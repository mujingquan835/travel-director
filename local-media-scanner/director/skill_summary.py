"""Compact, evidence-backed summaries for completed or blocked Skill runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from director.project import (
    ProjectConflict,
    ProjectPaths,
    _atomic_write,
    _canonical_bytes,
    load_project_state,
    open_project,
    preflight_visual_stage_checked,
    record_supporting_artifact,
    record_visual_stage_checked,
)
from director.schema import ExternalCallRecord
from director.visual_schema import (
    Bucket,
    VisualProjectState,
    VisualReviewArtifact,
    VisualStrictModel,
    validate_visual_stage_artifact,
)


EXTERNAL_SERVICES = (
    "quduoduo",
    "dreamina",
    "netease_music",
    "qq_music",
    "spotify",
    "apple_music",
    "music_generation",
)

_BUCKET_FIELDS: tuple[tuple[Bucket, str], ...] = (
    ("core", "core_materials"),
    ("candidate", "candidate_materials"),
    ("redundant", "redundant_materials"),
    ("reject_suggestion", "reject_suggestions"),
    ("review_required", "review_required"),
)


class SkillRunSummary(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    project_mode: Literal["automatic", "assisted", "blocked"]
    material_count: int = Field(ge=0)
    successful_material_count: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    bucket_counts: dict[Bucket, int]
    logline: str | None = None
    chapter_titles: list[str] = Field(default_factory=list)
    material_gaps: list[str] = Field(default_factory=list)
    music_prompts: list[str] = Field(default_factory=list, max_length=3)
    unsupported_inferences: list[str] = Field(default_factory=list)
    artifact_paths: dict[str, str]
    external_call_count: Literal[0] = 0
    external_services: dict[str, Literal["not_executed"]]

    @field_validator("music_prompts")
    @classmethod
    def prompts_stay_bounded(cls, value: list[str]) -> list[str]:
        if any(len(prompt) > 200 for prompt in value):
            raise ValueError("music prompts must be at most 200 characters")
        return value

    @model_validator(mode="after")
    def summary_fields_are_consistent(self) -> "SkillRunSummary":
        if set(self.bucket_counts) != {bucket for bucket, _ in _BUCKET_FIELDS}:
            raise ValueError("bucket_counts must include every director bucket")
        if self.project_mode == "blocked":
            if self.music_prompts:
                raise ValueError("blocked summaries must not expose music prompts")
            return self
        if len(self.music_prompts) != 3:
            raise ValueError("completed summaries must include exactly three prompts")
        return self


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectConflict(f"invalid JSON artifact: {path}") from exc


def _load_stage(paths, state, stage: str) -> dict[str, object] | None:
    artifact = paths.artifact_for(stage)
    recorded_hash = state.completed_artifact_hashes.get(stage)
    if recorded_hash is None:
        return None
    if not artifact.is_file():
        raise ProjectConflict(f"completed artifact is missing: {stage}")
    from director.project import _sha256_file

    if _sha256_file(artifact) != recorded_hash:
        raise ProjectConflict(f"completed artifact drifted: {stage}")
    return validate_visual_stage_artifact(stage, _load_json(artifact))


def _artifact_paths(paths, state) -> dict[str, str]:
    ordered = {
        name: str((paths.root / relative).resolve())
        for name, relative in state.artifact_paths.items()
        if name != "input_manifest" or (paths.root / relative).is_file()
    }
    if paths.review_route.is_file():
        ordered["review_route"] = str(paths.review_route.resolve())
    ordered["final_summary"] = str(paths.final_summary.resolve())
    return ordered


def _external_call_payload(paths, state) -> list[dict[str, object]]:
    recorded_hash = state.completed_artifact_hashes.get("external_calls")
    if recorded_hash is None or not paths.external_calls.is_file():
        raise ProjectConflict("external call ledger is missing")
    from director.project import _sha256_file

    if _sha256_file(paths.external_calls) != recorded_hash:
        raise ProjectConflict("external call ledger drifted")
    payload = _load_json(paths.external_calls)
    if not isinstance(payload, list):
        raise ProjectConflict("external call ledger must be a JSON array")
    return [
        ExternalCallRecord.model_validate(item).model_dump(mode="json")
        for item in payload
    ]


def _bucket_counts(treatment: dict[str, object] | None) -> dict[Bucket, int]:
    if treatment is None:
        return {bucket: 0 for bucket, _ in _BUCKET_FIELDS}
    return {
        bucket: len(treatment[field])
        for bucket, field in _BUCKET_FIELDS
    }


def _review_required_count(observations: dict[str, object] | None) -> int:
    if observations is None:
        return 0
    return sum(
        1
        for item in observations["items"]
        if item.get("review_required_fields")
    )


def _validate_cross_artifact_bindings(
    paths: ProjectPaths,
    state: VisualProjectState,
    *,
    intent_brief: dict[str, object] | None,
    brief_confirmation: dict[str, object] | None,
    treatment: dict[str, object] | None,
    director_review: dict[str, object] | None,
) -> None:
    if intent_brief is not None and brief_confirmation is not None:
        expected_draft_hash = state.completed_artifact_hashes["intent_brief"]
        confirmation_hash = brief_confirmation["draft_sha256"]
        if confirmation_hash != expected_draft_hash:
            preserved_draft = paths.visual_drafts / "intent_brief.json"
            preserved_matches = False
            if preserved_draft.is_file():
                try:
                    preserved_value = validate_visual_stage_artifact(
                        "intent_brief", _load_json(preserved_draft)
                    )
                except (ProjectConflict, ValueError):
                    preserved_value = None
                preserved_matches = (
                    preserved_value == intent_brief
                    and hashlib.sha256(preserved_draft.read_bytes()).hexdigest()
                    == confirmation_hash
                )
            if not preserved_matches:
                raise ProjectConflict("brief confirmation draft hash mismatch")
    if treatment is not None and director_review is not None:
        expected_treatment_hash = state.completed_artifact_hashes[
            "director_treatment"
        ]
        if director_review["treatment_sha256"] != expected_treatment_hash:
            raise ProjectConflict("director review treatment hash mismatch")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def build_skill_run_summary(project_root: Path) -> SkillRunSummary:
    paths = open_project(project_root.resolve())
    state = load_project_state(paths)
    if state.schema_version != "0.2.0":
        raise ProjectConflict("skill summary requires a V0.2 visual project")

    observations = _load_stage(paths, state, "clip_observations")
    intent_brief = _load_stage(paths, state, "intent_brief")
    brief_confirmation = _load_stage(paths, state, "brief_confirmation")
    intent_decisions = _load_stage(paths, state, "intent_decisions")
    coverage = _load_stage(paths, state, "project_coverage")
    treatment = _load_stage(paths, state, "director_treatment")
    review = _load_stage(paths, state, "director_review")
    prompts = _load_stage(paths, state, "music_style_recommendations")
    external_calls = _external_call_payload(paths, state)
    _validate_cross_artifact_bindings(
        paths,
        state,
        intent_brief=intent_brief,
        brief_confirmation=brief_confirmation,
        treatment=treatment,
        director_review=review,
    )

    bucket_counts = _bucket_counts(treatment)
    material_count = len(observations["items"]) if observations is not None else 0
    unavailable_count = (
        sum(
            1
            for item in observations["items"]
            if item["observation_status"] == "unavailable"
        )
        if observations is not None
        else 0
    )
    review_required_count = (
        bucket_counts["review_required"]
        if treatment is not None
        else _review_required_count(observations)
    )
    successful_material_count = (
        sum(bucket_counts.values()) - bucket_counts["review_required"]
        if treatment is not None
        else max(0, material_count - review_required_count - unavailable_count)
    )

    completion_gates: list[str] = []
    if observations is None or observations["status"] != "completed":
        completion_gates.append("clip_observations")
    brief_is_confirmed = (
        brief_confirmation is not None
        and brief_confirmation["status"] == "completed"
    )
    if intent_brief is None or (
        intent_brief["status"] != "completed"
        and not (intent_brief["status"] == "partial" and brief_is_confirmed)
    ):
        completion_gates.append("intent_brief")
    if brief_confirmation is None or brief_confirmation["status"] != "completed":
        completion_gates.append("brief_confirmation")
    if intent_decisions is None or intent_decisions["status"] != "completed":
        completion_gates.append("intent_decisions")
    if coverage is None or coverage["status"] != "completed":
        completion_gates.append("project_coverage")
    if treatment is None or treatment["status"] != "completed":
        completion_gates.append("director_treatment")
    elif treatment["unsupported_inferences"]:
        completion_gates.append("unsupported_inferences")
    if review is None or review["status"] != "completed":
        completion_gates.append("director_review")
    if (
        prompts is None
        or prompts["status"] != "completed"
        or len(prompts["items"]) != 3
        or any(len(item["generation_prompt"]) > 200 for item in prompts["items"])
    ):
        completion_gates.append("music_style_recommendations")
    if external_calls:
        completion_gates.append("external_calls")
    material_gaps = _dedupe(
        (list(treatment["coverage_gaps"]) if treatment is not None else [])
        + completion_gates
    )

    project_mode: Literal["automatic", "assisted", "blocked"]
    music_prompts: list[str]
    if completion_gates:
        project_mode = "blocked"
        music_prompts = []
    else:
        observation_mode = observations["mode"]
        review_mode = review["mode"]
        project_mode = (
            "automatic"
            if observation_mode == "automatic" and review_mode == "automatic"
            else "assisted"
        )
        music_prompts = [
            item["generation_prompt"] for item in prompts["items"]
        ]

    return SkillRunSummary(
        project_mode=project_mode,
        material_count=material_count,
        successful_material_count=successful_material_count,
        review_required_count=review_required_count,
        unavailable_count=unavailable_count,
        bucket_counts=bucket_counts,
        logline=treatment["logline"] if treatment is not None else None,
        chapter_titles=(
            [chapter["title"] for chapter in treatment["chapters"]]
            if treatment is not None
            else []
        ),
        material_gaps=material_gaps,
        music_prompts=music_prompts,
        unsupported_inferences=(
            list(treatment["unsupported_inferences"]) if treatment is not None else []
        ),
        artifact_paths=_artifact_paths(paths, state),
        external_services={
            name: "not_executed" for name in EXTERNAL_SERVICES
        },
    )


def write_skill_run_summary(project_root: Path) -> SkillRunSummary:
    """Write and publish the canonical summary without changing its gates."""

    paths = open_project(project_root.resolve())
    summary = build_skill_run_summary(paths.root)
    visual_review = None
    draft = paths.visual_drafts / "visual_review.summary.json"
    if summary.project_mode != "blocked":
        state = load_project_state(paths)
        visual_review = VisualReviewArtifact(
            status="completed",
            report_path=str(paths.final_summary.resolve()),
            source_artifact_hashes={
                stage: state.completed_artifact_hashes[stage]
                for stage in (
                    "clip_observations",
                    "brief_confirmation",
                    "director_treatment",
                    "director_review",
                    "music_style_recommendations",
                )
            },
            external_call_count=0,
        )
        preflight_visual_stage_checked(
            paths,
            "visual_review",
            draft,
            visual_review,
        )
    summary_payload = _canonical_bytes(summary.model_dump(mode="json"))
    if (
        not paths.final_summary.is_file()
        or paths.final_summary.read_bytes() != summary_payload
    ):
        _atomic_write(paths.final_summary, summary_payload)
    if visual_review is not None:
        record_supporting_artifact(
            paths,
            draft,
            visual_review.model_dump(mode="json"),
        )
        record_visual_stage_checked(paths, "visual_review", draft)
    return summary
