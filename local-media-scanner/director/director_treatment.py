"""Deterministic, evidence-bound project-level director treatment."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from director.visual_schema import (
    BriefConfirmation,
    DirectorFunction,
    DirectorTreatment,
    EvidenceBackedStatement,
    EvidenceRef,
    IntentConditionedDecision,
    IntentDecisionBatch,
    ProjectCoverage,
    ProjectRoleAssignment,
    TreatmentChapter,
)


def _brief_ref(brief: BriefConfirmation, field: str) -> EvidenceRef:
    return EvidenceRef(
        artifact_path="brief_confirmation.json",
        field_path=f"normalized_fields.{field}",
        source_kind="user_brief",
        status="confirmed",
        confidence=1.0,
    )


def _key(ref: EvidenceRef) -> tuple[Any, ...]:
    return (
        ref.material_id,
        ref.artifact_path,
        ref.field_path,
        ref.source_kind,
        ref.status,
        ref.sha256,
    )


def _dedupe(refs: Iterable[EvidenceRef]) -> list[EvidenceRef]:
    output: list[EvidenceRef] = []
    seen: set[tuple[Any, ...]] = set()
    for ref in refs:
        if _key(ref) not in seen:
            output.append(ref)
            seen.add(_key(ref))
    return output


def _chapter(
    chapter_id: str,
    title: str,
    functions: tuple[DirectorFunction, ...],
    decisions: list[IntentConditionedDecision],
    assignments: list[ProjectRoleAssignment],
    brief: BriefConfirmation,
) -> TreatmentChapter | None:
    if assignments:
        selected_assignments = [
            assignment
            for assignment in assignments
            if assignment.director_function in functions
        ]
        if not selected_assignments:
            return None
        material_ids = list(
            dict.fromkeys(
                material_id
                for assignment in selected_assignments
                for material_id in assignment.material_ids
            )
        )
        refs = _dedupe(
            [
                ref
                for assignment in selected_assignments
                for ref in assignment.evidence_refs
            ]
            + [_brief_ref(brief, "travel_type")]
        )
        return TreatmentChapter(
            chapter_id=chapter_id,
            title=title,
            director_functions=[
                function
                for function in functions
                if any(
                    assignment.director_function == function
                    for assignment in selected_assignments
                )
            ],
            material_ids=material_ids,
            evidence_refs=refs,
        )

    selected = [
        item
        for item in decisions
        if item.bucket not in {"reject_suggestion", "review_required", "redundant"}
        and any(function in item.director_function_candidates for function in functions)
    ]
    active_functions = [
        function
        for function in functions
        if any(function in item.director_function_candidates for item in selected)
    ]
    if not selected or not active_functions:
        return None
    refs = _dedupe(
        [ref for item in selected for ref in item.evidence_refs]
        + [_brief_ref(brief, "travel_type")]
    )
    return TreatmentChapter(
        chapter_id=chapter_id,
        title=title,
        director_functions=active_functions,
        material_ids=[item.material_id for item in selected],
        evidence_refs=refs,
    )


def build_director_treatment(
    decisions: IntentDecisionBatch,
    coverage: ProjectCoverage,
    brief: BriefConfirmation,
) -> DirectorTreatment:
    """Build a concise treatment from confirmed, already-bounded artifacts."""

    if brief.status != "completed":
        raise ValueError("confirmed brief is required for director treatment")
    if decisions.status != "completed" or coverage.status != "completed":
        raise ValueError("completed decisions and coverage are required")
    fields = brief.normalized_fields
    assert fields.location and fields.travel_type and fields.style and fields.mood
    assert fields.rhythm
    chapters = [
        chapter
        for chapter in (
            _chapter(
                "arrival",
                f"进入{fields.location}",
                ("opening", "context"),
                decisions.items,
                decisions.role_assignments,
                brief,
            ),
            _chapter(
                "discovery",
                "行进与发现",
                ("progression", "emotion", "contrast", "breathing"),
                decisions.items,
                decisions.role_assignments,
                brief,
            ),
            _chapter(
                "culmination",
                "高潮与收束",
                ("climax", "ending"),
                decisions.items,
                decisions.role_assignments,
                brief,
            ),
        )
        if chapter is not None
    ]
    if not chapters:
        raise ValueError("confirmed observations provide no supported director function")

    mood_ref = _brief_ref(brief, "mood")
    travel_ref = _brief_ref(brief, "travel_type")
    rhythm_ref = _brief_ref(brief, "rhythm")
    material_refs = _dedupe(
        ref
        for item in decisions.items
        if item.bucket in {"core", "candidate"}
        for ref in item.evidence_refs
        if ref.material_id is not None
    )
    emotional_arc = [
        EvidenceBackedStatement(
            text=f"起点：以{fields.mood}建立观看预期。",
            evidence_refs=[mood_ref],
        ),
        EvidenceBackedStatement(
            text=f"展开：围绕{fields.travel_type}的已确认素材职责推进。",
            evidence_refs=_dedupe([travel_ref, *material_refs]),
        ),
    ]
    if "ending" in coverage.missing_director_functions:
        emotional_arc.append(
            EvidenceBackedStatement(
                text="收束：结尾职责缺失，保持开放式收束并列入补拍缺口。",
                evidence_refs=_dedupe([travel_ref, *coverage.evidence_refs]),
            )
        )
    else:
        if decisions.role_assignments:
            ending_refs = _dedupe(
                ref
                for assignment in decisions.role_assignments
                if assignment.director_function == "ending"
                for ref in assignment.evidence_refs
            )
        else:
            ending_refs = _dedupe(
                ref
                for item in decisions.items
                if "ending" in item.director_function_candidates
                for ref in item.evidence_refs
            )
        emotional_arc.append(
            EvidenceBackedStatement(
                text=f"收束：回到{fields.mood}的旅行余韵。",
                evidence_refs=_dedupe([mood_ref, *ending_refs]),
            )
        )

    pacing = {
        "low": "以较长呼吸组织章节，减少职责切换。",
        "medium": "保持稳定推进，在情绪和呼吸职责之间留出转换。",
        "high": "加快职责切换，但不越过已确认素材覆盖。",
    }[fields.rhythm]
    memberships = {
        bucket: [item.material_id for item in decisions.items if item.bucket == bucket]
        for bucket in (
            "core",
            "candidate",
            "redundant",
            "reject_suggestion",
            "review_required",
        )
    }
    all_refs = _dedupe(
        [
            _brief_ref(brief, "location"),
            _brief_ref(brief, "travel_type"),
            _brief_ref(brief, "style"),
            mood_ref,
            rhythm_ref,
        ]
        + [ref for item in decisions.items for ref in item.evidence_refs]
    )
    available = "—".join(coverage.available_director_functions) or "待确认"
    return DirectorTreatment(
        schema_version=decisions.schema_version,
        status="completed",
        mode="deterministic",
        logline=f"在{fields.location}，以{fields.style}方式组织一段{fields.mood}的{fields.travel_type}。",
        narrative_spine=available,
        chapters=chapters,
        emotional_arc=emotional_arc,
        pacing_strategy=pacing,
        pacing_evidence_refs=[rhythm_ref],
        core_materials=memberships["core"],
        candidate_materials=memberships["candidate"],
        redundant_materials=memberships["redundant"],
        reject_suggestions=memberships["reject_suggestion"],
        review_required=memberships["review_required"],
        coverage_gaps=[
            f"missing_director_function:{function}"
            for function in coverage.missing_director_functions
        ],
        role_assignments=decisions.role_assignments,
        evidence_refs=all_refs,
        unsupported_inferences=[],
    )


def _memberships(treatment: DirectorTreatment) -> dict[str, tuple[str, ...]]:
    return {
        "core": tuple(treatment.core_materials),
        "candidate": tuple(treatment.candidate_materials),
        "redundant": tuple(treatment.redundant_materials),
        "reject_suggestion": tuple(treatment.reject_suggestions),
        "review_required": tuple(treatment.review_required),
    }


def _all_evidence(treatment: DirectorTreatment) -> list[EvidenceRef]:
    return [
        *treatment.evidence_refs,
        *treatment.pacing_evidence_refs,
        *(ref for assignment in treatment.role_assignments for ref in assignment.evidence_refs),
        *(ref for chapter in treatment.chapters for ref in chapter.evidence_refs),
        *(ref for row in treatment.emotional_arc for ref in row.evidence_refs),
    ]


def validate_treatment_enhancement(
    baseline: DirectorTreatment,
    candidate: DirectorTreatment,
) -> None:
    """Reject structural/evidence drift before any future text-level review."""

    if _memberships(candidate) != _memberships(baseline):
        raise ValueError("enhancement cannot change deterministic membership")
    if candidate.coverage_gaps != baseline.coverage_gaps:
        raise ValueError("enhancement cannot change deterministic coverage gaps")
    allowed_evidence = {_key(ref) for ref in _all_evidence(baseline)}
    if any(_key(ref) not in allowed_evidence for ref in _all_evidence(candidate)):
        raise ValueError("enhancement contains evidence outside deterministic baseline")
    if candidate.unsupported_inferences:
        raise ValueError("enhancement cannot carry unsupported inferences")
    baseline_assignments = [
        (
            assignment.director_function,
            tuple(assignment.material_ids),
            assignment.assignment_score,
            assignment.selection_reason,
        )
        for assignment in baseline.role_assignments
    ]
    candidate_assignments = [
        (
            assignment.director_function,
            tuple(assignment.material_ids),
            assignment.assignment_score,
            assignment.selection_reason,
        )
        for assignment in candidate.role_assignments
    ]
    if candidate_assignments != baseline_assignments:
        raise ValueError("enhancement cannot change deterministic project roles")
    baseline_roles = sorted(
        (
            tuple(sorted(chapter.material_ids)),
            tuple(sorted(chapter.director_functions)),
        )
        for chapter in baseline.chapters
    )
    candidate_roles = sorted(
        (
            tuple(sorted(chapter.material_ids)),
            tuple(sorted(chapter.director_functions)),
        )
        for chapter in candidate.chapters
    )
    if candidate_roles != baseline_roles:
        raise ValueError("enhancement cannot change deterministic director roles")
