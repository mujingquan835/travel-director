"""Build beat-aligned editorial slots from measured music structure."""

from __future__ import annotations

from bisect import bisect_left
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from director.schema import MusicStructure, TimelineSlot, UserCreativeBrief


TimelineRole = Literal["intro", "rise", "breath", "climax", "outro", "unknown"]


class TimelineRoleOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    role: TimelineRole

    @model_validator(mode="after")
    def end_after_start(self) -> "TimelineRoleOverride":
        if self.end <= self.start:
            raise ValueError("override end must be greater than start")
        return self


class TimelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_slot_seconds: float = Field(default=0.8, gt=0.0)
    max_slot_seconds: float = Field(default=6.0, gt=0.0)
    intro_mean_seconds: float = Field(default=3.5, gt=0.0)
    rise_mean_seconds: float = Field(default=2.2, gt=0.0)
    breath_mean_seconds: float = Field(default=4.5, gt=0.0)
    climax_mean_seconds: float = Field(default=1.4, gt=0.0)
    outro_mean_seconds: float = Field(default=3.5, gt=0.0)
    unknown_mean_seconds: float = Field(default=2.5, gt=0.0)

    @model_validator(mode="after")
    def slot_bounds_are_ordered(self) -> "TimelineConfig":
        if self.min_slot_seconds > self.max_slot_seconds:
            raise ValueError("min_slot_seconds must not exceed max_slot_seconds")
        return self

    def mean_for(self, role: str) -> float:
        value = {
            "intro": self.intro_mean_seconds,
            "rise": self.rise_mean_seconds,
            "breath": self.breath_mean_seconds,
            "climax": self.climax_mean_seconds,
            "outro": self.outro_mean_seconds,
        }.get(role, self.unknown_mean_seconds)
        return min(self.max_slot_seconds, max(self.min_slot_seconds, value))


def _nearest(values: list[float], target: float) -> float:
    return min(values, key=lambda value: (abs(value - target), value))


def _nearest_beat_index(beats: list[float], time_seconds: float) -> int | None:
    if not beats:
        return None
    index = bisect_left(beats, time_seconds)
    candidates = [min(index, len(beats) - 1), max(0, index - 1)]
    return min(candidates, key=lambda item: abs(beats[item] - time_seconds))


def _snap_section_boundaries(
    structure: MusicStructure,
    target_duration: float,
    role_overrides: list[TimelineRoleOverride] | None = None,
) -> list[float]:
    measured = sorted(
        {
            value
            for value in [*structure.beats_seconds, *structure.downbeats_seconds]
            if 0 < value < target_duration
        }
    )
    boundaries = [0.0]
    for section in structure.sections[:-1]:
        if section.end >= target_duration or not measured:
            break
        later = [value for value in measured if value > boundaries[-1]]
        if not later:
            break
        snapped = _nearest(later, section.end)
        if snapped < target_duration:
            boundaries.append(snapped)
    for override in role_overrides or []:
        for value in (override.start, override.end):
            if 0 < value < target_duration and measured:
                boundaries.append(_nearest(measured, value))
    boundaries.append(target_duration)
    return sorted(set(boundaries))


def _section_for_time(structure: MusicStructure, midpoint: float):
    for section in structure.sections:
        if section.start <= midpoint < section.end:
            return section
    return structure.sections[-1] if structure.sections else None


def _override_for_time(
    role_overrides: list[TimelineRoleOverride], midpoint: float
) -> TimelineRoleOverride | None:
    matches = [
        override
        for override in role_overrides
        if override.start <= midpoint < override.end
    ]
    return matches[-1] if matches else None


def _interval_energy(
    structure: MusicStructure,
    start: float,
    end: float,
    fallback: float,
) -> float:
    values = [
        point.value
        for point in structure.energy_curve
        if start <= point.time_seconds < end
    ]
    if not values and structure.energy_curve:
        midpoint = (start + end) / 2.0
        nearest = min(
            structure.energy_curve,
            key=lambda point: abs(point.time_seconds - midpoint),
        )
        values = [nearest.value]
    if not values:
        return fallback
    return float(min(1.0, max(0.0, sum(values) / len(values))))


