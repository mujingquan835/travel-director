from __future__ import annotations

import pytest

from director.intent_matcher import build_intent_decisions, build_project_coverage
from director.visual_schema import (
    BriefConfirmation,
    ClipObservation,
    ClipObservationBatch,
    EvidenceRef,
    IntentDecisionBatch,
    MaterialRef,
    ObservationAssertion,
    ProjectRoleAssignment,
)


def _material_id(index: int) -> str:
    return f"sha256:{index:064x}"


def _evidence(index: int, field: str, *, status: str = "confirmed") -> EvidenceRef:
    return EvidenceRef(
        material_id=_material_id(index),
        artifact_path="confirmed_observations.json",
        field_path=f"items[{index - 1}].assertions.{field}",
        source_kind="user_confirmation",
        status=status,
        confidence=1.0 if status == "confirmed" else None,
        sha256="a" * 64,
    )


def _assertion(index: int, field: str, value: object) -> ObservationAssertion:
    return ObservationAssertion(
        field=field,
        value=value,
        status="confirmed",
        confidence=1.0,
        evidence_refs=[_evidence(index, field)],
    )


def six_confirmed_observations() -> ClipObservationBatch:
    specs = [
        ("urban", "dup-old-town"),
        ("culture_architecture", "dup-old-town"),
        ("food", None),
        ("nature", None),
        ("people", None),
        ("attraction_activity", None),
    ]
    items = []
    for index, (content, duplicate_group) in enumerate(specs, start=1):
        assertions = [
            _assertion(index, "technical_usability", "usable"),
            _assertion(index, "content_families", [content]),
            _assertion(index, "setting", "outdoor"),
        ]
        if duplicate_group:
            assertions.append(
                _assertion(index, "duplicate_group_id", duplicate_group)
            )
        if content == "attraction_activity":
            assertions.append(
                _assertion(index, "activity_candidates", ["步行游览"])
            )
        if index == 1:
            assertions.append(_assertion(index, "celebrity_identity", "某位名人"))
        items.append(
            ClipObservation(
                material=MaterialRef(
                    material_id=_material_id(index),
                    relative_path=f"trip/clip-{index:02d}.mov",
                    source_sha256=f"{index:064x}",
                    size_bytes=100,
                    mtime_ns=index,
                    duration_seconds=8.0,
                    fps=25.0,
                    orientation="portrait",
                ),
                provider="manual-fixture",
                observation_status="assisted",
                assertions=assertions,
            )
        )
    return ClipObservationBatch(status="completed", mode="assisted", items=items)


def relationship_observations() -> ClipObservationBatch:
    specs = [
        ("urban", "low", []),
        ("nature", "low", []),
        ("transport", "medium", ["步行进入"]),
        ("attraction_activity", "high", ["游览项目"]),
        ("performance_event", "high", ["现场演出"]),
        ("detail", "low", ["回望离开"]),
        ("lodging", "low", []),
    ]
    items = []
    for index, (content, motion, activities) in enumerate(specs, start=1):
        assertions = [
            _assertion(index, "technical_usability", "usable"),
            _assertion(index, "content_families", [content]),
            _assertion(index, "setting", "outdoor"),
            _assertion(index, "motion_level", motion),
        ]
        if activities:
            assertions.append(_assertion(index, "activity_candidates", activities))
        items.append(
            ClipObservation(
                material=MaterialRef(
                    material_id=_material_id(index),
                    relative_path=f"relations/clip-{index:02d}.mov",
                    source_sha256=f"{index:064x}",
                    size_bytes=100,
                    mtime_ns=index,
                    duration_seconds=8.0,
                    fps=25.0,
                    orientation="portrait",
                ),
                provider="relationship-fixture",
                observation_status="assisted",
                assertions=assertions,
            )
        )
    return ClipObservationBatch(status="completed", mode="assisted", items=items)


def confirmed_brief(travel_type: str) -> BriefConfirmation:
    mood = {
        "城市漫游": "探索",
        "美食旅行": "温暖",
        "自然旅行": "宁静",
    }[travel_type]
    return BriefConfirmation(
        status="completed",
        draft_sha256="b" * 64,
        normalized_fields={
            "location": "开封",
            "travel_type": travel_type,
            "target_duration_seconds": 60,
            "orientation": "portrait",
            "style": "纪实",
            "mood": mood,
            "rhythm": "medium",
        },
        changed_fields=[],
        confirmed_at="2026-08-31T15:00:00+08:00",
    )


