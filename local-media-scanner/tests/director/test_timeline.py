from __future__ import annotations

from director.schema import (
    EnergyPoint,
    MusicEnding,
    MusicStructure,
    MusicStructureSection,
    UserCreativeBrief,
)
from director.timeline import TimelineConfig, build_timeline_slots


def structure() -> MusicStructure:
    beats = [index * 0.5 for index in range(121)]
    return MusicStructure(
        source_sha256="a" * 64,
        duration_seconds=60,
        bpm=120,
        beats_seconds=beats,
        downbeats_seconds=beats[::4],
        energy_curve=[
            EnergyPoint(time_seconds=index, value=0.5) for index in range(60)
        ],
        sections=[
            MusicStructureSection(
                start=0, end=7, role="intro", energy=0.35, confidence=0.8
            ),
            MusicStructureSection(
                start=7, end=24, role="rise", energy=0.65, confidence=0.8
            ),
            MusicStructureSection(
                start=24, end=31, role="breath", energy=0.08, confidence=0.9
            ),
            MusicStructureSection(
                start=31, end=54, role="climax", energy=0.9, confidence=0.8
            ),
            MusicStructureSection(
                start=54, end=60, role="outro", energy=0.45, confidence=0.8
            ),
        ],
        ending=MusicEnding(last_onset_seconds=59.5, behavior="hard_stop"),
        confidence=0.95,
    )


def brief() -> UserCreativeBrief:
    return UserCreativeBrief(
        location="开封",
        travel_type="城市漫游",
        target_duration_seconds=60,
        orientation="portrait",
        style="明亮",
        mood="探索",
        rhythm="medium",
    )


def test_slots_cover_music_without_overlap() -> None:
    slots = build_timeline_slots(structure(), brief(), TimelineConfig())

    assert slots[0].start == 0
    assert slots[-1].end == brief().target_duration_seconds
    assert all(a.end == b.start for a, b in zip(slots, slots[1:]))
    assert all(slot.duration > 0 for slot in slots)


def test_climax_is_faster_than_breath() -> None:
    slots = build_timeline_slots(structure(), brief(), TimelineConfig())
    climax = [slot.duration for slot in slots if slot.section_role == "climax"]
    breath = [slot.duration for slot in slots if slot.section_role == "breath"]

    assert sum(climax) / len(climax) < sum(breath) / len(breath)


def test_internal_boundaries_are_measured_beats() -> None:
    measured = set(structure().beats_seconds) | set(structure().downbeats_seconds)
    slots = build_timeline_slots(structure(), brief(), TimelineConfig())

    assert all(slot.end in measured for slot in slots[:-1])
    assert all(slot.beat_start is not None for slot in slots)
    assert all(slot.beat_end is not None for slot in slots)


def test_slots_express_content_need_without_choosing_files() -> None:
    slots = build_timeline_slots(structure(), brief(), TimelineConfig())

    assert slots[0].content_need == "establishing_environment"
    assert all(
        slot.content_need == "high_visual_impact"
        for slot in slots
        if slot.section_role == "climax"
    )
    assert slots[-1].content_need == "resolved_ending"
    assert not hasattr(slots[0], "file")


def test_unknown_section_records_a_continuity_fallback() -> None:
    measured = structure()
    measured.sections[1].role = "unknown"

    slots = build_timeline_slots(measured, brief(), TimelineConfig())

    assert any(
        slot.section_role == "unknown"
        and slot.content_need == "continuity_fallback"
        for slot in slots
    )


def test_slots_accept_numeric_duration_and_default_config() -> None:
    slots_num = build_timeline_slots(structure(), 60.0)
    assert len(slots_num) > 0
    assert slots_num[0].start == 0.0
    assert slots_num[-1].end == 60.0

    class DummyDirection:
        target_duration_seconds = 60.0

    slots_obj = build_timeline_slots(structure(), DummyDirection())
    assert len(slots_obj) == len(slots_num)
