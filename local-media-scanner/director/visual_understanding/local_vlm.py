"""Weight-free contract boundary for one gated local MLX VLM candidate."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import Field, model_validator

from director.visual_schema import (
    ClipObservation,
    EvidenceRef,
    MaterialRef,
    ObservationAssertion,
    ProviderCapabilities,
    VisualStrictModel,
)


OBSERVATION_FIELDS = (
    "technical_usability",
    "content_families",
    "setting",
    "lighting",
    "people_presence",
    "people_count_band",
    "subject_candidates",
    "activity_candidates",
)

LOCAL_VLM_PROMPT = """你只负责描述多张代表帧中直接可见的画面，并输出一个 JSON 对象。
不得猜测具体地点、人物身份、事件名称、导演职责、素材优先级或剪辑时间区间。
不确定时必须使用 unknown 或空列表，并把字段名写入 unknown_fields。
只允许这些字段：technical_usability, content_families, setting, lighting,
people_presence, people_count_band, subject_candidates, activity_candidates,
unknown_fields, confidence_by_field。confidence_by_field 只表达画面证据置信度。
"""


class LocalVlmConfig(VisualStrictModel):
    model_id: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_package: Literal["mlx-vlm"] = "mlx-vlm"
    runtime_version: str = Field(min_length=1)
    max_images: int = Field(default=5, ge=1, le=5)
    max_image_edge: int = Field(default=768, ge=256, le=1024)
    max_tokens: int = Field(default=384, ge=64, le=1024)
    review_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class WarmThroughputAssessment(VisualStrictModel):
    measured_items: int = Field(ge=1)
    mean_item_seconds: float = Field(gt=0.0)
    target_items: int = Field(ge=1)
    projected_total_seconds: float = Field(gt=0.0)
    max_total_seconds: float = Field(gt=0.0)
    qualified: bool


def assess_warm_throughput(
    item_seconds: list[float], *, target_items: int, max_total_seconds: float
) -> WarmThroughputAssessment:
    if not item_seconds or any(value <= 0.0 for value in item_seconds):
        raise ValueError("warm throughput requires positive item timings")
    mean_item_seconds = sum(item_seconds) / len(item_seconds)
    projected_total_seconds = mean_item_seconds * target_items
    return WarmThroughputAssessment(
        measured_items=len(item_seconds),
        mean_item_seconds=mean_item_seconds,
        target_items=target_items,
        projected_total_seconds=projected_total_seconds,
        max_total_seconds=max_total_seconds,
        qualified=projected_total_seconds <= max_total_seconds,
    )


ContentFamily = Literal[
    "urban",
    "nature",
    "culture_architecture",
    "food",
    "transport",
    "lodging",
    "attraction_activity",
    "performance_event",
    "people",
    "detail",
    "other",
    "unknown",
]


class LocalVlmResponse(VisualStrictModel):
    technical_usability: Literal[
        "usable", "unusable", "review_required", "unknown"
    ]
    content_families: list[ContentFamily]
    setting: Literal["indoor", "outdoor", "mixed", "unknown"]
    lighting: Literal["daylight", "night", "artificial", "mixed", "unknown"]
    people_presence: Literal["present", "absent", "unknown"]
    people_count_band: Literal["none", "single", "few", "crowd", "unknown"]
    subject_candidates: list[str]
    activity_candidates: list[str]
    unknown_fields: list[str]
    confidence_by_field: dict[str, float]

    @model_validator(mode="after")
    def confidence_and_abstention_are_explicit(self) -> "LocalVlmResponse":
        if "unknown" in self.content_families and self.content_families != ["unknown"]:
            raise ValueError("unknown content family cannot be mixed with other values")
        if self.people_presence == "absent" and self.people_count_band not in {
            "none",
            "unknown",
        }:
            raise ValueError("people_presence absent contradicts people_count_band")
        if self.people_presence == "present" and self.people_count_band == "none":
            raise ValueError("people_presence present contradicts people_count_band")
        unknown = set(self.unknown_fields)
        supported = set(OBSERVATION_FIELDS)
        if not unknown.issubset(supported):
            raise ValueError("unknown_fields contains an unsupported field")
        if not set(self.confidence_by_field).issubset(supported):
            raise ValueError("confidence_by_field contains an unsupported field")
        values = self.field_values()
        computed_unknown = {
            field for field, value in values.items() if _is_unknown_value(field, value)
        }
        if unknown != computed_unknown:
            raise ValueError("unknown_fields must exactly match abstained values")
        missing_confidence = [
            field
            for field in OBSERVATION_FIELDS
            if field not in unknown and field not in self.confidence_by_field
        ]
        if missing_confidence:
            raise ValueError(
                "confidence is missing for supported fields: "
                + ", ".join(missing_confidence)
            )
        if any(not 0.0 <= value <= 1.0 for value in self.confidence_by_field.values()):
            raise ValueError("confidence values must be between zero and one")
        return self

    def field_values(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in OBSERVATION_FIELDS}


def _is_unknown_value(field: str, value: Any) -> bool:
    if field in {"content_families", "subject_candidates", "activity_candidates"}:
        return not value or value == ["unknown"]
    return value == "unknown"


def _unwrap_json_fence(raw: str) -> str:
    stripped = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def parse_local_vlm_response(raw: str) -> LocalVlmResponse:
    """Parse one strict response; only a surrounding JSON fence is repaired."""

    try:
        payload = json.loads(_unwrap_json_fence(raw))
        return LocalVlmResponse.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid local VLM response: {exc}") from exc


LocalVlmRunner = Callable[[str, list[str], LocalVlmConfig], str]


class LocalVlmProvider:
    """Injectable provider boundary; the real MLX runner is added only after approval."""

    def __init__(self, config: LocalVlmConfig, runner: LocalVlmRunner) -> None:
        self.config = config
        self._runner = runner

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name="local_vlm",
            local_only=True,
            supports_abstention=True,
            requires_model_weights=True,
        )

    def observe(self, material: MaterialRef, evidence: dict[str, Any]) -> ClipObservation:
        frame_paths = [str(path) for path in evidence.get("frame_paths", [])]
        if not frame_paths:
            raise ValueError("local VLM observation requires representative frames")
        if len(frame_paths) > self.config.max_images:
            raise ValueError("local VLM observation exceeds max_images")
        artifact_path = str(evidence.get("response_artifact_path", "")).strip()
        if not artifact_path:
            raise ValueError("local VLM observation requires response_artifact_path")
        raw = self._runner(LOCAL_VLM_PROMPT, frame_paths, self.config)
        parsed = parse_local_vlm_response(raw)
        response_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assertions: list[ObservationAssertion] = []
        review_required: list[str] = []
        for field, value in parsed.field_values().items():
            if field in parsed.unknown_fields:
                assertions.append(ObservationAssertion(field=field, status="abstained"))
                review_required.append(field)
                continue
            confidence = parsed.confidence_by_field[field]
            assertions.append(
                ObservationAssertion(
                    field=field,
                    value=value,
                    status="candidate",
                    confidence=confidence,
                    evidence_refs=[
                        EvidenceRef(
                            material_id=material.material_id,
                            artifact_path=artifact_path,
                            field_path=field,
                            source_kind="visual_provider",
                            status="candidate",
                            confidence=confidence,
                            sha256=response_hash,
                        )
                    ],
                )
            )
            if (
                confidence < self.config.review_confidence_threshold
                or (field == "technical_usability" and value == "review_required")
            ):
                review_required.append(field)
        review_required = sorted(set(review_required))
        return ClipObservation(
            material=material,
            provider="local_vlm",
            observation_status="abstained" if review_required else "automatic",
            assertions=assertions,
            unknown_fields=sorted(parsed.unknown_fields),
            review_required_fields=review_required,
        )
