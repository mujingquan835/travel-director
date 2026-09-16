from __future__ import annotations

import math
from typing import Literal

from pydantic import Field

from director.schema import MusicStructure, StrictModel


class OutroConfig(StrictModel):
    outro_volume: float = Field(default=0.7, ge=0.0, le=1.0)
    outro_pre_end_seconds: float = Field(default=1.0, ge=0.0)
    enable_auto_outro: bool = True


class OutroPlan(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    sfx_path: str | None
    trigger_time_seconds: float
    reason: str
    config: OutroConfig


def _get_sfx_path(e: any) -> str:
    for attr in ("relative_path", "file", "path", "name"):
        val = getattr(e, attr, None)
        if val is not None:
            return str(val)
    return str(e)


def select_outro_sfx(ending_behavior: str, sfx_entries: list) -> str | None:
    """Select the outro SFX based on the ending behavior."""
    # Preserve eligibility rules; choose the lexicographically smallest path.
    sfx_entries = sorted(sfx_entries, key=_get_sfx_path)
    if ending_behavior == "hard_stop":
        for e in sfx_entries:
            role = getattr(e, "role", "")
            name = getattr(e, "name", "")
            if role == "outro_hit" and ("Deep Hit" in name or "Cliff" in name):
                return _get_sfx_path(e)
    elif ending_behavior == "decay":
        for e in sfx_entries:
            if getattr(e, "role", "") == "outro_piano":
                return _get_sfx_path(e)
    elif ending_behavior == "fade":
        for e in sfx_entries:
            role = getattr(e, "role", "")
            name = getattr(e, "name", "")
            if role == "outro_hit" and "Event Horizon" in name:
                return _get_sfx_path(e)

    return None


def build_outro_plan(
    music_structure: MusicStructure, sfx_entries: list, config: OutroConfig | None = None,
    *, target_duration_seconds: float | None = None,
) -> OutroPlan:
    """Build a plan for the outro effect."""
    if config is None:
        config = OutroConfig()

    duration = music_structure.duration_seconds if target_duration_seconds is None else target_duration_seconds
    if not math.isfinite(duration) or duration <= 0 or duration > music_structure.duration_seconds + 1e-6:
        raise ValueError("outro target duration must be positive and within the measured music")
    if config.outro_pre_end_seconds > duration:
        raise ValueError("outro pre-end must not exceed target duration")
    truncated = duration < music_structure.duration_seconds - 1e-6
    sfx_path = None
    reason = "Auto outro disabled"

    if config.enable_auto_outro and truncated:
        reason = "剪辑点早于原曲结尾，剪辑点收尾特征尚未分析；暂不自动叠加收尾音效"
    elif config.enable_auto_outro:
        behavior = music_structure.ending.behavior
        sfx_path = select_outro_sfx(behavior, sfx_entries)
        if sfx_path:
            reason = f"Selected for behavior: {behavior}"
        else:
            reason = f"No SFX found for behavior: {behavior}"

    trigger_time = max(0.0, duration - config.outro_pre_end_seconds)

    return OutroPlan(
        sfx_path=sfx_path,
        trigger_time_seconds=trigger_time,
        reason=reason,
        config=config,
    )


def _number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def build_outro_filters(plan: OutroPlan, total_duration: float) -> list[str]:
    """Generate FFmpeg filters for the outro effect."""
    if not plan.sfx_path:
        return []

    delay_ms = round(plan.trigger_time_seconds * 1000)

    f_sfx = (
        f"[1:a]atrim=start=0:end=5.0,asetpts=PTS-STARTPTS,"
        f"adelay={delay_ms}|{delay_ms},volume={_number(plan.config.outro_volume)}[outro_sfx]"
    )
    f_mix = "[0:a][outro_sfx]amix=inputs=2:duration=first:dropout_transition=0[outro_mix_out]"

    return [f_sfx, f_mix]
