"""Region boundaries and shot cuts share one time."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from director.beat_grid import build_rhythm
from director.boundary_snap import choose_boundary, filter_downbeat_times
from director.confirm_serve import start_confirm_desk
from director.music_edit_regions import analyze_music_edit_regions
from director.music_edit_regions_schema import MusicEditRegion, MusicEditRegions
from director.music_edit_regions_versions import (
    confirm_regions_draft,
    load_regions_draft,
    load_regions_version,
    save_regions_draft,
)
from director.music_edit_regions_schema import region_invariant_violations
from director.schema import (
    BeatEvent,
    BeatGridInfo,
    EnergyPoint,
    MusicEnding,
    MusicStructure,
    MusicStructureSection,
)
from director.shot_slots import apply_boundary_snaps, plan_shot_slots
from tests.director.test_confirm_serve import _json, _port, _post_json, _request
from tests.director.test_music_edit_regions import _travel
from tests.director.test_music_edit_regions_versions import _confirmed_bytes, _project


SHA = "d" * 64

# beat_this small0, dbn=False, on the same 120 BPM track: 31 downbeats.
# 15.22 sits 0.50s after 14.72. 58.24 sits 1.50s after 56.74.
USER_DOWNBEATS = [
    0.72, 2.74, 4.74, 6.74, 8.74, 10.72, 12.74, 14.72, 15.22, 16.72, 18.72,
    20.72, 22.74, 24.74, 26.72, 28.74, 30.72, 32.74, 34.72, 36.74, 38.72, 40.74,
    42.72, 44.74, 46.72, 48.74, 50.72, 52.74, 54.72, 56.74, 58.24,
]


def test_user_downbeats_snap_inside_half_a_bar_and_drop_only_the_close_extra() -> None:
    kept, dropped = filter_downbeat_times(USER_DOWNBEATS, 0.5)
    assert 15.22 in dropped
    assert 58.24 in kept
    assert 14.72 in kept
    assert 58.24 not in dropped

    cases = {
        8.0: 8.74,
        25.0: 24.74,
        40.0: 40.74,
        51.935: 52.74,
    }
    beats = list(USER_DOWNBEATS) + [7.75, 24.9, 39.7, 51.5]
    for moment, expected in cases.items():
        choice = choose_boundary(moment, 60.0, USER_DOWNBEATS, beats, 0.5, 0.935)
        assert choice.rule == "downbeat"
        assert choice.time == expected
        assert "强拍" in choice.explanation_zh
        assert "半小节" in choice.explanation_zh
        assert "1.00s" in choice.explanation_zh
        assert choice.pending


def test_low_confidence_uses_a_beat_only_past_half_a_bar() -> None:
    far = choose_boundary(10.0, 60.0, [11.3], [10.4, 11.3], 0.5, 0.05)
    assert far.rule == "beat"
    assert far.time == 10.4
    assert far.warning == "boundary_snap_beat_low_confidence"
    assert "0.050" in far.explanation_zh
    assert "半小节" in far.explanation_zh

    still = choose_boundary(10.0, 60.0, [11.3], [10.4, 11.3], 0.5, 0.90)
    assert still.rule == "downbeat"
    assert still.time == 11.3
    assert "超过半小节" in still.explanation_zh
    assert "1 小节" in still.explanation_zh

    close = choose_boundary(8.0, 60.0, [8.74], [8.2, 8.74], 0.5, 0.008)
    assert close.rule == "downbeat"
    assert close.time == 8.74
    assert "没有超过半小节" in close.explanation_zh


def test_beyond_one_bar_does_not_move_and_is_not_adopted() -> None:
    choice = choose_boundary(10.0, 60.0, [13.5], [12.6], 0.5, 0.9)
    assert choice.rule == "beyond_bar"
    assert choice.time == 10.0
    assert choice.pending
    assert choice.warning == "boundary_snap_beyond_bar"
    assert "不移动" in choice.explanation_zh

    document = _sample()
    document = document.model_copy(
        update={
            "downbeat_confidence": 0.9,
            "beats": [
                BeatEvent(
                    i=0, t=0.0, bar=0, beat_in_bar=0, is_downbeat=True,
                    onset_strength=0.5, energy=0.5,
                ),
                BeatEvent(
                    i=1, t=13.5, bar=1, beat_in_bar=0, is_downbeat=True,
                    onset_strength=0.5, energy=0.5,
                ),
            ],
            "downbeats_seconds": [0.0, 13.5],
            "beats_seconds": [0.0, 13.5],
        }
    )
    # 8.0 is 5.5s from 13.5 and 8s from 0, both past one bar (2s).
    adopted = apply_boundary_snaps(document, None)
    assert [region.start for region in adopted.regions] == [region.start for region in document.regions]
    assert adopted is document or adopted.model_dump() == document.model_dump()


def test_build_rhythm_drops_a_downbeat_closer_than_half_a_bar() -> None:
    times = np.asarray([0.72, 2.74, 4.74, 6.74, 8.74, 14.72, 15.22, 16.72, 56.74, 58.24], dtype=np.float64)
    audio = np.zeros(int(60 * 22050), dtype=np.float32)
    envelope = np.zeros(200, dtype=np.float64)
    rhythm = build_rhythm(
        audio=audio,
        sample_rate=22050,
        hop_length=512,
        duration=60.0,
        bpm=120.0,
        beat_times=times,
        onset_envelope=envelope,
        onset_times=np.asarray([], dtype=np.float64),
        model_downbeats=[14.72, 15.22, 16.72, 56.74, 58.24],
        backend="beat_this",
        note="",
        plp_beats=0,
    )
    assert 15.22 not in rhythm["downbeats_seconds"]
    assert 58.24 in rhythm["downbeats_seconds"]
    assert 14.72 in rhythm["downbeats_seconds"]
    assert any(abs(moment - 15.22) < 1e-6 for moment in rhythm["downbeat_cluster_times"])
    assert "downbeat_cluster" in rhythm["analysis_warnings"]
    assert all(abs(phrase.start - 15.22) > 0.05 for phrase in rhythm["phrases"])
    assert all(not event.is_downbeat or abs(event.t - 15.22) > 0.05 for event in rhythm["beat_events"])


def test_analysis_without_beat_events_keeps_the_hook_at_three_seconds() -> None:
    plain = analyze_music_edit_regions(_travel())
    assert plain.regions[0].end == 3.0
    assert plain.regions[0].end_raw_s is None

    structure = _travel()
    events = []
    moment = 0.0
    index = 0
    while moment < structure.duration_seconds - 0.001:
        events.append(
            BeatEvent(
                i=index,
                t=round(moment, 6),
                bar=index // 4,
                beat_in_bar=index % 4,
                is_downbeat=index % 4 == 0,
                onset_strength=0.4,
                energy=0.4,
            )
        )
        index += 1
        moment += 0.5
    snapped = analyze_music_edit_regions(
        structure.model_copy(
            update={
                "beat_events": events,
                "downbeat_confidence": 0.8,
                "beat_grid": BeatGridInfo(period_s=0.5, coverage=1.0),
            }
        )
    )
    assert snapped.regions[0].end == 2.0
    assert snapped.regions[0].end_raw_s == 3.0
    assert snapped.shot_slots
    assert snapped.shot_slots[0].start == snapped.regions[0].start
    assert abs(snapped.shot_slots[0].end) > 0
    first_slots = [slot for slot in snapped.shot_slots if slot.region_id == snapped.regions[0].region_id]
    assert first_slots[-1].end == snapped.regions[0].end


def _region(region_id: str, start: float, end: float, role: str) -> MusicEditRegion:
    proxy = "outro" if role == "settle_outro" else "intro" if role == "establish" else "rise"
    need = "closing_image" if role == "settle_outro" else "orientation_detail"
    return MusicEditRegion(
        region_id=region_id,
        start=start,
        end=end,
        edit_role=role,  # type: ignore[arg-type]
        musical_proxy=proxy,  # type: ignore[arg-type]
        mean_energy=0.4,
        onset_rate=1.0,
        energy_slope=0.0,
        suggested_shot_mean_s=3.2,
        shot_min_s=2.5,
        shot_max_s=4.0,
        snap_policy="free",
        desired_motion="low",
        content_need=need,
        confidence=0.6,
        evidence_basis="energy",
    )


def _sample() -> MusicEditRegions:
    beats: list[BeatEvent] = []
    moments = sorted(set(USER_DOWNBEATS + [7.75, 24.9, 39.7, 51.5]))
    for index, moment in enumerate(moments):
        beats.append(
            BeatEvent(
                i=index,
                t=moment,
                bar=index,
                beat_in_bar=0,
                is_downbeat=moment in USER_DOWNBEATS,
                onset_strength=0.5,
                energy=0.5,
            )
        )
    return MusicEditRegions(
        source_sha256=SHA,
        duration_seconds=60.0,
        bpm=120.0,
        provider="beat_this+heuristic",
        downbeat_detector="beat_this",
        downbeat_confidence=0.935,
        beats=beats,
        beats_seconds=[beat.t for beat in beats],
        downbeats_seconds=list(USER_DOWNBEATS),
        beat_grid=BeatGridInfo(period_s=0.5, coverage=1.0),
        energy_curve=[EnergyPoint(time_seconds=float(second), value=0.4) for second in range(60)],
        regions=[
            _region("r01", 0.0, 8.0, "establish"),
            _region("r02", 8.0, 25.0, "narrative_hold"),
            _region("r03", 25.0, 40.0, "narrative_hold"),
            _region("r04", 40.0, 51.935, "narrative_hold"),
            _region("r05", 51.935, 60.0, "settle_outro"),
        ],
        ending=MusicEnding(last_onset_seconds=58.0, behavior="decay"),
        confidence=0.7,
        meter_assumed=4,
    )


def test_adopt_aligns_slots_with_region_edges_and_skips_beyond_bar() -> None:
    document = _sample()
    planned = plan_shot_slots(document)
    by_start = {
        round(anchor.boundary_s, 3): anchor
        for anchor in planned.region_cut_anchors
        if abs(anchor.boundary_s - next(region.start for region in document.regions if region.region_id == anchor.region_id)) < 0.02
    }
    assert by_start[8.0].snapped_s == 8.74
    assert by_start[25.0].snapped_s == 24.74
    assert by_start[40.0].snapped_s == 40.74
    assert by_start[51.935].snapped_s == 52.74
    assert 15.22 in planned.downbeat_cluster_times
    assert 58.24 not in planned.downbeat_cluster_times
    assert "downbeat_cluster" in planned.warnings

    adopted = apply_boundary_snaps(document, {"r02", "r03", "r04", "r05"})
    starts = [region.start for region in adopted.regions]
    assert starts == [0.0, 8.74, 24.74, 40.74, 52.74]
    assert adopted.regions[0].end == 8.74
    assert adopted.regions[0].end_raw_s == 8.0
    assert adopted.regions[1].start_raw_s == 8.0
    for region in adopted.regions:
        slots = [slot for slot in adopted.shot_slots if slot.region_id == region.region_id]
        assert slots
        assert slots[0].start == region.start
        assert slots[-1].end == region.end
    for previous, slot in zip(adopted.shot_slots, adopted.shot_slots[1:]):
        assert abs(slot.start - previous.end) <= 0.001
    pending = [anchor for anchor in adopted.region_cut_anchors if anchor.pending and anchor.rule in {"downbeat", "beat"}]
    assert pending == []


def test_confirmed_adopt_forks_a_draft_and_leaves_the_lock_unchanged(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    save_regions_draft(paths, _sample())
    listing = confirm_regions_draft(paths)
    confirmed = load_regions_version(paths, listing.version_id)
    before = _confirmed_bytes(paths, confirmed.version_id)
    server = start_confirm_desk(paths.root, host="127.0.0.1", port=0)
    try:
        port = _port(server)
        status, page_headers, page = _request(port, f"/music?version={confirmed.version_id}")
        assert status == 200
        text = page.decode("utf-8")
        assert "text/html" in page_headers["content-type"]
        assert "orig-bound" not in text
        assert "waveform" not in text.lower()
        assert "建议 8.74s +0.74s" in text
        assert "半小节" in text
        assert "强拍" in text
        assert "15.22" in text
        assert "全部采纳" in text
        assert "秋日骑行" not in text
        assert "<select disabled>" in text

        code, payload = _post_json(
            port,
            "/api/regions-draft/adopt-boundaries",
            {
                "expected_revision": confirmed.regions_sha256,
                "version_id": confirmed.version_id,
                "boundaries": ["r02"],
            },
        )
        assert code == 200
        assert payload["version_id"] != confirmed.version_id
        assert payload["read_only"] is False
        assert _confirmed_bytes(paths, confirmed.version_id) == before
        moved = next(region for region in payload["regions"] if region["region_id"] == "r02")
        assert moved["start"] == 8.74
        slots = [slot for slot in payload["shot_slots"] if slot["region_id"] == "r02"]
        assert slots[0]["start"] == 8.74
        previous = next(region for region in payload["regions"] if region["region_id"] == "r01")
        assert previous["end"] == 8.74

        again, refused = _post_json(
            port,
            "/api/regions-draft/adopt-boundaries",
            {
                "expected_revision": confirmed.regions_sha256,
                "version_id": confirmed.version_id,
                "boundaries": "all",
            },
        )
        assert again == 409
        assert "已经有打开的草稿" in refused["error"]
        assert _confirmed_bytes(paths, confirmed.version_id) == before
    finally:
        server.shutdown()
        server.server_close()


def test_draft_adopt_updates_in_place_and_role_post_rejects_times(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    draft = save_regions_draft(paths, _sample())
    server = start_confirm_desk(paths.root, host="127.0.0.1", port=0)
    try:
        port = _port(server)
        status, _headers, page = _request(port, "/music")
        assert status == 200
        text = page.decode("utf-8")
        assert "<select disabled>" not in text
        assert "orig-bound" not in text
        assert "预留·未启用" not in text
        assert "建议 24.74s -0.26s" in text

        stale, stale_body = _post_json(
            port,
            "/api/regions-draft/adopt-boundaries",
            {"expected_revision": "0" * 64, "version_id": draft.version_id, "boundaries": "all"},
        )
        assert stale == 409
        assert "stale" in stale_body["error"]

        code, payload = _post_json(
            port,
            "/api/regions-draft/adopt-boundaries",
            {
                "expected_revision": draft.regions_sha256,
                "version_id": draft.version_id,
                "boundaries": "all",
            },
        )
        assert code == 200
        assert payload["version_id"] == draft.version_id
        starts = [region["start"] for region in payload["regions"]]
        assert starts == [0.0, 8.74, 24.74, 40.74, 52.74]
        saved = load_regions_draft(paths)
        assert saved is not None
        assert [region.start for region in saved.regions.regions] == starts

        role_rows = [
            {"region_id": region["region_id"], "edit_role": region["edit_role"], "start": 1.0}
            for region in payload["regions"]
        ]
        rejected, body = _post_json(
            port,
            "/api/regions-draft",
            {"expected_revision": payload["revision"], "regions": role_rows},
        )
        assert rejected == 400
        assert "只能修改每段的角色" in body["error"]
        assert [region.start for region in load_regions_draft(paths).regions.regions] == starts
    finally:
        server.shutdown()
        server.server_close()


def test_old_region_json_without_snap_fields_still_loads() -> None:
    payload = _sample().model_dump(mode="json")
    for region in payload["regions"]:
        region.pop("start_raw_s")
        region.pop("end_raw_s")
    payload.pop("downbeat_cluster_times")
    loaded = MusicEditRegions.model_validate(payload)
    assert loaded.downbeat_cluster_times == []
    assert loaded.regions[0].start_raw_s is None
    assert json.loads(loaded.model_dump_json())["schema_version"] == "0.1.0"


def _flip_curve(*, with_downbeats: bool) -> MusicStructure:
    """60s curve where a sub-bar window shift crosses the establish slope gate.

    Raw 3–8s slopes at -0.09, so it is unknown. The same energy read on
    2.74–8.74s slopes inside ±0.08, so the old snapped-window classifier
    called it establish and then marked the 8–25s section unknown.
    """

    values = [0.55] * 60
    values[0:3] = [0.58, 0.58, 0.58]
    values[3:6] = [0.62, 0.62, 0.62]
    values[6:8] = [0.53, 0.53]
    for index in range(8, 25):
        values[index] = 0.62
    for index in range(25, 40):
        values[index] = 0.92
    for index in range(40, 52):
        values[index] = 0.48
    for index, level in enumerate(np.linspace(0.40, 0.05, 8)):
        values[52 + index] = float(level)
    sections = [
        MusicStructureSection(start=start, end=end, role="unknown", energy=0.5, confidence=confidence)
        for start, end, confidence in (
            (0, 3, 0.8),
            (3, 8, 0.7),
            (8, 25, 0.65),
            (25, 40, 0.8),
            (40, 52, 0.7),
            (52, 60, 0.75),
        )
    ]
    beats: list[float] = []
    moment = 0.0
    while moment < 60.0 - 1e-9:
        if 8 <= moment < 25 or abs(moment / 2 - round(moment / 2)) < 1e-6:
            beats.append(round(moment, 6))
        moment += 0.5
    beats = sorted(set(beats))
    payload: dict = {
        "source_sha256": SHA,
        "duration_seconds": 60.0,
        "bpm": 120.0,
        "beats_seconds": beats,
        "downbeats_seconds": beats[::4],
        "energy_curve": [
            EnergyPoint(time_seconds=float(index), value=round(float(level), 6))
            for index, level in enumerate(values)
        ],
        "sections": sections,
        "ending": MusicEnding(last_onset_seconds=58.0, behavior="decay"),
        "confidence": 0.9,
    }
    if with_downbeats:
        grid = sorted(set([round(index * 0.5, 6) for index in range(120)] + list(USER_DOWNBEATS)))
        payload.update(
            {
                "beat_events": [
                    BeatEvent(
                        i=index,
                        t=item,
                        bar=index // 4,
                        beat_in_bar=index % 4,
                        is_downbeat=any(abs(item - down) < 1e-6 for down in USER_DOWNBEATS),
                        onset_strength=0.4,
                        energy=0.4,
                    )
                    for index, item in enumerate(grid)
                ],
                "downbeat_confidence": 0.935,
                "beat_grid": BeatGridInfo(period_s=0.5, coverage=1.0),
                "downbeats_seconds": list(USER_DOWNBEATS),
                "beat_backend": "beat_this",
                "downbeat_detector": "beat_this",
            }
        )
    return MusicStructure(**payload)


def test_sub_bar_snap_keeps_the_establish_role_on_the_long_section() -> None:
    plain = analyze_music_edit_regions(_flip_curve(with_downbeats=False))
    snapped = analyze_music_edit_regions(_flip_curve(with_downbeats=True))
    assert region_invariant_violations(plain) == []
    assert region_invariant_violations(snapped) == []

    before = [(region.edit_role, region.confidence) for region in plain.regions]
    assert [role for role, _confidence in before] == [
        "hook",
        "unknown",
        "establish",
        "peak_cut",
        "narrative_hold",
        "settle_outro",
    ]
    assert [(region.start, region.end, region.edit_role) for region in plain.regions][1:3] == [
        (3.0, 8.0, "unknown"),
        (8.0, 25.0, "establish"),
    ]
    assert plain.regions[1].confidence == 0.4
    assert plain.regions[2].confidence == 0.65

    assert [region.edit_role for region in snapped.regions] == [role for role, _confidence in before]
    short = snapped.regions[1]
    long = snapped.regions[2]
    assert (short.start, short.end, short.start_raw_s, short.end_raw_s) == (2.74, 8.74, 3.0, 8.0)
    assert short.edit_role == "unknown"
    assert short.confidence == 0.4
    assert (long.start, long.end, long.start_raw_s, long.end_raw_s) == (8.74, 24.74, 8.0, 25.0)
    assert long.edit_role == "establish"
    assert long.confidence == 0.65
    long_slots = [slot for slot in snapped.shot_slots if slot.region_id == long.region_id]
    assert long_slots
    assert all(slot.reason_code != "ROLE_UNKNOWN_BAR_GRID" for slot in long_slots)
    assert {slot.reason_code for slot in snapped.shot_slots if slot.region_id == short.region_id} == {
        "ROLE_UNKNOWN_BAR_GRID"
    }
