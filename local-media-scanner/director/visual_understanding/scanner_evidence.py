"""Conservative V0.2 observations built only from saved Scanner JSON."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scanner.schema import ScannerCard, ScannerResult

from director.visual_schema import (
    ClipObservation,
    ClipObservationBatch,
    EvidenceRef,
    MaterialRef,
    ObservationAssertion,
    ProviderIssue,
    derive_material_id,
)


REVIEW_REQUIRED_FIELDS = [
    "technical_usability",
    "content_families",
    "setting",
    "lighting",
    "people_presence",
    "people_count_band",
    "subject_candidates",
    "activity_candidates",
]
SEMANTIC_CANDIDATE_STATUSES = {"predicted", "candidate"}


def _evidence(
    card: ScannerCard,
    *,
    material_id: str,
    artifact_path: str,
    artifact_sha256: str,
    field_path: str,
    status: str,
    confidence: float | None = None,
) -> EvidenceRef:
    return EvidenceRef(
        material_id=material_id,
        artifact_path=artifact_path,
        field_path=field_path,
        source_kind="scanner",
        status=status,
        confidence=confidence,
        sha256=artifact_sha256,
    )


def _measured_assertion(
    card: ScannerCard,
    *,
    material_id: str,
    artifact_path: str,
    artifact_sha256: str,
    field: str,
    field_path: str,
    value: Any,
) -> ObservationAssertion | None:
    if value is None:
        return None
    return ObservationAssertion(
        field=field,
        value=value,
        status="measured",
        evidence_refs=[
            _evidence(
                card,
                material_id=material_id,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                field_path=field_path,
                status="measured",
            )
        ],
    )


def _candidate_assertion(
    card: ScannerCard,
    *,
    material_id: str,
    artifact_path: str,
    artifact_sha256: str,
    field: str,
    scanner_field: str,
    field_path: str,
    value: Any,
) -> ObservationAssertion:
    if value is None or card.field_status.get(scanner_field) not in SEMANTIC_CANDIDATE_STATUSES:
        return ObservationAssertion(field=field, status="abstained")
    confidence = (
        card.confidence[scanner_field].score
        if scanner_field in card.confidence
        else 0.0
    )
    return ObservationAssertion(
        field=field,
        value=value,
        status="candidate",
        confidence=confidence,
        evidence_refs=[
            _evidence(
                card,
                material_id=material_id,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                field_path=field_path,
                status="candidate",
                confidence=confidence,
            )
        ],
    )


def _card_observation(
    card: ScannerCard,
    *,
    index: int,
    source_sha256: str,
    artifact_path: str,
    artifact_sha256: str,
) -> ClipObservation:
    material_id = derive_material_id(source_sha256)
    prefix = f"items[{index}]"
    material = MaterialRef(
        material_id=material_id,
        relative_path=card.source.relative_path,
        source_sha256=source_sha256,
        size_bytes=card.source.size_bytes,
        mtime_ns=card.source.mtime_ns,
        duration_seconds=card.technical.duration,
        fps=card.technical.fps,
        orientation=card.technical.orientation,
        rotation=card.technical.rotation,
    )
    measured_specs = [
        ("duration_seconds", f"{prefix}.technical.duration", card.technical.duration),
        ("fps", f"{prefix}.technical.fps", card.technical.fps),
        ("orientation", f"{prefix}.technical.orientation", card.technical.orientation),
        ("rotation", f"{prefix}.technical.rotation", card.technical.rotation),
        ("laplacian_variance_raw", f"{prefix}.quality.laplacian_variance_raw", card.quality.laplacian_variance_raw),
        ("brightness_score", f"{prefix}.quality.brightness_score", card.quality.brightness_score),
        ("dark_pixel_ratio", f"{prefix}.quality.dark_pixel_ratio", card.quality.dark_pixel_ratio),
        ("bright_pixel_ratio", f"{prefix}.quality.bright_pixel_ratio", card.quality.bright_pixel_ratio),
        ("motion_intensity_raw", f"{prefix}.motion.motion_intensity_raw", card.motion.motion_intensity_raw),
        ("directional_motion_ratio", f"{prefix}.motion.directional_motion_ratio", card.motion.directional_motion_ratio),
        ("luma_change_p90", f"{prefix}.motion.luma_change_p90", card.motion.luma_change_p90),
    ]
    assertions = [
        assertion
        for field, field_path, value in measured_specs
        if (
            assertion := _measured_assertion(
                card,
                material_id=material_id,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                field=field,
                field_path=field_path,
                value=value,
            )
        )
        is not None
    ]
    if card.quality.exposure_status != "unknown":
        assertions.append(
            _measured_assertion(
                card,
                material_id=material_id,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                field="exposure_status",
                field_path=f"{prefix}.quality.exposure_status",
                value=card.quality.exposure_status,
            )
        )
    assertions.extend(
        [
            _candidate_assertion(
                card,
                material_id=material_id,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                field="people_presence_candidate",
                scanner_field="content.people_present",
                field_path=f"{prefix}.content.people_present",
                value=card.content.people_present,
            ),
            _candidate_assertion(
                card,
                material_id=material_id,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                field="people_count_lower_bound",
                scanner_field="content.people_count_estimate",
                field_path=f"{prefix}.content.people_count_estimate",
                value=card.content.people_count_estimate,
            ),
            _candidate_assertion(
                card,
                material_id=material_id,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                field="setting_candidates",
                scanner_field="content.scene_type",
                field_path=f"{prefix}.content.scene_type",
                value=[card.content.scene_type] if card.content.scene_type else None,
            ),
            _candidate_assertion(
                card,
                material_id=material_id,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                field="subject_candidates",
                scanner_field="content.main_objects",
                field_path=f"{prefix}.content.main_objects",
                value=list(card.content.main_objects) or None,
            ),
            _candidate_assertion(
                card,
                material_id=material_id,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                field="activity_candidates",
                scanner_field="content.simple_action",
                field_path=f"{prefix}.content.simple_action",
                value=[card.content.simple_action] if card.content.simple_action else None,
            ),
            _candidate_assertion(
                card,
                material_id=material_id,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                field="shot_scale_candidate",
                scanner_field="shot_scale",
                field_path=f"{prefix}.shot_scale",
                value=card.shot_scale,
            ),
        ]
    )
    issues = [
        ProviderIssue(code=error.code, message=error.message, field=error.stage)
        for error in card.errors
    ]
    return ClipObservation(
        material=material,
        provider="scanner_only",
        observation_status=(
            "unavailable" if card.analysis_status == "failed" else "abstained"
        ),
        assertions=assertions,
        unknown_fields=list(REVIEW_REQUIRED_FIELDS),
        review_required_fields=list(REVIEW_REQUIRED_FIELDS),
        errors=issues,
    )


def build_scanner_only_observations(
    result: ScannerResult,
    *,
    source_hashes: Mapping[str, str],
    artifact_path: str,
    artifact_sha256: str,
) -> ClipObservationBatch:
    """Map saved Scanner evidence without decoding media or inventing semantics."""

    items: list[ClipObservation] = []
    for index, card in enumerate(result.items):
        try:
            source_sha256 = source_hashes[card.source.relative_path]
        except KeyError as exc:
            raise ValueError(
                f"missing source SHA-256 for {card.source.relative_path}"
            ) from exc
        items.append(
            _card_observation(
                card,
                index=index,
                source_sha256=source_sha256,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
            )
        )
    return ClipObservationBatch(status="partial", mode="scanner_only", items=items)