def test_six_materials_change_roles_across_three_briefs_without_a_model() -> None:
    observations = six_confirmed_observations()
    outputs = {
        travel_type: build_intent_decisions(observations, confirmed_brief(travel_type))
        for travel_type in ("城市漫游", "美食旅行", "自然旅行")
    }

    by_brief = {
        name: {item.material_id: item for item in batch.items}
        for name, batch in outputs.items()
    }
    assert by_brief["城市漫游"][_material_id(1)].bucket == "core"
    assert by_brief["自然旅行"][_material_id(4)].bucket == "core"
    assert by_brief["美食旅行"][_material_id(3)].bucket == "core"
    assert by_brief["自然旅行"][_material_id(1)].bucket == "candidate"
    assert by_brief["美食旅行"][_material_id(4)].bucket == "candidate"
    assert all(
        by_brief[name][_material_id(2)].bucket == "redundant"
        for name in by_brief
    )
    signatures = {
        tuple((item.material_id, item.bucket) for item in batch.items)
        for batch in outputs.values()
    }
    assert len(signatures) == 3


def test_every_bucket_and_role_carries_material_and_brief_evidence() -> None:
    decisions = build_intent_decisions(
        six_confirmed_observations(), confirmed_brief("城市漫游")
    )

    for item in decisions.items:
        assert item.evidence_refs
        assert any(ref.material_id == item.material_id for ref in item.evidence_refs)
        assert any(ref.source_kind == "user_brief" for ref in item.evidence_refs)
    payload = decisions.model_dump_json()
    assert "某位名人" not in payload
    assert "celebrity_identity" not in payload


def test_semantic_mismatch_never_becomes_hard_reject() -> None:
    decisions = build_intent_decisions(
        six_confirmed_observations(), confirmed_brief("自然旅行")
    )
    urban = next(item for item in decisions.items if item.material_id == _material_id(1))

    assert urban.bucket == "candidate"
    assert urban.bucket != "reject_suggestion"


def test_only_hard_failure_can_create_reject_suggestion() -> None:
    observations = six_confirmed_observations()
    failed = observations.items[5]
    failed.assertions = [
        _assertion(6, "technical_usability", "unusable"),
        _assertion(6, "content_families", ["attraction_activity"]),
    ]
    decisions = build_intent_decisions(observations, confirmed_brief("城市漫游"))
    rejected = next(item for item in decisions.items if item.material_id == _material_id(6))

    assert rejected.bucket == "reject_suggestion"
    assert any("技术" in reason for reason in rejected.reasons)


def test_candidate_unusable_label_is_not_hard_reject_evidence() -> None:
    observations = six_confirmed_observations()
    weak = observations.items[5]
    weak.assertions[0] = ObservationAssertion(
        field="technical_usability",
        value="unusable",
        status="candidate",
        confidence=0.6,
        evidence_refs=[
            _evidence(6, "technical_usability", status="candidate").model_copy(
                update={"confidence": 0.6}
            )
        ],
    )

    decisions = build_intent_decisions(observations, confirmed_brief("城市漫游"))
    result = next(item for item in decisions.items if item.material_id == _material_id(6))

    assert result.bucket != "reject_suggestion"


def test_unconfirmed_observation_batch_is_blocked() -> None:
    observations = six_confirmed_observations().model_copy(update={"status": "partial"})
    observations.items[0].review_required_fields = ["content_families"]

    with pytest.raises(ValueError, match="confirmed observations"):
        build_intent_decisions(observations, confirmed_brief("城市漫游"))


def test_project_coverage_aggregates_supported_evidence_and_gaps() -> None:
    observations = six_confirmed_observations()
    decisions = build_intent_decisions(observations, confirmed_brief("城市漫游"))
    coverage = build_project_coverage(observations, decisions)

    assert coverage.content_distribution["urban"] == 1
    assert coverage.duplicate_groups == {
        "dup-old-town": [_material_id(1), _material_id(2)]
    }
    assert "opening" in coverage.available_director_functions
    assert "ending" in coverage.missing_director_functions
    assert coverage.evidence_refs


