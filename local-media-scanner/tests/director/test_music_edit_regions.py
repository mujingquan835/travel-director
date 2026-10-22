"""music_edit_regions M0 (heuristic_v1): contract §6 invariants and §10.A checks."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from director.cli import app
from director.music_edit_regions import (
    BEAT_GRID_PROXY_WARNING,
    HOOK_WINDOW_SOFT,
    SHORT_REGION_UNMERGED,
    EditRegionConfig,
    analyze_music_edit_regions,
    build_project_music_edit_regions,
    load_music_edit_regions,
    peak_shot_mean,
)
from director.music_edit_regions_schema import (
    MISSING_SETTLE_OUTRO,
    MusicEditRegions,
    outro_window_seconds,
    region_invariant_violations,
)
from director.schema import (
    EnergyPoint,
    MusicEnding,
    MusicStructure,
    MusicStructureSection,
)


SHA = "a" * 64
TOL = 0.001


def _structure(
    levels: list[tuple[float, float]],
    *,
    bpm: float | None = 120.0,
    behavior: str = "decay",
    ramp_tail: tuple[float, float] | None = None,
    beat_free: list[tuple[float, float]] | None = None,
) -> MusicStructure:
    """Build a MusicStructure from (end_second, energy) steps on a 1 s grid.

    ``ramp_tail`` linearly ramps the final level; ``beat_free`` lists
    (start, end) spans without beats (sparse onsets).
    """

    values: list[float] = []
    sections: list[MusicStructureSection] = []
    start = 0.0
    for end, level in levels:
        count = int(end - start)
        segment = [level] * count
        if ramp_tail is not None and end == levels[-1][0]:
            first, last = ramp_tail
            segment = [first + (last - first) * i / max(1, count - 1) for i in range(count)]
        values.extend(segment)
        sections.append(
            MusicStructureSection(
                start=start, end=end, role="unknown", energy=level, confidence=0.7
            )
        )
        start = end
    duration = levels[-1][0]
    beats: list[float] = []
    if bpm:
        step = 60.0 / bpm
        t = 0.0
        while t < duration:
            if not any(a <= t < b for a, b in beat_free or []):
                beats.append(round(t, 6))
            t += step
    return MusicStructure(
        source_sha256=SHA,
        duration_seconds=duration,
        bpm=bpm,
        beats_seconds=beats,
        downbeats_seconds=beats[::4],
        energy_curve=[
            EnergyPoint(time_seconds=float(i), value=round(v, 6)) for i, v in enumerate(values)
        ],
        sections=sections,
        ending=MusicEnding(last_onset_seconds=duration - 2.0, behavior=behavior),
        confidence=0.9,
    )


# Quiet-but-dense opening, story, valley, dense climax, decaying tail.
TRAVEL_LEVELS = [(10.0, 0.5), (25.0, 0.6), (32.0, 0.1), (52.0, 1.0), (60.0, 0.4)]


def _travel(**kwargs) -> MusicStructure:
    return _structure(TRAVEL_LEVELS, ramp_tail=(0.6, 0.2), **kwargs)


def _roles(document: MusicEditRegions) -> list[tuple[float, float, str]]:
    return [(r.start, r.end, r.edit_role) for r in document.regions]


def _role_at(document: MusicEditRegions, time: float) -> str:
    return next(r.edit_role for r in document.regions if r.start <= time < r.end)


def _assert_invariants(document: MusicEditRegions) -> None:
    assert region_invariant_violations(document) == []
    regions = document.regions
    assert regions and abs(regions[0].start) <= TOL
    for a, b in zip(regions, regions[1:]):
        assert abs(b.start - a.end) <= TOL
    assert abs(regions[-1].end - document.duration_seconds) <= TOL
    assert all(r.end > r.start for r in regions)
    assert all(r.shot_min_s <= r.suggested_shot_mean_s <= r.shot_max_s for r in regions)


# --- heuristic role mapping (§8, §10.A constructed energy curves) ---------


def test_constructed_curve_maps_peak_breath_and_settle() -> None:
    document = analyze_music_edit_regions(_travel())

    _assert_invariants(document)
    assert document.provider == "heuristic_v1"
    assert document.schema_version == "0.1.0"
    assert _role_at(document, 40.0) == "peak_cut"
    assert _role_at(document, 28.0) == "breath"
    assert _role_at(document, 58.0) == "settle_outro"
    assert _role_at(document, 1.0) == "hook"
    assert _role_at(document, 15.0) in {"establish", "narrative_hold"}
    peak = next(r for r in document.regions if r.edit_role == "peak_cut")
    assert peak.musical_proxy == "climax" and peak.snap_policy == "beat"
    assert peak.desired_motion == "high" and peak.content_need == "high_visual_impact"
    breath = next(r for r in document.regions if r.edit_role == "breath")
    assert breath.musical_proxy == "breath" and breath.snap_policy == "free"
    assert all(r.musical_label is None and r.evidence_basis == "energy" for r in document.regions)
    assert document.downbeat_detector == "every_fourth_beat"
    assert BEAT_GRID_PROXY_WARNING in document.warnings


def test_high_energy_flat_mid_is_peak_cut_despite_low_beat_density() -> None:
    """Loud mid with sparse beats (proxy onset low, flat slope) must still be peak_cut under M0 proxy."""

    structure = _structure(
        [(10.0, 0.5), (25.0, 0.55), (45.0, 0.95), (60.0, 0.35)],
        ramp_tail=(0.5, 0.15),
        beat_free=[(25.0, 45.0)],
    )
    document = analyze_music_edit_regions(structure)
    _assert_invariants(document)
    assert BEAT_GRID_PROXY_WARNING in document.warnings
    assert _role_at(document, 35.0) == "peak_cut"
    peak = next(r for r in document.regions if r.start <= 35.0 < r.end)
    assert peak.edit_role == "peak_cut"
    assert peak.mean_energy >= 0.9
    assert peak.onset_rate < 0.5  # beat-free mid → low proxy density


def test_rising_region_becomes_build() -> None:
    structure = _structure(
        [(10.0, 0.5), (22.0, 0.3), (30.0, 0.9), (45.0, 0.95), (60.0, 0.4)],
        ramp_tail=(0.4, 0.1),
    )
    values = [p.value for p in structure.energy_curve]
    values[10:22] = [0.3 + 0.05 * i for i in range(12)]  # steady climb
    structure = structure.model_copy(
        update={
            "energy_curve": [
                EnergyPoint(time_seconds=float(i), value=round(v, 6))
                for i, v in enumerate(values)
            ]
        }
    )
    document = analyze_music_edit_regions(structure)
    _assert_invariants(document)
    assert _role_at(document, 15.0) == "build"
    assert next(r for r in document.regions if r.edit_role == "build").snap_policy == "beat"


@pytest.mark.parametrize("bpm", [60.0, 90.0, 120.0, 174.0, 30.0, None])
def test_peak_region_shot_length_is_shorter_than_narrative_hold(bpm) -> None:
    levels = [(10.0, 0.5), (30.0, 0.6), (50.0, 0.6), (57.0, 0.1), (88.0, 1.0), (100.0, 0.4)]
    document = analyze_music_edit_regions(_structure(levels, bpm=bpm, ramp_tail=(0.5, 0.2)))

    _assert_invariants(document)
    peaks = [r for r in document.regions if r.edit_role == "peak_cut"]
    holds = [r for r in document.regions if r.edit_role == "narrative_hold"]
    assert peaks and holds
    assert max(r.suggested_shot_mean_s for r in peaks) < min(
        r.suggested_shot_mean_s for r in holds
    )


def test_peak_shot_mean_follows_bpm_and_stays_in_budget() -> None:
    assert peak_shot_mean(120.0) == 0.5
    assert peak_shot_mean(None) == 1.0
    assert peak_shot_mean(75.0) == pytest.approx(0.8)
    assert peak_shot_mean(30.0) == 1.4  # 60/bpm=2.0 clamped (invariant 4)


# --- hook window (§4, §8.5, decision §12.1) -------------------------------


def test_hook_region_is_enabled_by_default_for_every_film_type() -> None:
    assert EditRegionConfig().enable_hook_region is True
    for duration in (15.0, 30.0, 60.0, 180.0):
        document = analyze_music_edit_regions(
            _structure([(duration, 0.8)], ramp_tail=(0.9, 0.3))
        )
        _assert_invariants(document)
        first = document.regions[0]
        assert first.start == 0.0
        assert first.end == pytest.approx(round(min(3.0, 0.08 * duration), 3))
        assert first.edit_role in {"hook", "establish"}


def test_dense_opening_is_hook_with_attention_budget() -> None:
    document = analyze_music_edit_regions(_travel())
    hook = document.regions[0]
    assert (hook.start, hook.end, hook.edit_role) == (0.0, 3.0, "hook")
    assert (hook.suggested_shot_mean_s, hook.shot_min_s, hook.shot_max_s) == (0.9, 0.6, 1.2)
    assert hook.musical_proxy == "intro" and hook.content_need == "attention_hook"
    assert HOOK_WINDOW_SOFT not in document.warnings


def test_sparse_quiet_opening_keeps_window_but_softens_to_establish() -> None:
    document = analyze_music_edit_regions(_travel(beat_free=[(0.0, 3.0)]))
    first = document.regions[0]
    assert (first.start, first.end, first.edit_role) == (0.0, 3.0, "establish")
    assert HOOK_WINDOW_SOFT in document.warnings
    _assert_invariants(document)


def test_hook_can_be_explicitly_disabled() -> None:
    document = analyze_music_edit_regions(
        _travel(), EditRegionConfig(enable_hook_region=False)
    )
    _assert_invariants(document)
    assert all(r.edit_role != "hook" for r in document.regions)
    assert document.regions[0].edit_role == "establish"
    assert document.regions[0].end >= 4.0


# --- §6 invariants on producer output -------------------------------------


@pytest.mark.parametrize(
    "levels",
    [
        TRAVEL_LEVELS,
        [(12.0, 0.5)],
        [(13.0, 0.9), (14.5, 0.2), (26.0, 0.8)],
        [(5.0, 0.3), (7.0, 0.9), (9.0, 0.2), (40.0, 0.6), (41.0, 1.0), (90.0, 0.5)],
        [(3.0, 0.6)],
        [(240.0, 0.7)],
    ],
)
def test_producer_output_satisfies_all_invariants(levels) -> None:
    document = analyze_music_edit_regions(_structure(levels, ramp_tail=(0.7, 0.1)))
    _assert_invariants(document)
    peaks = [r for r in document.regions if r.edit_role == "peak_cut"]
    breaths = [r for r in document.regions if r.edit_role == "breath"]
    assert not any(
        min(p.end, b.end) - max(p.start, b.start) > TOL for p in peaks for b in breaths
    )
    if document.duration_seconds >= 12.0:
        window_start = document.duration_seconds - outro_window_seconds(
            document.duration_seconds
        )
        assert any(
            r.edit_role == "settle_outro" or r.musical_proxy == "outro"
            for r in document.regions
            if r.end > window_start
        )


def test_loud_hard_stop_ending_reports_missing_settle_instead_of_pretending() -> None:
    structure = _structure(
        [(10.0, 0.5), (25.0, 0.6), (32.0, 0.1), (60.0, 1.0)], behavior="hard_stop"
    )
    document = analyze_music_edit_regions(structure)

    _assert_invariants(document)
    window_start = 60.0 - outro_window_seconds(60.0)
    tail = [r for r in document.regions if r.end > window_start]
    assert MISSING_SETTLE_OUTRO in document.warnings
    assert all(r.edit_role == "unknown" and r.musical_proxy == "unknown" for r in tail)
    assert all(r.edit_role != "settle_outro" for r in document.regions)


def test_short_regions_merge_or_are_marked_unknown() -> None:
    merged = analyze_music_edit_regions(
        _structure([(10.0, 0.5), (11.5, 0.55), (30.0, 0.6), (60.0, 0.4)], ramp_tail=(0.5, 0.2))
    )
    _assert_invariants(merged)
    middle = [r for r in merged.regions[1:] if r.end <= 60.0 - 8.0 + TOL]
    assert all(r.end - r.start >= 4.0 - TOL for r in middle)

    tiny = analyze_music_edit_regions(_structure([(12.5, 0.5)], ramp_tail=(0.5, 0.2)))
    _assert_invariants(tiny)
    assert SHORT_REGION_UNMERGED in tiny.warnings
    assert any(r.edit_role == "unknown" for r in tiny.regions)


def test_target_duration_clips_to_the_film_window() -> None:
    document = analyze_music_edit_regions(
        _travel(), EditRegionConfig(target_duration_seconds=45.0)
    )
    _assert_invariants(document)
    assert document.duration_seconds == 45.0
    assert document.regions[-1].end == 45.0
    assert all(b < 45.0 for b in document.beats_seconds)
    assert document.ending.behavior == "unknown"


# --- §6 invariants on the validator (each must be rejected) ---------------


def _valid_payload() -> dict:
    return analyze_music_edit_regions(_travel()).model_dump(mode="json")


def _violations(payload: dict) -> list[str]:
    with pytest.raises(ValidationError):
        MusicEditRegions.model_validate(payload)
    regions = [
        MusicEditRegions.model_fields["regions"].annotation.__args__[0].model_construct(**r)
        for r in payload["regions"]
    ]
    document = MusicEditRegions.model_construct(
        **{**payload, "regions": regions}
    )
    return region_invariant_violations(document)


def test_invariant_1_rejects_empty_or_late_start() -> None:
    payload = _valid_payload()
    payload["regions"] = []
    with pytest.raises(ValidationError, match="invariant 1"):
        MusicEditRegions.model_validate(payload)
    payload = _valid_payload()
    payload["regions"][0]["start"] = 0.5
    assert any("invariant 1" in v for v in _violations(payload))


def test_invariant_2_rejects_gaps_and_short_coverage() -> None:
    payload = _valid_payload()
    payload["regions"][1]["start"] += 0.5
    assert any("invariant 2" in v for v in _violations(payload))
    payload = _valid_payload()
    payload["regions"][-1]["end"] -= 0.5
    assert any("invariant 2" in v for v in _violations(payload))


def test_invariant_2_and_3_accept_one_millisecond_tolerance() -> None:
    payload = _valid_payload()
    payload["regions"][1]["start"] += 0.0005
    payload["regions"][0]["start"] = 0.0004
    MusicEditRegions.model_validate(payload)


def test_invariant_3_rejects_overlap_and_negative_length() -> None:
    payload = _valid_payload()
    payload["regions"][1]["start"] -= 0.5
    assert any("invariant 3" in v for v in _violations(payload))
    payload = _valid_payload()
    payload["regions"][1]["end"] = payload["regions"][1]["start"] - 1.0
    with pytest.raises(ValidationError, match="end > start"):
        MusicEditRegions.model_validate(payload)


def test_invariant_4_rejects_shot_mean_outside_budget() -> None:
    for field, value in (("suggested_shot_mean_s", 9.0), ("suggested_shot_mean_s", 0.1)):
        payload = _valid_payload()
        payload["regions"][2][field] = value
        with pytest.raises(ValidationError, match="shot_min_s <= suggested_shot_mean_s"):
            MusicEditRegions.model_validate(payload)
    payload = _valid_payload()
    payload["regions"][2]["shot_max_s"] = payload["regions"][2]["shot_min_s"]
    with pytest.raises(ValidationError, match="shot_max_s > shot_min_s"):
        MusicEditRegions.model_validate(payload)


def test_invariant_5_rejects_peak_overlapping_breath() -> None:
    payload = _valid_payload()
    roles = [r["edit_role"] for r in payload["regions"]]
    breath = payload["regions"][roles.index("breath")]
    peak = payload["regions"][roles.index("peak_cut")]
    peak["start"] = breath["start"] + 1.0
    found = _violations(payload)
    assert any("invariant 5" in v for v in found)


def test_invariant_6_requires_settle_or_honest_warning() -> None:
    payload = _valid_payload()
    last = payload["regions"][-1]
    assert last["edit_role"] == "settle_outro"
    last.update(edit_role="narrative_hold", musical_proxy="unknown")
    found = _violations(payload)
    assert any("missing_settle_outro" in v for v in found)
    assert any("marked unknown" in v for v in found)

    payload["warnings"].append(MISSING_SETTLE_OUTRO)
    found = _violations(payload)
    assert any("marked unknown" in v for v in found)

    payload["regions"][-1]["edit_role"] = "unknown"
    MusicEditRegions.model_validate(payload)


def test_invariant_6_not_required_below_twelve_seconds() -> None:
    payload = analyze_music_edit_regions(
        _structure([(10.0, 0.6)], ramp_tail=(0.6, 0.5))
    ).model_dump(mode="json")
    for region in payload["regions"]:
        region.update(edit_role="narrative_hold", musical_proxy="rise")
        region.update(suggested_shot_mean_s=4.0, shot_min_s=3.0, shot_max_s=5.5)
    MusicEditRegions.model_validate(payload)


# --- invariant 7: deterministic output -------------------------------------


def test_invariant_7_same_input_and_config_is_byte_stable() -> None:
    config = EditRegionConfig()
    first = analyze_music_edit_regions(_travel(), config).model_dump_json()
    second = analyze_music_edit_regions(_travel(), config).model_dump_json()
    assert first == second
    for region in json.loads(first)["regions"]:
        for key in ("start", "end"):
            assert region[key] == round(region[key], 3)


def test_invariant_7_fixed_wav_fixture_is_stable(click_track: Path) -> None:
    from director.music_analysis import AudioAnalysisConfig, analyze_music

    runs = [
        analyze_music_edit_regions(analyze_music(click_track, AudioAnalysisConfig()))
        for _ in range(2)
    ]
    dumps = [run.model_dump_json() for run in runs]
    assert dumps[0] == dumps[1]
    document = runs[0]
    _assert_invariants(document)
    assert _role_at(document, 40.0) == "peak_cut"
    assert _role_at(document, 27.0) == "breath"
    assert _role_at(document, 57.0) == "settle_outro"
    assert document.regions[0].end == 2.02
    assert document.regions[0].end_raw_s == 3.0


def test_music_structure_major_version_is_unchanged(click_track: Path) -> None:
    assert MusicStructure.model_fields["schema_version"].default == "0.1.0"
    assert "regions" not in MusicStructure.model_fields
    assert "edit_role" not in MusicStructure.model_fields["sections"].annotation.__args__[0].model_fields


def test_only_heuristic_v1_is_available_in_m0() -> None:
    for provider in ("allin1", "beat_this+heuristic", "hybrid"):
        with pytest.raises(ValueError, match="heuristic_v1"):
            analyze_music_edit_regions(_travel(), EditRegionConfig(provider=provider))
    with pytest.raises(ValidationError):
        EditRegionConfig(provider="cloud")


# --- project artifact, CLI and track-change invalidation (§3, §9) ----------


def _frozen_project(tmp_path: Path, click_track: Path):
    from director.audio_import import freeze_and_analyze_music
    from director.project import create_visual_project
    from director.visual_schema import RawCreativeBrief

    paths = create_visual_project(
        tmp_path / "runs", "demo", RawCreativeBrief(raw_description="60秒旅行视频")
    )
    freeze_and_analyze_music(paths, click_track)
    return paths


def _cli(*args: str):
    return CliRunner().invoke(app, ["analyze-music-edit-regions", *args])


def test_cli_writes_sibling_artifact_without_external_calls(
    tmp_path: Path, click_track: Path
) -> None:
    from director.project import load_project_state

    paths = _frozen_project(tmp_path, click_track)
    structure_before = paths.music_structure.read_bytes()

    result = _cli("--project", str(paths.root))

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["status"] == "created"
    assert report["provider"] == "heuristic_v1"
    assert report["external_call_count"] == 0
    assert report["candidate_status"] == "unconfirmed_candidates"
    assert paths.music_edit_regions == paths.root / "music_edit_regions.json"
    assert paths.music_edit_regions.parent == paths.music_structure.parent
    assert paths.music_structure.read_bytes() == structure_before
    document = MusicEditRegions.model_validate_json(paths.music_edit_regions.read_text())
    structure = MusicStructure.model_validate_json(structure_before)
    assert document.source_sha256 == structure.source_sha256
    assert "music_edit_regions" in load_project_state(paths).completed_artifact_hashes
    assert load_music_edit_regions(paths) == document
    external = paths.external_calls
    assert not external.exists() or json.loads(external.read_text()) == []

    before = paths.music_edit_regions.read_bytes()
    again = json.loads(_cli("--project", str(paths.root)).output)
    assert again["status"] == "unchanged"
    assert paths.music_edit_regions.read_bytes() == before

    changed = json.loads(_cli("--project", str(paths.root), "--disable-hook-region").output)
    assert changed["status"] == "regenerated"
    assert "hook" not in changed["edit_roles"]


def test_stale_regions_from_another_track_are_ignored_then_regenerated(
    tmp_path: Path, click_track: Path
) -> None:
    from director.project import record_supporting_artifact

    paths = _frozen_project(tmp_path, click_track)
    stale = analyze_music_edit_regions(_travel())  # bound to a different sha
    record_supporting_artifact(
        paths, paths.music_edit_regions, stale, state_key="music_edit_regions"
    )
    assert load_music_edit_regions(paths) is None

    report = build_project_music_edit_regions(paths.root)

    assert report["status"] == "regenerated"
    assert report["invalidated_previous"] is True
    assert report["previous_source_sha256"] == SHA
    fresh = load_music_edit_regions(paths)
    assert fresh is not None and fresh.source_sha256 != SHA


def test_cli_requires_frozen_music_and_supported_provider(
    tmp_path: Path, click_track: Path
) -> None:
    from director.project import create_visual_project
    from director.visual_schema import RawCreativeBrief

    bare = create_visual_project(
        tmp_path / "runs", "bare", RawCreativeBrief(raw_description="旅行")
    )
    result = _cli("--project", str(bare.root))
    assert result.exit_code != 0
    assert not bare.music_edit_regions.exists()

    paths = _frozen_project(tmp_path, click_track)
    result = _cli("--project", str(paths.root), "--provider", "allin1")
    assert result.exit_code != 0
    assert not paths.music_edit_regions.exists()


def test_new_music_version_invalidates_old_regions(
    tmp_path: Path, monkeypatch, click_track: Path
) -> None:
    from director.project import load_project_state, open_project
    from director.runner import run_travel_director
    from tests.director.test_creative_runner import reach_creative
    from tests.director.test_runner import BRIEF, _submit_creative

    source, project, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, project, BRIEF, request)
    assert (
        run_travel_director(source, BRIEF, project=project, music=click_track).status
        == "waiting_for_timeline"
    )
    parent_report = build_project_music_edit_regions(project)
    parent_bytes = (project / "music_edit_regions.json").read_bytes()

    other = tmp_path / "other.wav"
    with wave.open(str(click_track), "rb") as original:
        params, frames = original.getparams(), original.readframes(original.getnframes())
    with wave.open(str(other), "wb") as changed:
        changed.setparams(params)
        changed.writeframes(frames + b"\0\0" * params.nchannels * 100)
    version = run_travel_director(
        source, BRIEF, project=project, music=other, new_music_version=True
    )
    assert version.status == "waiting_for_timeline", version.message
    child = open_project(Path(version.project_path))

    assert (project / "music_edit_regions.json").read_bytes() == parent_bytes
    assert not child.music_edit_regions.exists()
    assert "music_edit_regions" not in load_project_state(child).completed_artifact_hashes
    assert load_music_edit_regions(child) is None

    child_report = build_project_music_edit_regions(child.root)
    assert child_report["status"] == "created"
    assert child_report["source_sha256"] != parent_report["source_sha256"]
