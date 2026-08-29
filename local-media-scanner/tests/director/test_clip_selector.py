from __future__ import annotations

from director.clip_selector import ClipSelectionConfig, place_clips
from director.schema import (
    MaterialScanResult,
    MotionEvidence,
    PeopleEvidence,
    QualityEvidence,
    RecommendedRange,
    TimelineSlot,
)
from scanner.schema import SourceRecord, TechnicalMetadata


def material(
    name: str,
    *,
    impact: float,
    duplicate_group: str,
    motion: str = "medium",
    status: str = "complete",
) -> MaterialScanResult:
    return MaterialScanResult(
        file=name,
        source=SourceRecord(relative_path=name, size_bytes=1_000, mtime_ns=1),
        technical=TechnicalMetadata(
            duration=6,
            width=1080,
            height=1920,
            fps=30,
            orientation="portrait",
            codec="h264",
        ),
        analysis_status=status,
        quality_evidence=QualityEvidence(laplacian_variance_raw=120),
        motion_evidence=MotionEvidence(
            motion_intensity_raw=impact,
            motion_level_candidate=motion,
        ),
        scene_candidates=["city" if name != "detail.mp4" else "food_dining"],
        people_evidence=PeopleEvidence(
            present_candidate=True,
            count_lower_bound=1,
        ),
        duplicate_group_id=duplicate_group,
        visual_impact_score=impact,
        recommended_ranges=[RecommendedRange(start=0.5, end=5.5, reasons=["test"])],
    )


def slots() -> list[TimelineSlot]:
    definitions = [
        ("intro", 0.0, 3.0, "low"),
        ("rise", 3.0, 7.0, "medium"),
        ("climax", 7.0, 9.0, "high"),
        ("outro", 9.0, 12.0, "low"),
    ]
    return [
        TimelineSlot(
            slot_id=f"slot-{index:03d}",
            start=start,
            end=end,
            section_role=role,
            energy=0.8 if role == "climax" else 0.4,
            content_need="high_visual_impact" if role == "climax" else "continuity",
            desired_motion=motion,
        )
        for index, (role, start, end, motion) in enumerate(definitions, start=1)
    ]


def materials() -> list[MaterialScanResult]:
    return [
        material("wide.mp4", impact=0.45, duplicate_group="group-a", motion="low"),
        material("walk.mp4", impact=0.6, duplicate_group="group-b"),
        material("peak.mp4", impact=1.0, duplicate_group="group-c", motion="high"),
        material("detail.mp4", impact=0.5, duplicate_group="group-d", motion="low"),
        material("wide-duplicate.mp4", impact=0.4, duplicate_group="group-a"),
    ]


def test_adjacent_slots_avoid_same_duplicate_group() -> None:
    placements = place_clips(slots(), materials(), ClipSelectionConfig())

    assert all(
        first.duplicate_group_id != second.duplicate_group_id
        for first, second in zip(placements, placements[1:])
    )


def test_highest_impact_clip_is_reserved_for_climax() -> None:
    placements = place_clips(slots(), materials(), ClipSelectionConfig())
    strongest = max(materials(), key=lambda item: item.visual_impact_score or 0).file
    chosen = next(item for item in placements if item.file == strongest)

    assert chosen.section_role == "climax"


def test_in_out_points_stay_inside_recommended_ranges() -> None:
    source_by_file = {item.file: item for item in materials()}

    for placement in place_clips(slots(), materials(), ClipSelectionConfig()):
        source = source_by_file[placement.file]
        assert 0 <= placement.source_in < placement.source_out <= placement.source_duration
        assert any(
            allowed.start <= placement.source_in
            and placement.source_out <= allowed.end
            for allowed in source.recommended_ranges
        )


def test_shortage_reuses_only_after_unique_candidates_are_exhausted() -> None:
    available = materials()[:2]
    placements = place_clips(slots(), available, ClipSelectionConfig())

    assert len(placements) == len(slots())
    assert len({placements[0].file, placements[1].file}) == 2
    assert any("reused_after_unique_exhausted" in row.relaxed_constraints for row in placements)


def test_known_unusable_material_returns_partial_if_slot_cannot_be_filled() -> None:
    unusable = [
        material(
            "failed.mp4",
            impact=1.0,
            duplicate_group="failed",
            status="failed",
        )
    ]

    placements = place_clips(slots()[:1], unusable, ClipSelectionConfig())

    assert placements.status == "partial"
    assert placements == []
    assert placements.errors[0].code == "insufficient_material"


def test_people_candidate_does_not_create_human_story_score() -> None:
    placements = place_clips(slots()[:1], materials(), ClipSelectionConfig())

    assert "human_story" not in placements[0].score_components


def test_long_slot_relaxes_recommendation_only_when_source_is_long_enough() -> None:
    long_slot = TimelineSlot(
        slot_id="slot-long",
        start=0,
        end=5.5,
        section_role="breath",
        energy=0.1,
        content_need="reflective_pause",
        desired_motion="low",
    )

    placements = place_clips(
        [long_slot],
        [material("long.mp4", impact=0.2, duplicate_group="long", motion="low")],
        ClipSelectionConfig(),
    )

    assert placements.status == "completed"
    assert len(placements) == 1
    assert placements[0].source_in == 0
    assert placements[0].source_out == 5.5
    assert "recommended_range_unavailable" in placements[0].relaxed_constraints
