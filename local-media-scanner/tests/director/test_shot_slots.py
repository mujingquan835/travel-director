"""Shot slots follow the phrase, not an equal split of suggested_shot_mean_s."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from director.beat_grid import compare_beat_trackers, select_backend
from director.music_analysis import AudioAnalysisConfig, analyze_music
from director.music_edit_regions import BEAT_GRID_PROXY_WARNING, analyze_music_edit_regions
from director.music_edit_regions_schema import MusicEditRegion, MusicEditRegions
from director.schema import BeatEvent, BeatGridInfo, EnergyPoint, MusicEnding, MusicStructure
from director.shot_slots import plan_shot_slots


SHA = "c" * 64


def _beat(index: int, moment: float, *, down: bool, accent: bool = False, energy: float = 0.5) -> BeatEvent:
    return BeatEvent(
        i=index,
        t=moment,
        bar=index // 4,
        beat_in_bar=index % 4,
        is_downbeat=down,
        is_phrase_start=down and index % 16 == 0,
        onset_strength=0.9 if accent else 0.4,
        energy=energy,
        accent=accent,
    )


def _region(region_id: str, start: float, end: float, role: str, shot: tuple[float, float, float]) -> MusicEditRegion:
    mean, low, high = shot
    proxy = {
        "hook": "intro",
        "establish": "intro",
        "build": "rise",
        "peak_cut": "climax",
        "settle_outro": "outro",
        "unknown": "unknown",
        "breath": "breath",
        "narrative_hold": "rise",
    }[role]
    return MusicEditRegion(
        region_id=region_id,
        start=start,
        end=end,
        edit_role=role,  # type: ignore[arg-type]
        musical_proxy=proxy,  # type: ignore[arg-type]
        mean_energy=0.6,
        onset_rate=2.0,
        energy_slope=0.0,
        suggested_shot_mean_s=mean,
        shot_min_s=low,
        shot_max_s=high,
        snap_policy="beat" if role in {"hook", "build", "peak_cut"} else "free",
        desired_motion="high" if role in {"hook", "peak_cut"} else "low",
        content_need="high_visual_impact" if role == "peak_cut" else "orientation_detail",
        confidence=0.8,
        evidence_basis="energy",
    )


def _document(regions: list[MusicEditRegion], duration: float, *, accent_at: set[int] | None = None) -> MusicEditRegions:
    accent_at = accent_at or set()
    beats = [
        _beat(index, round(index * 0.5, 3), down=index % 4 == 0, accent=index in accent_at)
        for index in range(int(duration / 0.5) + 1)
        if index * 0.5 < duration - 0.001
    ]
    # Keep the beat on the final boundary out of the open interval; anchors still see downbeats via is_downbeat.
    if duration % 2 == 0:
        beats.append(_beat(len(beats), duration, down=True))
        beats[-1] = beats[-1].model_copy(update={"i": len(beats) - 1})
    return MusicEditRegions(
        source_sha256=SHA,
        duration_seconds=duration,
        bpm=120.0,
        provider="heuristic_v1",
        downbeat_detector="onset_phase_heuristic",
        downbeat_confidence=0.8,
        beats=beats,
        beats_seconds=[beat.t for beat in beats],
        downbeats_seconds=[beat.t for beat in beats if beat.is_downbeat],
        beat_grid=BeatGridInfo(period_s=0.5, coverage=1.0),
        energy_curve=[EnergyPoint(time_seconds=float(second), value=0.6) for second in range(int(duration))],
        regions=regions,
        ending=MusicEnding(last_onset_seconds=duration - 0.5, behavior="hard_stop"),
        confidence=0.8,
        meter_assumed=4,
    )


def test_peak_slots_are_not_an_equal_split() -> None:
    document = _document(
        [_region("r05", 0.0, 8.0, "peak_cut", (0.5, 0.5, 1.4))],
        8.0,
        accent_at={0, 1, 2, 4, 5, 6},
    )
    planned = plan_shot_slots(document)
    lengths = [round(slot.end - slot.start, 3) for slot in planned.shot_slots]
    assert len(lengths) >= 4
    assert len(set(lengths)) > 1
    equal = round(8.0 / len(lengths), 3)
    assert any(abs(length - equal) > 0.05 for length in lengths)


def test_build_cuts_land_on_downbeats() -> None:
    document = _document(
        [_region("r04", 0.0, 8.0, "build", (2.0, 1.5, 2.5))],
        8.0,
    )
    planned = plan_shot_slots(document)
    downbeats = [beat.t for beat in planned.beats if beat.is_downbeat]
    assert planned.shot_slots
    for slot in planned.shot_slots:
        assert any(abs(slot.start - moment) <= 0.02 for moment in downbeats)
        assert any(abs(slot.end - moment) <= 0.02 for moment in downbeats)
        assert slot.reason_zh
        assert slot.reason_code
        assert slot.shot_type


def test_every_slot_has_a_reason_and_evidence() -> None:
    document = _document(
        [
            _region("r01", 0.0, 4.0, "hook", (0.9, 0.6, 1.2)),
            _region("r02", 4.0, 8.0, "unknown", (3.0, 1.5, 5.0)),
        ],
        8.0,
    )
    planned = plan_shot_slots(document)
    assert planned.shot_slots
    for slot in planned.shot_slots:
        assert slot.reason_code
        assert slot.reason_zh.strip()
        assert slot.shot_type
        assert slot.evidence.rule == slot.reason_code
        assert slot.evidence.region_id == slot.region_id
    unknown = [slot for slot in planned.shot_slots if slot.region_id == "r02"]
    assert unknown
    assert {slot.shot_type for slot in unknown} == {"?"}


def test_hit_hold_with_accent_starts_on_that_beat() -> None:
    document = _document(
        [_region("r05", 0.0, 8.0, "peak_cut", (0.5, 0.5, 1.4))],
        8.0,
        accent_at={0},
    )
    planned = plan_shot_slots(document)
    held = next(slot for slot in planned.shot_slots if slot.reason_code == "HIT_HOLD")
    assert held.accent_at_start
    assert any(beat.accent and abs(beat.t - held.start) <= 0.02 for beat in planned.beats)


def test_same_input_is_byte_identical() -> None:
    document = _document(
        [_region("r04", 0.0, 8.0, "build", (2.0, 1.5, 2.5))],
        8.0,
    )
    assert plan_shot_slots(document).model_dump_json() == plan_shot_slots(document).model_dump_json()


def test_missing_beat_this_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing():
        raise ImportError("beat_this is not installed")

    monkeypatch.setattr("director.beat_grid.beat_this_module", _missing)
    backend, note = select_backend("beat_this")
    assert backend == "librosa"
    assert "回退" in note
    assert "下载" in note


def test_analyze_music_records_librosa_when_beat_this_is_missing(click_track: Path) -> None:
    result = analyze_music(click_track, AudioAnalysisConfig(beat_backend="beat_this"))
    assert result.beat_backend == "librosa"
    assert "回退" in result.beat_backend_note
    assert result.onsets
    assert result.beat_events
    assert result.downbeat_detector in {"onset_phase_heuristic", "every_fourth_beat"}
    assert "onset_rate_from_beat_grid_proxy" not in result.analysis_warnings
    regions = analyze_music_edit_regions(result)
    assert BEAT_GRID_PROXY_WARNING not in regions.warnings
    assert regions.shot_slots
    assert all(slot.reason_zh and slot.reason_code and slot.shot_type for slot in regions.shot_slots)


def test_synthetic_curve_without_onsets_keeps_the_proxy_warning() -> None:
    from tests.director.test_music_edit_regions import _travel

    document = analyze_music_edit_regions(_travel())
    assert document.downbeat_detector == "every_fourth_beat"
    assert BEAT_GRID_PROXY_WARNING in document.warnings
    assert document.shot_slots == []


def test_trim_true_drops_quiet_edges_on_a_123_bpm_minute(tmp_path: Path) -> None:
    sample_rate = 22_050
    duration = 60.0
    bpm = 123.0
    audio = np.zeros(int(sample_rate * duration), dtype=np.float32)
    click = np.exp(-np.linspace(0.0, 8.0, int(0.04 * sample_rate))).astype(np.float32)
    step = 60.0 / bpm
    moment = 0.0
    while moment < duration - 0.05:
        amp = 0.02 if moment < 8.0 or moment > 52.0 else 0.8
        start = int(moment * sample_rate)
        audio[start : start + len(click)] += amp * click
        moment += step
    path = tmp_path / "quiet-edges-123.wav"
    sf.write(path, audio, sample_rate, subtype="PCM_16")
    measured = compare_beat_trackers(path, sample_rate=sample_rate)
    assert int(measured["beats_trim_true"]) < int(measured["beats_trim_false"])
    assert int(measured["beats_trim_false"]) >= 110


def _structure_roundtrip() -> None:
    MusicStructure.model_validate(
        {
            "source_sha256": SHA,
            "duration_seconds": 1.0,
            "ending": {"behavior": "unknown"},
        }
    )
