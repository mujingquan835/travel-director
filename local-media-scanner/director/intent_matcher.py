"""Evidence-bound deterministic matching of confirmed observations to a brief."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from itertools import combinations
from typing import Any

from director.visual_schema import (
    BriefConfirmation,
    ClipObservation,
    ClipObservationBatch,
    DirectorFunction,
    EvidenceRef,
    IntentConditionedDecision,
    IntentDecisionBatch,
    MaterialCapability,
    ObservationAssertion,
    ProjectCoverage,
    ProjectRoleAssignment,
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

CONTENT_CAPABILITIES: dict[str, tuple[MaterialCapability, ...]] = {
    "urban": ("environment_establishing", "spatial_transition"),
    "nature": ("environment_establishing", "quiet_breathing"),
    "culture_architecture": ("environment_establishing", "sensory_detail"),
    "food": ("sensory_detail", "human_emotion"),
    "transport": ("directional_entry", "movement_progression", "spatial_transition"),
    "lodging": ("quiet_breathing",),
    "attraction_activity": ("movement_progression",),
    "performance_event": ("event_energy", "human_emotion"),
    "people": ("human_emotion",),
    "detail": ("sensory_detail", "quiet_breathing"),
}

CLOSURE_CUES = ("离开", "回望", "告别", "落幕", "收束", "余韵", "放松", "静坐")

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


def _candidate_capabilities(
    assertions: dict[str, ObservationAssertion],
) -> tuple[list[MaterialCapability], list[str]]:
    capabilities: list[MaterialCapability] = []
    reasons: list[str] = []

    def add(capability: MaterialCapability, reason: str) -> None:
        if capability not in capabilities:
            capabilities.append(capability)
            reasons.append(reason)

    for content in _values(assertions.get("content_families")):
        for capability in CONTENT_CAPABILITIES.get(content, ()):
            add(capability, f"确认内容 {content} 支持单素材候选能力 {capability}。")
    activities = _values(assertions.get("activity_candidates"))
    if activities:
        add("movement_progression", "确认活动可作为运动推进候选，但不直接构成高潮。")
    visible_phrases = [
        *_values(assertions.get("subject_candidates")),
        *activities,
    ]
    if any(cue in phrase for cue in CLOSURE_CUES for phrase in visible_phrases):
        add("closure_resonance", "确认的可见动作包含离开、回望或收束候选线索。")
    return capabilities, reasons


def _assignment_evidence(
    decisions: list[IntentConditionedDecision],
    material_ids: list[str],
    brief: BriefConfirmation,
) -> list[EvidenceRef]:
    selected = set(material_ids)
    return _dedupe_refs(
        [_brief_ref(brief, "travel_type")]
        + [
            ref
            for item in decisions
            if item.material_id in selected
            for ref in item.evidence_refs
        ]
    )


def _assign_project_roles(
    decisions: list[IntentConditionedDecision],
    brief: BriefConfirmation,
) -> list[ProjectRoleAssignment]:
    eligible = [item for item in decisions if item.bucket in {"core", "candidate"}]
    order = {item.material_id: index for index, item in enumerate(decisions)}
    assignments: dict[DirectorFunction, ProjectRoleAssignment] = {}

    def ranked(
        capabilities: set[MaterialCapability], limit: int
    ) -> list[IntentConditionedDecision]:
        matches = [
            item
            for item in eligible
            if capabilities.intersection(item.candidate_capabilities)
        ]
        return sorted(
            matches,
            key=lambda item: (
                -item.relevance_score,
                -len(capabilities.intersection(item.candidate_capabilities)),
                order[item.material_id],
            ),
        )[:limit]

    def add(
        function: DirectorFunction,
        selected: list[IntentConditionedDecision],
        reason: str,
    ) -> None:
        if not selected:
            return
        material_ids = [item.material_id for item in selected]
        capability_strength = sum(len(item.candidate_capabilities) for item in selected)
        relevance = sum(item.relevance_score for item in selected) / len(selected)
        score = min(
            1.0,
            round(relevance * 0.8 + min(capability_strength, 4) * 0.05, 6),
        )
        assignments[function] = ProjectRoleAssignment(
            director_function=function,
            material_ids=material_ids,
            assignment_score=score,
            selection_reason=reason,
            evidence_refs=_assignment_evidence(decisions, material_ids, brief),
        )

    add(
        "opening",
        ranked({"environment_establishing", "directional_entry"}, 1),
        "在全部可用素材中按 Brief 相关度选择一个环境建立或进入感最强的开场。",
    )
    add(
        "context",
        ranked({"environment_establishing"}, 3),
        "用少量环境建立候选共同交代旅行空间，不把内容类别直接当作最终职责。",
    )
    add(
        "progression",
        ranked({"movement_progression", "spatial_transition"}, 3),
        "从运动推进与空间转换候选中按 Brief 相关度选择推进素材。",
    )
    add(
        "emotion",
        ranked({"human_emotion", "event_energy", "sensory_detail"}, 3),
        "从人物、事件与感官细节候选中组织情绪层，不依赖人数档位。",
    )
    add(
        "breathing",
        ranked({"quiet_breathing", "sensory_detail"}, 2),
        "从低强度与细节候选中选择呼吸素材，灯光只保留为解释性证据。",
    )
    add(
        "climax",
        ranked({"event_energy"}, 1),
        "高潮只从全项目事件能量候选中相对排序选出一条，普通活动不自动升级。",
    )
    add(
        "ending",
        ranked({"closure_resonance"}, 1),
        "结尾只从可见的离开、回望或收束候选中选择，不绑定住宿类别。",
    )

    contrast_candidates = [item for item in eligible if item.candidate_capabilities]
    if len(contrast_candidates) >= 2:
        left, right = max(
            combinations(contrast_candidates, 2),
            key=lambda pair: (
                len(
                    set(pair[0].candidate_capabilities)
                    ^ set(pair[1].candidate_capabilities)
                ),
                pair[0].relevance_score + pair[1].relevance_score,
                -order[pair[0].material_id],
                -order[pair[1].material_id],
            ),
        )
        if set(left.candidate_capabilities) != set(right.candidate_capabilities):
            add(
                "contrast",
                [left, right],
                "对比由两条候选能力明显不同的素材配对形成，而不是单素材静态标签。",
            )

    return [
        assignments[function]
        for function in CONTENT_FUNCTIONS_ORDER
        if function in assignments
    ]


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
        capabilities, capability_reasons = _candidate_capabilities(assertions)

        evidence = [
            ref
            for field in (
                "technical_usability",
                "content_families",
                "activity_candidates",
                "subject_candidates",
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
            capabilities = []
            capability_reasons = []
        elif review_required:
            bucket = "review_required"
            score = 0.0
            confidence = 1.0
            reasons = ["影响导演判断的观察字段仍未确认。"]
            capabilities = []
            capability_reasons = []
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
                candidate_capabilities=capabilities,
                capability_reasons=capability_reasons,
                director_function_candidates=[],
                reasons=reasons,
                evidence_refs=_dedupe_refs(evidence),
                user_confirmation_required=bucket == "review_required",
            )
        )
    role_assignments = _assign_project_roles(decisions, brief)
    return IntentDecisionBatch(
        schema_version="0.3.0",
        status="completed",
        items=decisions,
        role_assignments=role_assignments,
    )


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

    if decisions.schema_version == "0.3.0":
        assigned_functions = {
            assignment.director_function for assignment in decisions.role_assignments
        }
    else:
        usable_decisions = [
            item
            for item in decisions.items
            if item.bucket not in {"reject_suggestion", "review_required"}
        ]
        assigned_functions = {
            function
            for item in usable_decisions
            for function in item.director_function_candidates
        }
    available = [
        function
        for function in CONTENT_FUNCTIONS_ORDER
        if function in assigned_functions
    ]
    missing = [function for function in CONTENT_FUNCTIONS_ORDER if function not in available]
    uncertainty = [
        f"review_required:{item.material_id}"
        for item in decisions.items
        if item.bucket == "review_required"
    ]
    return ProjectCoverage(
        schema_version=decisions.schema_version,
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
