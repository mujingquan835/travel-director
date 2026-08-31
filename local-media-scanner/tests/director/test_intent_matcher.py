from __future__ import annotations

import pytest

from director.intent_matcher import build_intent_decisions, build_project_coverage
from director.visual_schema import (
    BriefConfirmation,
    ClipObservation,
    ClipObservationBatch,
    EvidenceRef,
    MaterialRef,
    ObservationAssertion,
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
