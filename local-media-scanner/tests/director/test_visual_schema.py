from __future__ import annotations

import pytest
from pydantic import ValidationError

from director.visual_schema import (
    ClipObservation,
    DirectorReview,
    EditorialOverride,
    EvidenceRef,
    MaterialRef,
    ObservationAssertion,
    derive_material_id,
)


SOURCE_SHA256 = "a" * 64
MATERIAL_ID = f"sha256:{SOURCE_SHA256}"


def material() -> MaterialRef:
    return MaterialRef(
        material_id=MATERIAL_ID,
        relative_path="trip/clip-01.mov",
        source_sha256=SOURCE_SHA256,
        size_bytes=1024,
        mtime_ns=123,
        duration_seconds=8.5,
        fps=25.0,
        orientation="portrait",
    )


def evidence() -> EvidenceRef:
    return EvidenceRef(
        material_id=MATERIAL_ID,
        artifact_path="scanner_result.json",
        field_path="items[0].technical.orientation",
        source_kind="scanner",
        status="measured",
        sha256="b" * 64,
    )


def test_material_id_is_stably_derived_from_source_hash() -> None:
    assert derive_material_id(SOURCE_SHA256) == MATERIAL_ID


def test_observation_contract_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ClipObservation(
            material=material(),
            provider="scanner_only",
            observation_status="automatic",
            silently_claim_location="开封",
        )


def test_supported_assertion_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        ObservationAssertion(
            field="content_families",
            value=["culture_architecture"],
            status="candidate",
            confidence=0.8,
        )

    assertion = ObservationAssertion(
        field="orientation",
        value="portrait",
        status="measured",
        evidence_refs=[evidence()],
    )

    assert assertion.evidence_refs[0].material_id == MATERIAL_ID


def test_candidate_assertion_requires_confidence() -> None:
    with pytest.raises(ValidationError, match="confidence"):
        ObservationAssertion(
            field="people_presence_candidate",
            value=True,
            status="candidate",
            evidence_refs=[evidence()],
        )


def test_editorial_override_is_audited_and_has_no_time_range() -> None:
    override = EditorialOverride(
        material_id=MATERIAL_ID,
        original_bucket="candidate",
        bucket_override="core",
        director_function_overrides=["opening"],
        force_include=True,
        user_note="必须保留同行者出场",
        changed_at="2026-08-31T12:00:00+08:00",
    )
    review = DirectorReview(
        treatment_sha256="c" * 64,
        status="completed",
        mode="assisted",
        overrides=[override],
        confirmed_at="2026-08-31T12:01:00+08:00",
    )

    assert review.overrides[0].bucket_override == "core"
    with pytest.raises(ValidationError):
        EditorialOverride(
            material_id=MATERIAL_ID,
            original_bucket="candidate",
            changed_at="2026-08-31T12:00:00+08:00",
            source_in=1.0,
            source_out=2.0,
        )


def test_editorial_override_cannot_force_include_and_exclude() -> None:
    with pytest.raises(ValidationError, match="force_include"):
        EditorialOverride(
            material_id=MATERIAL_ID,
            original_bucket="candidate",
            force_include=True,
            force_exclude=True,
            changed_at="2026-08-31T12:00:00+08:00",
        )
