from __future__ import annotations

from director.schema import (
    ClipPlacement,
    MaterialScanResult,
    MotionEvidence,
    PeopleEvidence,
    QualityEvidence,
    SfxCandidate,
)
from director.sfx import build_sfx_plan, collect_sfx_candidates
from scanner.schema import SourceRecord, TechnicalMetadata


def placement(
    file: str = "river.mp4",
    *,
    role: str = "breath",
    source_in: float = 1.0,
    source_out: float = 4.0,
) -> ClipPlacement:
    return ClipPlacement(
        slot_id="slot-001",
        file=file,
        source_in=source_in,
        source_out=source_out,
        source_duration=6.0,
        section_role=role,
    )


def candidate(
    file: str = "river.mp4",
    *,
    label: str = "water",
    evidence_source: str = "local_audio_candidate",
) -> SfxCandidate:
    return SfxCandidate(
        file=file,
        label=label,
        source_time_seconds=2.0,
        confidence=0.8,
        evidence_source=evidence_source,
    )


def material_with_candidates(candidates: list[SfxCandidate]) -> MaterialScanResult:
    return MaterialScanResult(
        file="river.mp4",
        source=SourceRecord(relative_path="river.mp4", size_bytes=1, mtime_ns=1),
        technical=TechnicalMetadata(
            duration=6,
            width=1080,
            height=1920,
            fps=30,
            orientation="portrait",
            codec="h264",
        ),
        analysis_status="complete",
        quality_evidence=QualityEvidence(),
        motion_evidence=MotionEvidence(),
        people_evidence=PeopleEvidence(),
        sfx_candidates=candidates,
    )


def test_plan_contains_only_placed_materials() -> None:
    plan = build_sfx_plan(
        [placement()],
        [candidate(), candidate("unused.mp4", label="door")],
    )

    assert {item.file for item in plan.items} <= {"river.mp4"}


def test_breath_prefers_valuable_location_sound() -> None:
    plan = build_sfx_plan([placement()], [candidate()])

    assert plan.items[0].decision == "keep_original"
    assert plan.items[0].timeline_time_seconds == 1.0


def test_no_candidate_can_remain_silent() -> None:
    plan = build_sfx_plan([placement()], [])

    assert plan.items[0].decision == "silence"


def test_visual_event_can_suggest_generation_without_calling_a_provider() -> None:
    visual = candidate(label="door", evidence_source="scanner_object_candidate")

    plan = build_sfx_plan([placement(role="rise")], [visual])

    assert plan.items[0].decision == "generate_sfx"
    assert "provider" not in plan.items[0].reason.lower()


def test_collect_normalizes_allowed_labels_and_deduplicates() -> None:
    repeated = candidate()
    unknown = candidate(label="speech")
    material = material_with_candidates([repeated, repeated, unknown])

    collected = collect_sfx_candidates([material])

    assert [(row.file, row.label) for row in collected] == [("river.mp4", "water")]


def test_adjacent_visual_events_do_not_generate_sfx_on_every_transition() -> None:
    placements = [
        placement("door-a.mp4", role="rise", source_in=0, source_out=3),
        placement("door-b.mp4", role="rise", source_in=0, source_out=3),
    ]
    candidates = [
        candidate(
            "door-a.mp4",
            label="door",
            evidence_source="scanner_object_candidate",
        ),
        candidate(
            "door-b.mp4",
            label="door",
            evidence_source="scanner_object_candidate",
        ),
    ]

    plan = build_sfx_plan(placements, candidates)

    assert [item.decision for item in plan.items] == ["generate_sfx", "silence"]
