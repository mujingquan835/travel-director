"""Fast and Slow Mode delivery orchestration for Travel Director."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from director.audio_catalog import SfxEntry
from director.creative_schema import CreativeSection
from director.export.markdown import render_fast_mode_markdown
from director.hook_builder import HookConfig, HookPlan, build_hook_plan
from director.outro_builder import OutroConfig, OutroPlan, build_outro_plan
from director.schema import MusicStructure, StrictModel
from director.timeline import TimelineConfig, build_timeline_slots


class FastModeSlot(StrictModel):
    slot_id: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    duration: float = Field(gt=0.0)
    section_role: str
    energy: float = Field(ge=0.0, le=1.0)
    content_need: str
    desired_motion: str
    narrative_task: str | None = None
    visual_plan: str | None = None
    placeholder_text: str
    beat_start: int | None = None
    beat_end: int | None = None


class FastModeTimeline(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    mode: Literal["fast"] = "fast"
    target_duration_seconds: float = Field(gt=0.0)
    music_title: str | None = None
    music_asset_path: str
    bpm: float | None = None
    hook_plan: HookPlan | None = None
    outro_plan: OutroPlan | None = None
    slots: list[FastModeSlot] = Field(min_length=1)


def build_fast_mode_timeline(
    music_structure: MusicStructure,
    target_duration_seconds: float,
    music_asset_path: str,
    *,
    music_title: str | None = None,
    creative_sections: list[CreativeSection] | None = None,
    sfx_entries: list[SfxEntry] | None = None,
    hook_config: HookConfig | None = None,
    outro_config: OutroConfig | None = None,
    timeline_config: TimelineConfig | None = None,
) -> FastModeTimeline:
    """Build a beat-aligned Fast Mode timeline with text placeholders and audio packaging."""
    raw_slots = build_timeline_slots(
        music_structure, target_duration_seconds, timeline_config
    )

    hook_plan: HookPlan | None = None
    if sfx_entries:
        try:
            hook_plan = build_hook_plan(sfx_entries, hook_config)
        except Exception:
            hook_plan = None

    outro_plan: OutroPlan | None = None
    if sfx_entries:
        try:
            outro_plan = build_outro_plan(music_structure, sfx_entries, outro_config)
        except Exception:
            outro_plan = None

    fast_slots: list[FastModeSlot] = []
    for slot in raw_slots:
        midpoint = (slot.start + slot.end) / 2.0
        matched_section: CreativeSection | None = None
        if creative_sections:
            for sec in creative_sections:
                if sec.start <= midpoint < sec.end:
                    matched_section = sec
                    break
            if matched_section is None and creative_sections:
                matched_section = creative_sections[-1]

        narrative_task = matched_section.narrative_task if matched_section else None
        visual_plan = matched_section.visual_plan if matched_section else None
        desc_task = narrative_task or slot.content_need
        placeholder = (
            f"[{slot.slot_id} | {slot.start:.2f}s-{slot.end:.2f}s | {slot.section_role} | 能量: {slot.energy:.2f}] "
            f"{desc_task} (运镜: {slot.desired_motion}) [待填素材]"
        )

        fast_slots.append(
            FastModeSlot(
                slot_id=slot.slot_id,
                start=slot.start,
                end=slot.end,
                duration=round(slot.duration, 6),
                section_role=slot.section_role,
                energy=slot.energy,
                content_need=slot.content_need,
                desired_motion=slot.desired_motion,
                narrative_task=narrative_task,
                visual_plan=visual_plan,
                placeholder_text=placeholder,
                beat_start=slot.beat_start,
                beat_end=slot.beat_end,
            )
        )

    return FastModeTimeline(
        schema_version="1.0.0",
        mode="fast",
        target_duration_seconds=target_duration_seconds,
        music_title=music_title,
        music_asset_path=music_asset_path,
        bpm=music_structure.bpm,
        hook_plan=hook_plan,
        outro_plan=outro_plan,
        slots=fast_slots,
    )


def save_fast_mode_delivery(
    timeline: FastModeTimeline, output_dir: Path
) -> tuple[Path, Path]:
    """Atomically save the JSON and Markdown representations of the Fast Mode timeline."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "fast_mode_timeline.json"
    md_path = output_dir / "timeline_delivery.md"

    json_path.write_text(timeline.model_dump_json(indent=2), encoding="utf-8")
    md_content = render_fast_mode_markdown(timeline)
    md_path.write_text(md_content, encoding="utf-8")

    return json_path, md_path