def test_v03_separates_clip_capabilities_from_project_role_assignments() -> None:
    decisions = build_intent_decisions(
        relationship_observations(), confirmed_brief("城市漫游")
    )

    assert decisions.schema_version == "0.3.0"
    by_material = {item.material_id: item for item in decisions.items}
    assert all(not item.director_function_candidates for item in decisions.items)
    assert by_material[_material_id(4)].candidate_capabilities == [
        "movement_progression"
    ]
    assert "climax" not in by_material[_material_id(4)].director_function_candidates
    assert "ending" not in by_material[_material_id(7)].director_function_candidates

    assignments = {
        assignment.director_function: assignment
        for assignment in decisions.role_assignments
    }
    assert assignments["climax"].material_ids == [_material_id(5)]
    assert assignments["ending"].material_ids == [_material_id(6)]
    assert len(assignments["contrast"].material_ids) >= 2
    assert all(
        len(assignment.material_ids) <= 1
        for function, assignment in assignments.items()
        if function in {"opening", "climax", "ending"}
    )
    for assignment in decisions.role_assignments:
        assert assignment.selection_reason
        assert any(ref.source_kind == "user_brief" for ref in assignment.evidence_refs)
        assert all(
            any(ref.material_id == material_id for ref in assignment.evidence_refs)
            for material_id in assignment.material_ids
        )


def test_project_roles_change_with_brief_and_material_collection() -> None:
    observations = relationship_observations()
    city = build_intent_decisions(observations, confirmed_brief("城市漫游"))
    nature = build_intent_decisions(observations, confirmed_brief("自然旅行"))

    city_caps = {
        item.material_id: item.candidate_capabilities for item in city.items
    }
    nature_caps = {
        item.material_id: item.candidate_capabilities for item in nature.items
    }
    assert city_caps == nature_caps
    city_opening = next(
        row for row in city.role_assignments if row.director_function == "opening"
    )
    nature_opening = next(
        row for row in nature.role_assignments if row.director_function == "opening"
    )
    assert city_opening.material_ids == [_material_id(1)]
    assert nature_opening.material_ids == [_material_id(2)]

    without_city = observations.model_copy(
        update={"items": observations.items[1:]}, deep=True
    )
    changed = build_intent_decisions(without_city, confirmed_brief("城市漫游"))
    changed_opening = next(
        row for row in changed.role_assignments if row.director_function == "opening"
    )
    assert changed_opening.material_ids != city_opening.material_ids


def test_lighting_and_people_count_are_not_standalone_role_triggers() -> None:
    observations = relationship_observations()
    weak = observations.items[0]
    weak.assertions = [
        _assertion(1, "technical_usability", "usable"),
        _assertion(1, "lighting", "golden_hour"),
        _assertion(1, "people_count_band", "crowd"),
    ]
    observations.items = [weak]

    decisions = build_intent_decisions(observations, confirmed_brief("城市漫游"))

    assert decisions.items[0].candidate_capabilities == []
    assert decisions.items[0].director_function_candidates == []
    assert decisions.role_assignments == []


def test_v02_intent_decisions_remain_readable() -> None:
    parsed = IntentDecisionBatch.model_validate(
        {
            "schema_version": "0.2.0",
            "status": "completed",
            "items": [
                {
                    "material_id": _material_id(1),
                    "bucket": "candidate",
                    "relevance_score": 0.5,
                    "confidence": 0.8,
                    "director_function_candidates": ["context"],
                    "reasons": ["legacy fixture"],
                    "evidence_refs": [_evidence(1, "content_families").model_dump()],
                    "user_confirmation_required": False,
                }
            ],
        }
    )

    assert parsed.schema_version == "0.2.0"
    assert parsed.role_assignments == []


def test_v03_schema_rejects_clip_level_final_roles_and_single_clip_contrast() -> None:
    decisions = build_intent_decisions(
        relationship_observations(), confirmed_brief("城市漫游")
    )
    payload = decisions.model_dump(mode="json")
    payload["items"][0]["director_function_candidates"] = ["opening"]
    with pytest.raises(ValueError, match="only to project assignments"):
        IntentDecisionBatch.model_validate(payload)

    evidence = [
        _evidence(1, "content_families"),
        EvidenceRef(
            artifact_path="brief_confirmation.json",
            field_path="normalized_fields.travel_type",
            source_kind="user_brief",
            status="confirmed",
            confidence=1.0,
        ),
    ]
    with pytest.raises(ValueError, match="at least two materials"):
        ProjectRoleAssignment(
            director_function="contrast",
            material_ids=[_material_id(1)],
            assignment_score=0.5,
            selection_reason="invalid single-material contrast",
            evidence_refs=evidence,
        )
