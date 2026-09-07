from __future__ import annotations

from pathlib import Path
import pytest

from director.audio_catalog import SfxEntry
from director.creative_schema import CreativeSection
from director.delivery import (
    FastModeTimeline,
    build_fast_mode_timeline,
    save_fast_mode_delivery,
)
from director.export.markdown import render_fast_mode_markdown
from director.schema import (
    EnergyPoint,
    MusicEnding,
    MusicStructure,
    MusicStructureSection,
)


def sample_structure() -> MusicStructure:
    beats = [index * 0.5 for index in range(121)]
    return MusicStructure(
        source_sha256="b" * 64,
        duration_seconds=60.0,
        bpm=120.0,
        beats_seconds=beats,
        downbeats_seconds=beats[::4],
        energy_curve=[
            EnergyPoint(time_seconds=index, value=0.5) for index in range(60)
        ],
        sections=[
            MusicStructureSection(start=0, end=10, role="intro", energy=0.3, confidence=0.8),
            MusicStructureSection(start=10, end=30, role="rise", energy=0.6, confidence=0.8),
            MusicStructureSection(start=30, end=40, role="breath", energy=0.1, confidence=0.9),
            MusicStructureSection(start=40, end=55, role="climax", energy=0.9, confidence=0.8),
            MusicStructureSection(start=55, end=60, role="outro", energy=0.4, confidence=0.8),
        ],
        ending=MusicEnding(last_onset_seconds=59.5, behavior="hard_stop"),
        confidence=0.9,
    )


def sample_sfx_entries() -> list[SfxEntry]:
    return [
        SfxEntry(
            sfx_id="sfx-01",
            name="CZG_Riser_001.wav",
            category="风声",
            role="riser",
            relative_path="风声/CZG_Riser_001.wav",
            duration_seconds=1.8,
        ),
        SfxEntry(
            sfx_id="sfx-02",
            name="CZG_Hit_001.wav",
            category="上升音效",
            role="hook_hit",
            relative_path="上升音效/CZG_Hit_001.wav",
            duration_seconds=1.1,
        ),
        SfxEntry(
            sfx_id="sfx-03",
            name="13 Deep Hit.wav",
            category="收尾",
            role="outro_hit",
            relative_path="收尾/13 Deep Hit.wav",
            duration_seconds=2.5,
        ),
    ]


def test_build_fast_mode_timeline_basic() -> None:
    st = sample_structure()
    tl = build_fast_mode_timeline(
        music_structure=st,
        target_duration_seconds=60.0,
        music_asset_path="/path/to/music.wav",
        music_title="Demo Track",
    )
    assert tl.mode == "fast"
    assert tl.target_duration_seconds == 60.0
    assert tl.music_title == "Demo Track"
    assert len(tl.slots) > 0
    assert tl.slots[0].start == 0.0
    assert tl.slots[-1].end == 60.0
    assert all(s.duration > 0 for s in tl.slots)
    assert tl.hook_plan is None
    assert tl.outro_plan is None
    assert "待填素材" in tl.slots[0].placeholder_text


def test_build_fast_mode_timeline_with_creative_sections() -> None:
    st = sample_structure()
    sections = [
        CreativeSection(
            section_id="sec-01",
            start=0.0,
            end=30.0,
            narrative_task="开篇交代地理与晨光",
            material_ids=[],
            material_gaps=["gap1"],
            visual_plan="大景别慢摇",
            music_change="轻柔起势",
            sfx_plan=[],
            packaging=[],
            reference_ids=[],
        ),
        CreativeSection(
            section_id="sec-02",
            start=30.0,
            end=60.0,
            narrative_task="高潮展现古城全貌与市集",
            material_ids=[],
            material_gaps=["gap2"],
            visual_plan="快切特写",
            music_change="强重音律动",
            sfx_plan=[],
            packaging=[],
            reference_ids=[],
            climax=True,
        ),
    ]
    tl = build_fast_mode_timeline(
        music_structure=st,
        target_duration_seconds=60.0,
        music_asset_path="/path/to/music.wav",
        creative_sections=sections,
    )
    first_slot = tl.slots[0]
    assert first_slot.narrative_task == "开篇交代地理与晨光"
    assert first_slot.visual_plan == "大景别慢摇"
    assert "开篇交代地理与晨光" in first_slot.placeholder_text

    last_slot = tl.slots[-1]
    assert last_slot.narrative_task == "高潮展现古城全貌与市集"


def test_build_fast_mode_timeline_with_sfx() -> None:
    st = sample_structure()
    sfx = sample_sfx_entries()
    tl = build_fast_mode_timeline(
        music_structure=st,
        target_duration_seconds=60.0,
        music_asset_path="/path/to/music.wav",
        sfx_entries=sfx,
    )
    assert tl.hook_plan is not None
    assert "CZG_Riser" in tl.hook_plan.riser_path
    assert "CZG_Hit" in tl.hook_plan.hit_path
    assert tl.outro_plan is not None
    assert tl.outro_plan.sfx_path is not None
    assert "Deep Hit" in tl.outro_plan.sfx_path


def test_render_fast_mode_markdown() -> None:
    st = sample_structure()
    sfx = sample_sfx_entries()
    tl = build_fast_mode_timeline(
        music_structure=st,
        target_duration_seconds=60.0,
        music_asset_path="/path/to/music.wav",
        music_title="Test Track",
        sfx_entries=sfx,
    )
    md = render_fast_mode_markdown(tl)
    assert "# 🎬 旅行导演 — 快速模式时间线交付" in md
    assert "Test Track" in md
    assert "黄金开场 Hook" in md
    assert "CZG_Riser" in md
    assert "结尾收尾音效" in md
    assert "| 槽位 ID |" in md
    assert "slot-001" in md


def test_save_fast_mode_delivery(tmp_path: Path) -> None:
    st = sample_structure()
    tl = build_fast_mode_timeline(
        music_structure=st,
        target_duration_seconds=60.0,
        music_asset_path="/path/to/music.wav",
    )
    json_path, md_path = save_fast_mode_delivery(tl, tmp_path)
    assert json_path.is_file()
    assert md_path.is_file()
    assert "slot-001" in json_path.read_text(encoding="utf-8")
    assert "# 🎬 旅行导演" in md_path.read_text(encoding="utf-8")


def test_truncated_music_uses_timeline_end_and_preserves_uncertainty():
    timeline = build_fast_mode_timeline(
        sample_structure(), 30.0, "/music.wav", sfx_entries=sample_sfx_entries(),
    )
    assert timeline.slots[-1].end == 30.0
    assert timeline.outro_plan.trigger_time_seconds == 29.0
    assert timeline.outro_plan.sfx_path is None
    assert "尚未分析" in timeline.outro_plan.reason
    markdown = render_fast_mode_markdown(timeline)
    assert "尚未分析" in markdown
    assert "原曲自然淡出" not in markdown


def test_full_music_keeps_measured_outro():
    timeline = build_fast_mode_timeline(
        sample_structure(), 60.0, "/music.wav", sfx_entries=sample_sfx_entries(),
    )
    assert timeline.outro_plan.trigger_time_seconds == 59.0
    assert timeline.outro_plan.sfx_path == "收尾/13 Deep Hit.wav"
