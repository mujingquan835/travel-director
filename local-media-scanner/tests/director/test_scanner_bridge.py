from __future__ import annotations

from pathlib import Path

from scanner.schema import (
    ContentAnalysis,
    FrameRecord,
    MotionMetrics,
    QualityMetrics,
    ScannerCard,
    ScannerResult,
    SourceRecord,
    TechnicalMetadata,
    TestManifest as ScannerManifest,
    TimingBreakdown,
)

from director.scanner_bridge import build_library_profile, to_material_scan


def scanner_card() -> ScannerCard:
    return ScannerCard(
        file="clip.mov",
        source=SourceRecord(relative_path="clip.mov", size_bytes=100, mtime_ns=1),
        analysis_status="complete",
        technical=TechnicalMetadata(
            duration=12.0,
            width=1920,
            height=1080,
            fps=30.0,
            orientation="landscape",
            codec="hevc",
        ),
        quality=QualityMetrics(
            laplacian_variance_raw=420.0,
            brightness_score=0.55,
            dark_pixel_ratio=0.1,
            bright_pixel_ratio=0.02,
            exposure_status="normal",
        ),
        motion=MotionMetrics(
            motion_intensity_raw=2.5,
            motion_intensity=0.7,
            motion_level="high",
            static_or_dynamic="dynamic",
            directional_motion_ratio=0.8,
            luma_change_p90=0.3,
        ),
        content=ContentAnalysis(
            people_present=True,
            people_count_estimate=30,
            scene_type="theme_park",
            main_objects=["person", "ride"],
        ),
        representative_frames=[
            FrameRecord(timestamp=4.0, reasons=["temporal"], thumbnail_relpath="frames/clip/00.jpg")
        ],
        confidence={},
        field_status={
            "content.people_present": "candidate",
            "content.people_count_estimate": "candidate",
            "content.scene_type": "candidate",
            "content.main_objects": "candidate",
            "motion.motion_level": "candidate",
        },
        timings_ms=TimingBreakdown(total=100.0),
        errors=[],
    )


def test_candidate_semantics_remain_candidates() -> None:
    material = to_material_scan(scanner_card())

    assert material.scene_candidates == ["theme_park"]
    assert material.confirmed_scene is None
    assert material.object_candidates == ["person", "ride"]


def test_people_count_is_lower_bound_without_story_priority() -> None:
    material = to_material_scan(scanner_card())

    assert material.people_evidence.count_lower_bound == 30
    assert material.story_priority is None


def test_abstained_semantic_value_is_not_copied() -> None:
    card = scanner_card()
    card.field_status["content.scene_type"] = "abstained"

    material = to_material_scan(card)

    assert material.scene_candidates == []


def test_profile_uses_measured_duration_without_inventing_sla(tmp_path: Path) -> None:
    card = scanner_card()
    result = ScannerResult(
        run_id="scanner-run",
        requested_device="mps",
        actual_device="mps",
        items=[card],
    )
    manifest = ScannerManifest(
        input_root=str(tmp_path),
        entries=[],
        total_duration_seconds=12.0,
        total_size_bytes=100,
    )

    profile = build_library_profile(result, manifest, tmp_path / "run")

    assert profile.total_source_duration_seconds == 12.0
    assert profile.usable_material_count == 1
    assert profile.processing_time_estimate_seconds is None
    assert profile.source_scanner_run_id == "scanner-run"
