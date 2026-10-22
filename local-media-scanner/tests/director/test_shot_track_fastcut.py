"""Travel and event shot tracks. Narrative slots stay the previous JSON."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from director.cli import analyze_music_edit_regions_command
from director.confirm_serve import start_confirm_desk
from director.music_edit_regions_versions import (
    confirm_regions_draft,
    load_regions_version,
    save_regions_draft,
)
from director.shot_slots import DEFAULT_SHOT_STYLE, plan_shot_slots
from director.shot_track.fastcut import (
    RULES_VERSION,
    EPS,
    MIN_SLOT_S,
    FastCutConfig,
    build_grid,
    drop_contrast,
    generate,
    stats,
    validate,
)
from tests.director.test_confirm_serve import _json, _port, _post_json, _request
from tests.director.test_music_edit_regions_versions import _confirmed_bytes, _project
from tests.director.test_shot_slots import _document, _region

DESK = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "user-track-desk.json").read_text(encoding="utf-8")
)
_FASTCUT_KEYS = {
    "style",
    "pattern_role",
    "flurry_group",
    "ramp",
    "transition",
    "flash",
    "cut_on",
    "rules_version",
    "beat_length",
}


def _slots(style):
    return generate(DESK, style)[0]


def _covered_song():
    return _document(
        [
            _region("r01", 0.0, 2.0, "hook", (0.9, 0.6, 1.2)),
            _region("r03", 2.0, 8.0, "establish", (3.2, 2.5, 4.0)),
            _region("r04", 8.0, 16.0, "build", (2.0, 1.5, 2.5)),
            _region("r05", 16.0, 24.0, "peak_cut", (1.0, 0.5, 1.4)),
            _region("r06", 24.0, 32.0, "settle_outro", (3.5, 2.5, 4.0)),
        ],
        32.0,
        accent_at={0, 4, 16, 32},
    )


def test_default_style_is_travel() -> None:
    assert DEFAULT_SHOT_STYLE == "travel"
    default = inspect.signature(analyze_music_edit_regions_command).parameters["shot_style"].default
    assert getattr(default, "default", default) == "travel"
    bare = plan_shot_slots(_covered_song())
    assert bare.shot_style is None
    assert all(slot.style is None for slot in bare.shot_slots)


def test_narrative_slots_omit_fastcut_fields_and_match_each_other() -> None:
    document = _covered_song()
    first = plan_shot_slots(document)
    second = plan_shot_slots(document)
    assert first.model_dump_json() == second.model_dump_json()
    dumped = json.loads(first.model_dump_json())
    assert "shot_style" not in dumped
    assert "shot_rules_version" not in dumped
    assert dumped["shot_slots"]
    for slot in dumped["shot_slots"]:
        assert _FASTCUT_KEYS.isdisjoint(slot)
        assert slot["slot_id"].split("-")[1].startswith("s")
    explicit = plan_shot_slots(document, style="narrative")
    assert explicit.shot_style == "narrative"
    assert json.loads(explicit.model_dump_json())["shot_slots"] == dumped["shot_slots"]


def test_deterministic():
    for style in ("travel", "event"):
        assert json.dumps(_slots(style)) == json.dumps(_slots(style))
        digest = hashlib.sha256(json.dumps(_slots(style)).encode()).hexdigest()
        assert digest == hashlib.sha256(json.dumps(generate(DESK, style)[0]).encode()).hexdigest()


def test_cover_and_contiguous():
    for style in ("travel", "event"):
        rows = _slots(style)
        assert rows[0]["start"] == 0 and abs(rows[-1]["end"] - DESK["duration_seconds"]) < 1e-3
        assert all(abs(a["end"] - b["start"]) < 1e-9 for a, b in zip(rows, rows[1:]))


def test_cuts_on_grid():
    grid = [t for t, _ in build_grid(DESK["beats_seconds"])] + [region["start"] for region in DESK["regions"]]
    for style in ("travel", "event"):
        for row in _slots(style):
            assert any(abs(row["start"] - moment) <= 0.02 for moment in grid), row["slot_id"]


def test_invariants():
    beat_s = 0.5
    for style in ("travel", "event"):
        assert validate(_slots(style), DESK, beat_s) == [], style


def test_region_edges_respected():
    for style in ("travel", "event"):
        rows = _slots(style)
        for region in DESK["regions"]:
            assert any(abs(row["start"] - region["start"]) < 1e-6 for row in rows)


def test_density_ordering():
    for style in ("travel", "event"):
        summary = stats(_slots(style), DESK, 0.5)
        assert summary["r05"]["cuts_per_bar"] > summary["r03"]["cuts_per_bar"] > summary["r06"]["cuts_per_bar"]
    travel, event = (stats(_slots(style), DESK, 0.5) for style in ("travel", "event"))
    assert all(event[region]["count"] >= travel[region]["count"] for region in travel)


def test_unknown_only_placeholder():
    for style in ("travel", "event"):
        assert {row["shot_type"] for row in _slots(style) if row["region_role"] == "unknown"} == {"?"}


def test_peak_starts_with_flash_hit_on_downbeat():
    for style in ("travel", "event"):
        first = next(row for row in _slots(style) if row["region_role"] == "peak_cut")
        assert first["pattern_role"] == "hit" and first["flash"] and first["cut_on"] in ("downbeat", "accent")


def test_tempo_guard_fast_song():
    fast = json.loads(json.dumps(DESK))
    scale = 0.75
    for key in ("beats_seconds", "downbeats_seconds"):
        fast[key] = [moment * scale for moment in fast[key]]
    for region in fast["regions"]:
        region["start"] *= scale
        region["end"] *= scale
    fast["duration_seconds"] *= scale
    fast["phrases"] = [dict(phrase, start=phrase["start"] * scale, end=phrase["end"] * scale) for phrase in fast["phrases"]]
    for style in ("travel", "event"):
        rows = generate(fast, style)[0]
        assert min(row["length_s"] for row in rows) >= MIN_SLOT_S - 0.02


def test_build_to_drop_contrast():
    for style in ("travel", "event"):
        contrast = drop_contrast(stats(_slots(style), DESK, 0.5))
        assert contrast["peak_vs_build_cuts_per_bar"] >= 1.25, (style, contrast)
        assert contrast["drop_vs_pre_drop"] >= 2.0, (style, contrast)
        assert contrast["build_second_half_mean"] > contrast["build_first_half_mean"], (style, contrast)


def test_drop_then_release_hold():
    for style, minimum in (("travel", 4.0), ("event", 2.0)):
        peak = [row for row in _slots(style) if row["region_role"] == "peak_cut"]
        bar_s = 4 * 0.5
        first_bar = [row for row in peak if row["start"] < peak[0]["start"] + bar_s - EPS]
        assert sum(1 for row in first_bar if row["pattern_role"] == "flurry") == 4, style
        hold = peak[len(first_bar)]
        assert hold["pattern_role"] == "hero" and hold["beats"] >= minimum and hold["ramp"] in ("slow", "freeze"), (style, hold)


def test_pre_drop_lift():
    for style in ("travel", "event"):
        rows = _slots(style)
        index = next(position for position, row in enumerate(rows) if row["region_role"] == "peak_cut")
        assert any(row["pattern_role"] == "lift" for row in rows[index - 3:index]), style


def test_user_track_counts_and_event_establish_is_less_dense_than_build():
    travel = stats(_slots("travel"), DESK, 0.5)
    event = stats(_slots("event"), DESK, 0.5)
    assert {key: travel[key]["count"] for key in travel} == {
        "r01": 6, "r02": 5, "r03": 22, "r04": 20, "r05": 23, "r06": 5,
    }
    assert {key: event[key]["count"] for key in event} == {
        "r01": 7, "r02": 8, "r03": 26, "r04": 29, "r05": 29, "r06": 6,
    }
    assert event["r03"]["cuts_per_bar"] < event["r04"]["cuts_per_bar"]
    assert travel["r03"]["cuts_per_bar"] == 2.75
    assert event["r03"]["flurry_slots"] < 14
    assert _slots("travel")[0]["rules_version"] == RULES_VERSION == "fastcut-0.3"


def test_short_build_keeps_dense_step_and_short_peak_skips_release():
    def desk(role: str, seconds: float) -> dict:
        beats = [round(index * 0.5, 3) for index in range(int(seconds / 0.5) + 1) if index * 0.5 <= seconds]
        return {
            "beats_seconds": beats,
            "downbeats_seconds": [moment for moment in beats if abs(moment % 2) < 1e-6],
            "phrases": [],
            "regions": [{"region_id": "r1", "start": 0.0, "end": seconds, "edit_role": role}],
            "duration_seconds": seconds,
            "shot_slots": [],
        }

    one_bar = generate(desk("build", 2.0), "travel")[0]
    assert any(row["pattern_role"] == "flurry" for row in one_bar)
    assert not any(row["pattern_role"] == "lift" for row in one_bar)
    two_bars = generate(desk("build", 4.0), "travel")[0]
    assert any(row["pattern_role"] == "flurry" and row["start"] < 2 for row in two_bars)
    assert any(row["pattern_role"] == "lift" and row["start"] >= 2 - EPS for row in two_bars)
    peak = generate(desk("peak_cut", 4.0), "travel")[0]
    assert not any(
        row["pattern_role"] == "hero" and row["ramp"] == "slow" and row["beats"] >= 4
        for row in peak
    )
    assert any(row["pattern_role"] == "breath" for row in peak)


def test_lead_frames_default_zero_and_optional_shift():
    assert FastCutConfig().lead_frames == 0
    plain = _slots("travel")
    shifted = generate(DESK, "travel", config=FastCutConfig(lead_frames=2))[0]
    assert [row["start"] for row in plain] != [row["start"] for row in shifted]
    flurry = next(
        row for row in plain if row["pattern_role"] == "flurry" and row["region_role"] == "peak_cut"
    )
    moved = next(row for row in shifted if row["slot_id"] == flurry["slot_id"])
    assert flurry["start"] - moved["start"] == pytest.approx(2 / 30, abs=0.002)
    assert validate(shifted, DESK, 0.5) == [] or all(
        "too_short" not in item and "gap" not in item for item in validate(shifted, DESK, 0.5)
    )


def test_mapped_fastcut_slots_share_region_edges(tmp_path: Path) -> None:
    document = _covered_song()
    travel = plan_shot_slots(document, style="travel")
    assert travel.shot_style == "travel"
    assert travel.shot_rules_version == RULES_VERSION
    assert travel.regions[0].start == document.regions[0].start
    for region in travel.regions:
        rows = [slot for slot in travel.shot_slots if slot.region_id == region.region_id]
        assert rows
        assert abs(rows[0].start - region.start) <= 0.001
        assert abs(rows[-1].end - region.end) <= 0.001
        assert region.cut_summary_zh.startswith("旅拍快剪")
    event = plan_shot_slots(document, style="event")
    assert "活动快剪" in event.regions[1].cut_summary_zh
    assert "落点" in __import__("director.shot_slots", fromlist=["drop_contrast_zh"]).drop_contrast_zh(event)

    paths = _project(tmp_path)
    draft = save_regions_draft(paths, plan_shot_slots(document))
    server = start_confirm_desk(paths.root, host="127.0.0.1", port=0)
    try:
        port = _port(server)
        code, switched = _post_json(
            port,
            "/api/regions-draft/shot-style",
            {"expected_revision": draft.regions_sha256, "version_id": draft.version_id, "style": "travel"},
        )
        assert code == 200, switched
        assert switched["shot_style"] == "travel"
        assert switched["read_only"] is False
        assert "落点" in switched["drop_contrast_zh"]
        assert any(slot.get("flash") for slot in switched["shot_slots"])
        status, _headers, page = _request(port, f"/music?version={switched['version_id']}&t=16")
        text = page.decode("utf-8")
        assert status == 200
        assert 'id="shot-style"' in text
        assert "旅拍快剪" in text
        assert 'id="mark-legend"' in text
        assert "闪白" in text
        assert "快闪组" in text
        assert "<select disabled>" not in text
        refused, body = _post_json(
            port,
            "/api/regions-draft",
            {
                "expected_revision": switched["revision"],
                "regions": [{"region_id": region["region_id"], "edit_role": region["edit_role"], "style": "event"} for region in switched["regions"]],
            },
        )
        assert refused == 400, body
        assert "角色" in body["error"]
        code, locked = _post_json(
            port,
            "/api/regions-draft/confirm",
            {"expected_revision": switched["revision"], "force": False, "reason": ""},
        )
        assert code == 200, locked
        confirmed = load_regions_version(paths, locked["version_id"])
        before = _confirmed_bytes(paths, confirmed.version_id)
        assert confirmed.regions.shot_style == "travel"
        code, forked = _post_json(
            port,
            "/api/regions-draft/shot-style",
            {
                "expected_revision": confirmed.regions_sha256,
                "version_id": confirmed.version_id,
                "style": "event",
            },
        )
        assert code == 200, forked
        assert forked["shot_style"] == "event"
        assert forked["status"] == "draft"
        assert _confirmed_bytes(paths, confirmed.version_id) == before
        stale, _stale_body = _post_json(
            port,
            "/api/regions-draft/shot-style",
            {"expected_revision": "0" * 64, "version_id": forked["version_id"], "style": "narrative"},
        )
        assert stale == 409
    finally:
        server.shutdown()
        server.server_close()


def test_confirmed_style_switch_is_blocked_while_a_draft_is_open(tmp_path: Path) -> None:
    document = plan_shot_slots(_covered_song(), style="travel")
    paths = _project(tmp_path)
    save_regions_draft(paths, document)
    listing = confirm_regions_draft(paths)
    confirmed = load_regions_version(paths, listing.version_id)
    save_regions_draft(paths, document)
    server = start_confirm_desk(paths.root, host="127.0.0.1", port=0)
    try:
        port = _port(server)
        code, blocked = _post_json(
            port,
            "/api/regions-draft/shot-style",
            {
                "expected_revision": confirmed.regions_sha256,
                "version_id": confirmed.version_id,
                "style": "event",
            },
        )
        assert code == 409
        assert "草稿" in blocked["error"]
        status, _headers, page = _request(port, f"/music?version={listing.version_id}")
        text = page.decode("utf-8")
        assert status == 200
        assert "<select disabled>" in text
        assert 'id="shot-style"' in text
        assert "selected>旅拍快剪" in text or 'value="travel" selected' in text
    finally:
        server.shutdown()
        server.server_close()
