"""Conservative bridge from Scanner evidence to Director materials."""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
from typing import TypeVar

from scanner.schema import ScannerCard, ScannerResult, TestManifest

from director.material_enrichment import enrich_materials
from director.visual_understanding.scanner_evidence import (
    build_scanner_only_observations,
)
from director.schema import (
    MaterialLibraryProfile,
    MaterialScanResult,
    MotionEvidence,
    PeopleEvidence,
    QualityEvidence,
)


T = TypeVar("T")
SEMANTIC_CANDIDATE_STATUSES = {"predicted", "candidate"}


def candidate_value(card: ScannerCard, key: str, value: T | None) -> list[T]:
    if value is None or card.field_status.get(key) not in SEMANTIC_CANDIDATE_STATUSES:
        return []
    return [value]


def to_material_scan(card: ScannerCard) -> MaterialScanResult:
    scene_candidates = candidate_value(
        card, "content.scene_type", card.content.scene_type
    )
    object_candidates = (
        list(card.content.main_objects)
        if card.field_status.get("content.main_objects") in SEMANTIC_CANDIDATE_STATUSES
        else []
    )
    people_present = None
    if card.field_status.get("content.people_present") in SEMANTIC_CANDIDATE_STATUSES:
        people_present = card.content.people_present
    people_count = None
    if card.field_status.get("content.people_count_estimate") in SEMANTIC_CANDIDATE_STATUSES:
        people_count = card.content.people_count_estimate

    return MaterialScanResult(
        file=card.file,
        source=card.source,
        technical=card.technical,
        analysis_status=card.analysis_status,
        quality_evidence=QualityEvidence(
            laplacian_variance_raw=card.quality.laplacian_variance_raw,
            brightness_score=card.quality.brightness_score,
            dark_pixel_ratio=card.quality.dark_pixel_ratio,
            bright_pixel_ratio=card.quality.bright_pixel_ratio,
            exposure_candidate=(
                card.quality.exposure_status
                if card.quality.exposure_status != "unknown"
                else None
            ),
        ),
        motion_evidence=MotionEvidence(
            motion_intensity_raw=card.motion.motion_intensity_raw,
            directional_motion_ratio=card.motion.directional_motion_ratio,
            luma_change_p90=card.motion.luma_change_p90,
            motion_level_candidate=(
                card.motion.motion_level
                if card.motion.motion_level != "unknown"
                else None
            ),
        ),
        scene_candidates=scene_candidates,
        confirmed_scene=None,
        object_candidates=object_candidates,
        people_evidence=PeopleEvidence(
            present_candidate=people_present,
            count_lower_bound=people_count,
        ),
        story_priority=None,
        representative_frames=list(card.representative_frames),
        errors=list(card.errors),
    )


def _manifest_sha256(manifest: TestManifest) -> str:
    payload = manifest.model_dump_json(exclude_none=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_library_profile(
    result: ScannerResult,
    manifest: TestManifest,
    run_dir: Path,
) -> MaterialLibraryProfile:
    cards = [
        to_material_scan(card)
        for card in result.items
        if card.analysis_status != "failed"
    ]
    materials = enrich_materials(cards, Path(manifest.input_root), run_dir)
    scenes = Counter(
        scene for material in materials for scene in material.scene_candidates
    )
    motions = Counter(
        material.motion_evidence.motion_level_candidate
        for material in materials
        if material.motion_evidence.motion_level_candidate is not None
    )
    orientations = Counter(material.technical.orientation for material in materials)
    return MaterialLibraryProfile(
        source_scanner_run_id=result.run_id,
        manifest_sha256=_manifest_sha256(manifest),
        materials=materials,
        total_source_duration_seconds=sum(
            material.technical.duration for material in materials
        ),
        usable_material_count=len(materials),
        scene_distribution=dict(sorted(scenes.items())),
        motion_distribution=dict(sorted(motions.items())),
        orientation_distribution=dict(sorted(orientations.items())),
        processing_time_estimate_seconds=None,
    )