def _subdivide_on_beats(
    start: float,
    end: float,
    mean_seconds: float,
    measured: list[float],
    config: TimelineConfig,
) -> list[float]:
    duration = end - start
    minimum_count = max(1, math.ceil(duration / config.max_slot_seconds))
    maximum_count = max(1, math.floor(duration / config.min_slot_seconds))
    slot_count = min(
        maximum_count,
        max(minimum_count, round(duration / mean_seconds)),
    )
    boundaries = [start]
    available = [value for value in measured if start < value < end]

    for index in range(1, slot_count):
        desired = start + duration * index / slot_count
        choices = [value for value in available if value > boundaries[-1]]
        if not choices:
            break
        snapped = _nearest(choices, desired)
        if snapped < end:
            boundaries.append(snapped)
    boundaries.append(end)
    return boundaries


def _content_need(role: str, *, first: bool) -> str:
    if first:
        return "establishing_environment"
    return {
        "intro": "orientation_detail",
        "rise": "progressive_discovery",
        "breath": "reflective_pause",
        "climax": "high_visual_impact",
        "outro": "resolved_ending",
        "unknown": "continuity_fallback",
    }.get(role, "continuity_fallback")


def _desired_motion(role: str) -> str:
    return {
        "intro": "low",
        "rise": "medium",
        "breath": "low",
        "climax": "high",
        "outro": "low",
        "unknown": "medium",
    }.get(role, "medium")


def build_timeline_slots(
    structure: MusicStructure,
    brief: UserCreativeBrief | Any,
    config: TimelineConfig | None = None,
    *,
    role_overrides: list[TimelineRoleOverride] | None = None,
) -> list[TimelineSlot]:
    """Create contiguous editorial budgets without choosing any source file."""

    if config is None:
        config = TimelineConfig()
    if isinstance(brief, (int, float)):
        target_duration = float(brief)
    elif hasattr(brief, "target_duration_seconds"):
        target_duration = float(brief.target_duration_seconds)
    else:
        raise ValueError("brief must provide target_duration_seconds or be a numeric duration")
    if structure.duration_seconds + 1e-6 < target_duration:
        raise ValueError("measured music is shorter than the requested timeline")
    if not structure.sections:
        raise ValueError("measured music structure has no sections")

    measured = sorted(set(structure.beats_seconds) | set(structure.downbeats_seconds))
    overrides = role_overrides or []
    section_boundaries = _snap_section_boundaries(
        structure, target_duration, overrides
    )
    raw_slots: list[tuple[float, float, str, float]] = []

    for section_start, section_end in zip(
        section_boundaries, section_boundaries[1:]
    ):
        section = _section_for_time(structure, (section_start + section_end) / 2.0)
        role_override = _override_for_time(
            overrides, (section_start + section_end) / 2.0
        )
        role = role_override.role if role_override else (
            section.role if section else "unknown"
        )
        fallback_energy = section.energy if section else 0.5
        boundaries = _subdivide_on_beats(
            section_start,
            section_end,
            config.mean_for(role),
            measured,
            config,
        )
        raw_slots.extend(
            (start, end, role, fallback_energy)
            for start, end in zip(boundaries, boundaries[1:])
            if end > start
        )

    slots: list[TimelineSlot] = []
    for index, (start, end, role, fallback_energy) in enumerate(raw_slots):
        energy = _interval_energy(
            structure, start, end, fallback_energy
        )
        slots.append(
            TimelineSlot(
                slot_id=f"slot-{index + 1:03d}",
                start=round(start, 6),
                end=round(end, 6),
                section_role=role,
                energy=energy,
                content_need=_content_need(role, first=index == 0),
                desired_motion=_desired_motion(role),
                beat_start=_nearest_beat_index(structure.beats_seconds, start),
                beat_end=_nearest_beat_index(structure.beats_seconds, end),
            )
        )
    return slots
