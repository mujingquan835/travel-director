from __future__ import annotations

import random
from typing import Literal

from pydantic import Field, model_validator

from director.schema import StrictModel


class HookConfig(StrictModel):
    hook_duration_seconds: float = Field(default=2.0, gt=0, le=5.0)
    hit_pre_trigger_seconds: float = Field(default=0.2, ge=0.0)
    riser_volume: float = Field(default=0.8, ge=0, le=1.0)
    hit_volume: float = Field(default=0.9, ge=0.0, le=1.0)
    bgm_duck_level: float = Field(default=0.3, ge=0, le=1.0)
    bgm_recovery_seconds: float = Field(default=0.3, gt=0.0)

    @model_validator(mode="after")
    def release_is_inside_hook(self) -> "HookConfig":
        if self.hit_pre_trigger_seconds > self.hook_duration_seconds:
            raise ValueError("hit pre-trigger must not exceed hook duration")
        return self


class HookPlan(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    riser_path: str
    hit_path: str
    hook_duration_seconds: float
    config: HookConfig


def _get_sfx_path(e: any) -> str:
    for attr in ("relative_path", "file", "path", "name"):
        val = getattr(e, attr, None)
        if val is not None:
            return str(val)
    return str(e)


def select_hook_sfx(sfx_entries: list, rng: random.Random | None = None) -> tuple[str, str]:
    """Select a riser and a hit for the hook from the audio catalog."""
    risers = sorted(
        (
            entry
            for entry in sfx_entries
            if getattr(entry, "role", "") in ("riser", "whoosh")
        ),
        key=lambda entry: (
            abs(getattr(entry, "duration_seconds", 1.8) - 1.8),
            _get_sfx_path(entry),
        ),
    )
    hits = sorted(
        (
            entry
            for entry in sfx_entries
            if getattr(entry, "role", "") in ("hook_hit", "hook_subdrop")
        ),
        key=lambda entry: (
            abs(getattr(entry, "duration_seconds", 1.5) - 1.5),
            _get_sfx_path(entry),
        ),
    )

    if not risers or not hits:
        raise ValueError("Missing risers or hits in the provided sfx entries")

    riser = risers[0]
    hit = hits[0] if rng is None else rng.choice(hits)

    return _get_sfx_path(riser), _get_sfx_path(hit)


def build_hook_plan(sfx_entries: list, config: HookConfig | None = None) -> HookPlan:
    """Build a plan for the hook effect."""
    if config is None:
        config = HookConfig()

    riser_path, hit_path = select_hook_sfx(sfx_entries)

    return HookPlan(
        riser_path=riser_path,
        hit_path=hit_path,
        hook_duration_seconds=config.hook_duration_seconds,
        config=config,
    )


def _number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def build_hook_filters(plan: HookPlan) -> list[str]:
    """Generate FFmpeg filter chain strings for the hook mixing."""
    c = plan.config

    f_riser = (
        f"[0:a]atrim=start=0:end={_number(plan.hook_duration_seconds)},"
        f"asetpts=PTS-STARTPTS,volume={_number(c.riser_volume)}[riser_out]"
    )

    hit_delay_sec = max(0.0, plan.hook_duration_seconds - c.hit_pre_trigger_seconds)
    hit_delay_ms = round(hit_delay_sec * 1000)
    f_hit = (
        f"[1:a]atrim=start=0:end=1.5,asetpts=PTS-STARTPTS,"
        f"adelay={hit_delay_ms}|{hit_delay_ms},volume={_number(c.hit_volume)}[hit_out]"
    )

    duck_end = plan.hook_duration_seconds
    recover_end = duck_end + c.bgm_recovery_seconds

    expr = (
        f"between(t,0,{_number(duck_end)})*{_number(c.bgm_duck_level)}+"
        f"between(t,{_number(duck_end)},{_number(recover_end)})*"
        f"({_number(c.bgm_duck_level)}+({_number(1.0 - c.bgm_duck_level)})*(t-{_number(duck_end)})/{_number(c.bgm_recovery_seconds)})+"
        f"gte(t,{_number(recover_end)})*1.0"
    )
    f_bgm = f"[2:a]volume='{expr}':eval=frame[bgm_out]"

    f_mix = "[riser_out][hit_out][bgm_out]amix=inputs=3:duration=longest:dropout_transition=0[hook_mix_out]"

    return [f_riser, f_hit, f_bgm, f_mix]


def build_hook_filters_for_export(plan: HookPlan) -> dict:
    """Return dict of track placement info for JianYing export."""
    c = plan.config
    hit_delay_sec = max(0.0, plan.hook_duration_seconds - c.hit_pre_trigger_seconds)
    return {
        "riser_start": 0.0,
        "riser_duration": plan.hook_duration_seconds,
        "hit_start": hit_delay_sec,
        "hit_duration": 1.5,
        "bgm_duck_start": 0.0,
        "bgm_duck_end": plan.hook_duration_seconds,
        "bgm_duck_level": c.bgm_duck_level,
    }
