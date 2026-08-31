"""Evidence-bound deterministic matching of confirmed observations to a brief."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

from director.visual_schema import (
    BriefConfirmation,
    ClipObservation,
    ClipObservationBatch,
    DirectorFunction,
    EvidenceRef,
    IntentConditionedDecision,
    IntentDecisionBatch,
    ObservationAssertion,
    ProjectCoverage,
)


SUPPORTED_FIELDS = {
    "technical_usability",
    "content_families",
    "setting",
    "lighting",
    "people_presence",
    "people_count_band",
    "subject_candidates",
    "activity_candidates",
    "orientation",
    "motion_level",
    "duplicate_group_id",
}

CONTENT_FUNCTIONS: dict[str, tuple[DirectorFunction, ...]] = {
    "urban": ("opening", "context"),
    "nature": ("context", "breathing"),
    "culture_architecture": ("context",),
    "food": ("breathing", "emotion"),
    "transport": ("opening", "progression"),
    "lodging": ("ending",),
    "attraction_activity": ("progression", "climax"),
    "performance_event": ("emotion", "climax"),
    "people": ("emotion",),
    "detail": ("breathing",),
}

TRAVEL_PREFERENCES: dict[str, set[str]] = {
    "城市漫游": {"urban", "culture_architecture", "transport", "people", "detail"},
    "美食旅行": {"food", "people", "urban", "detail"},
    "自然旅行": {"nature", "transport", "people", "detail"},
    "人文旅行": {"culture_architecture", "people", "urban", "detail"},
    "亲子旅行": {"people", "attraction_activity", "food", "nature"},
    "自驾旅行": {"transport", "nature", "urban", "lodging"},
    "度假旅行": {"lodging", "nature", "food", "people"},
}


def _assertions(item: ClipObservation) -> dict[str, ObservationAssertion]:
    return {
        assertion.field: assertion
        for assertion in item.assertions
        if assertion.field in SUPPORTED_FIELDS
    }


def _values(assertion: ObservationAssertion | None) -> list[str]:
    if assertion is None or assertion.value is None:
        return []
    if isinstance(assertion.value, list):
        return [str(value) for value in assertion.value]
    return [str(assertion.value)]


def _dedupe_refs(refs: Iterable[EvidenceRef]) -> list[EvidenceRef]:
    output: list[EvidenceRef] = []
    seen: set[tuple[Any, ...]] = set()
    for ref in refs:
        key = (
            ref.material_id,
            ref.artifact_path,
            ref.field_path,
            ref.source_kind,
            ref.status,
            ref.sha256,
        )
        if key not in seen:
            output.append(ref)
            seen.add(key)
    return output


def _brief_ref(brief: BriefConfirmation, field: str) -> EvidenceRef:
    return EvidenceRef(
        artifact_path="brief_confirmation.json",
        field_path=f"normalized_fields.{field}",
        source_kind="user_brief",
        status="confirmed",
        confidence=1.0,
    )


def _derived_observation_ref(item: ClipObservation, field_path: str, status: str) -> EvidenceRef:
    return EvidenceRef(
        material_id=item.material.material_id,
        artifact_path="clip_observations.json",
        field_path=field_path,
        source_kind="director_rule",
        status=status,
    )


def _preferred_content(travel_type: str) -> set[str]:
    if travel_type in TRAVEL_PREFERENCES:
        return TRAVEL_PREFERENCES[travel_type]
    for keyword, values in (
        ("城市", TRAVEL_PREFERENCES["城市漫游"]),
        ("美食", TRAVEL_PREFERENCES["美食旅行"]),
        ("自然", TRAVEL_PREFERENCES["自然旅行"]),
        ("人文", TRAVEL_PREFERENCES["人文旅行"]),
        ("亲子", TRAVEL_PREFERENCES["亲子旅行"]),
        ("自驾", TRAVEL_PREFERENCES["自驾旅行"]),
        ("度假", TRAVEL_PREFERENCES["度假旅行"]),
    ):
        if keyword in travel_type:
            return values
    return set()


def build_intent_decisions(
    observations: ClipObservationBatch,
    brief: BriefConfirmation,
) -> IntentDecisionBatch:
    """Create five-bucket decisions without model calls or unsupported semantics."""

    if observations.status != "completed" or any(
        item.review_required_fields for item in observations.items
    ):
        raise ValueError("confirmed observations are required for director decisions")
    if brief.status != "completed":
        raise ValueError("confirmed brief is required for director decisions")

    travel_type = brief.normalized_fields.travel_type
    orientation = brief.normalized_fields.orientation
    assert travel_type is not None and orientation is not None
    preferred = _preferred_content(travel_type)
    seen_duplicate_groups: set[str] = set()
    decisions: list[IntentConditionedDecision] = []

    for item in observations.items:
        assertions = _assertions(item)
        usability_assertion = assertions.get("technical_usability")
        usability = _values(usability_assertion)
        content = _values(assertions.get("content_families"))
        duplicate_assertion = assertions.get("duplicate_group_id")
        duplicate_values = (
            _values(duplicate_assertion)
            if duplicate_assertion
            and duplicate_assertion.status in {"measured", "confirmed"}
            else []
        )
        duplicate_group = duplicate_values[0] if duplicate_values else None
        hard_failure = item.observation_status == "unavailable" or (
            usability_assertion is not None
            and usability_assertion.status in {"measured", "confirmed"}
            and "unusable" in usability
        )
        review_required = (
            bool(item.review_required_fields)
            or item.observation_status in {"abstained", "unavailable"}
            or "review_required" in usability
        )
        matched_content = [value for value in content if value in preferred]
        functions: list[DirectorFunction] = []
        for value in content:
            for function in CONTENT_FUNCTIONS.get(value, ()):
                if function not in functions:
                    functions.append(function)
        if _values(assertions.get("activity_candidates")):
            for function in ("progression", "climax"):
                if function not in functions:
                    functions.append(function)

        evidence = [
            ref
            for field in (
                "technical_usability",
                "content_families",
                "activity_candidates",
                "duplicate_group_id",
            )
            for ref in (assertions[field].evidence_refs if field in assertions else [])
        ]
        if not evidence:
            evidence.append(
                _derived_observation_ref(item, "observation_status", "unavailable")
            )
        evidence.append(_brief_ref(brief, "travel_type"))

        if hard_failure:
            bucket = "reject_suggestion"
            score = 0.0
            confidence = 1.0
            reasons = ["确认观察包含不可用或技术失败硬证据。"]
            functions = []
        elif review_required:
            bucket = "review_required"
            score = 0.0
            confidence = 1.0
            reasons = ["影响导演判断的观察字段仍未确认。"]
            functions = []
        elif duplicate_group and duplicate_group in seen_duplicate_groups:
            bucket = "redundant"
            score = 0.5
            confidence = 1.0
            reasons = [f"确认重复组 {duplicate_group} 已有更早素材，保留为重复备选。"]
        elif matched_content:
            bucket = "core"
            score = 0.9
            confidence = 1.0
            reasons = [
                f"确认内容 { '、'.join(matched_content) } 与 Brief 的 {travel_type} 直接匹配。"
            ]
        else:
            bucket = "candidate"
            score = 0.55 if content else 0.35
            confidence = 0.8 if content else 0.6
            reasons = [
                "素材有已确认内容证据，但不是当前旅行类型的直接核心匹配；保留候选，不硬淘汰。"
            ]
        if duplicate_group and bucket not in {"reject_suggestion", "review_required"}:
            seen_duplicate_groups.add(duplicate_group)
        decisions.append(
            IntentConditionedDecision(
                material_id=item.material.material_id,
                bucket=bucket,
                relevance_score=score,
                confidence=confidence,
                director_function_candidates=functions,
                reasons=reasons,
                evidence_refs=_dedupe_refs(evidence),
                user_confirmation_required=bucket == "review_required",
            )
        )
    return IntentDecisionBatch(status="completed", items=decisions)


def build_project_coverage(
    observations: ClipObservationBatch,
    decisions: IntentDecisionBatch,
) -> ProjectCoverage:
    """Summarize only whitelisted confirmed observation fields and decision roles."""

    if decisions.status != "completed":
        raise ValueError("completed intent decisions are required for project coverage")
    by_material = {item.material.material_id: item for item in observations.items}
    if set(by_material) != {item.material_id for item in decisions.items}:
        raise ValueError("observation and intent decision memberships differ")

    distributions: dict[str, Counter[str]] = {
        "content": Counter(),
        "lighting": Counter(),
        "people": Counter(),
        "motion": Counter(),
    }
    duplicate_groups: defaultdict[str, list[str]] = defaultdict(list)
    evidence: list[EvidenceRef] = []
    for material_id, item in by_material.items():
        assertions = _assertions(item)
        for value in _values(assertions.get("content_families")):
            distributions["content"][value] += 1
        for value in _values(assertions.get("lighting")):
            distributions["lighting"][value] += 1
        for value in _values(assertions.get("people_presence")):
            distributions["people"][value] += 1
        for value in _values(assertions.get("motion_level")):
            distributions["motion"][value] += 1
        duplicate_assertion = assertions.get("duplicate_group_id")
        if duplicate_assertion and duplicate_assertion.status in {"measured", "confirmed"}:
            for group in _values(duplicate_assertion):
                duplicate_groups[group].append(material_id)
        evidence.extend(
            ref
            for assertion in assertions.values()
            for ref in assertion.evidence_refs
        )

    usable_decisions = [
        item
        for item in decisions.items
        if item.bucket not in {"reject_suggestion", "review_required"}
    ]
    available = [
        function
        for function in CONTENT_FUNCTIONS_ORDER
        if any(function in item.director_function_candidates for item in usable_decisions)
    ]
    missing = [function for function in CONTENT_FUNCTIONS_ORDER if function not in available]
    uncertainty = [
        f"review_required:{item.material_id}"
        for item in decisions.items
        if item.bucket == "review_required"
    ]
    return ProjectCoverage(
        status="completed",
        content_distribution=dict(distributions["content"]),
        lighting_distribution=dict(distributions["lighting"]),
        people_distribution=dict(distributions["people"]),
        motion_distribution=dict(distributions["motion"]),
        duplicate_groups={
            group: material_ids
            for group, material_ids in duplicate_groups.items()
            if len(material_ids) > 1
        },
        available_director_functions=available,
        missing_director_functions=missing,
        uncertainty_summary=uncertainty,
        evidence_refs=_dedupe_refs(evidence),
    )


CONTENT_FUNCTIONS_ORDER: tuple[DirectorFunction, ...] = (
    "opening",
    "context",
    "progression",
    "emotion",
    "contrast",
    "breathing",
    "climax",
    "ending",
)
