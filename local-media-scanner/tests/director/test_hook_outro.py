from __future__ import annotations

import dataclasses
import random

import pytest
from pydantic import ValidationError

from director.hook_builder import (
    HookConfig,
    HookPlan,
    build_hook_filters,
    build_hook_plan,
    select_hook_sfx,
)
from director.outro_builder import (
    OutroConfig,
    OutroPlan,
    build_outro_filters,
    build_outro_plan,
    select_outro_sfx,
)
from director.schema import MusicEnding, MusicStructure


@dataclasses.dataclass
class DummySfx:
    role: str
    name: str
    file: str
    duration_seconds: float = 2.0


def test_hook_config_validation():
    with pytest.raises(ValidationError):
        HookConfig(hook_duration_seconds=-1)

    with pytest.raises(ValidationError):
        HookConfig(hook_duration_seconds=6)

    with pytest.raises(ValidationError):
        HookConfig(bgm_duck_level=1.5)

    valid_config = HookConfig(hook_duration_seconds=3.0, riser_volume=0.5)
    assert valid_config.hook_duration_seconds == 3.0
    assert valid_config.riser_volume == 0.5


def test_select_hook_sfx():
    sfx_entries = [
        DummySfx(role="riser", name="Riser 1", file="/riser1.wav", duration_seconds=1.0),
        DummySfx(role="riser", name="Riser 2", file="/riser2.wav", duration_seconds=1.7),
        DummySfx(role="whoosh", name="Whoosh 1", file="/whoosh1.wav", duration_seconds=2.5),
        DummySfx(role="hook_hit", name="Hit 1", file="/hit1.wav"),
        DummySfx(role="hook_subdrop", name="Sub 1", file="/sub1.wav"),
    ]

    rng = random.Random(42)
    riser, hit = select_hook_sfx(sfx_entries, rng=rng)
    assert riser == "/riser2.wav"  # closest to 1.8
    assert hit in ("/hit1.wav", "/sub1.wav")

    with pytest.raises(ValueError, match="Missing risers or hits"):
        select_hook_sfx([DummySfx(role="riser", name="Riser 1", file="/riser1.wav")])


def test_build_hook_filters():
    config = HookConfig(
        hook_duration_seconds=2.0,
        hit_pre_trigger_seconds=0.5,
        riser_volume=0.8,
        hit_volume=0.9,
        bgm_duck_level=0.3,
        bgm_recovery_seconds=0.5,
    )
    plan = HookPlan(
        riser_path="/riser.wav",
        hit_path="/hit.wav",
        hook_duration_seconds=2.0,
        config=config,
    )

    filters = build_hook_filters(plan)
    assert len(filters) == 4
    assert "atrim=start=0:end=2,asetpts=PTS-STARTPTS,volume=0.8[riser_out]" in filters[0]
    
    # Hit delay: 2.0 - 0.5 = 1.5s -> 1500ms
    assert "adelay=1500|1500" in filters[1]
    
    # BGM Ducking
    assert "between(t,0,2)*0.3" in filters[2]
    assert "between(t,2,2.5)*(0.3+(0.7)*(t-2)/0.5)" in filters[2]
    
    # Mix
    assert "amix=inputs=3" in filters[3]


def test_select_outro_sfx():
    sfx_entries = [
        DummySfx(role="outro_hit", name="Deep Hit 1", file="/deep_hit.wav"),
        DummySfx(role="outro_piano", name="Piano 1", file="/piano.wav"),
        DummySfx(role="outro_hit", name="Event Horizon Hit", file="/event.wav"),
    ]

    assert select_outro_sfx("hard_stop", sfx_entries) == "/deep_hit.wav"
    assert select_outro_sfx("decay", sfx_entries) == "/piano.wav"
    assert select_outro_sfx("fade", sfx_entries) == "/event.wav"
    assert select_outro_sfx("unknown", sfx_entries) is None


def test_build_outro_plan():
    music = MusicStructure(
        source_sha256="123",
        duration_seconds=60.0,
        bpm=120.0,
        ending=MusicEnding(behavior="decay", last_onset_seconds=58.0),
        confidence=0.9,
    )
    sfx_entries = [DummySfx(role="outro_piano", name="Piano 1", file="/piano.wav")]
    config = OutroConfig(outro_pre_end_seconds=1.0)

    plan = build_outro_plan(music, sfx_entries, config)
    assert plan.sfx_path == "/piano.wav"
    assert plan.trigger_time_seconds == 59.0

    # Test None
    music.ending.behavior = "unknown"
    plan = build_outro_plan(music, sfx_entries, config)
    assert plan.sfx_path is None

def test_build_outro_filters():
    config = OutroConfig(outro_volume=0.7)
    plan = OutroPlan(sfx_path="/piano.wav", trigger_time_seconds=10.5, reason="test", config=config)
    
    filters = build_outro_filters(plan, total_duration=15.0)
    assert len(filters) == 2
    assert "adelay=10500|10500" in filters[0]
    assert "amix=inputs=2" in filters[1]

    # Test empty if no sfx
    plan.sfx_path = None
    assert build_outro_filters(plan, total_duration=15.0) == []
