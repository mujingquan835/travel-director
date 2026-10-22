"""Travel and event shot tracks. Narrative slots stay the previous JSON."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import subprocess
from pathlib import Path
from typing import get_args

import pytest

from director.cli import analyze_music_edit_regions_command
from director.confirm_serve import start_confirm_desk
from director.music_edit_regions_schema import GuideTransition, MotionKind, ShotSize, SoundCue, StoryBeat
from director.music_timeline import _shot_box_style, render_timeline_page
from director.music_edit_regions_versions import (
    confirm_regions_draft,
    load_regions_version,
    save_regions_draft,
)
from director.shot_slots import DEFAULT_SHOT_STYLE, plan_shot_slots
from director.shot_track.creator_guidance import creator_guidance, timing_hash, validate_guidance
from director.shot_track.fastcut import (
    RULES_VERSION,
    EPS,
    MIN_SLOT_S,
    SHOT_CYCLES,
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
    assert _slots("travel")[0]["rules_version"] == RULES_VERSION == "fastcut-0.4"


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
        assert region.cut_summary_zh
        assert "刀" not in region.cut_summary_zh
        assert region.cut_stats_zh.startswith("旅拍快剪")
    event = plan_shot_slots(document, style="event")
    assert "活动快剪" in event.regions[1].cut_stats_zh
    assert event.regions[1].cut_summary_zh
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


_BOX_RE = re.compile(
    r'<div class="(?P<class>[^"]*)" data-slot-id="(?P<id>[^"]+)" '
    r'data-region-id="(?P<region>[^"]+)"'
    r'(?: data-flurry-group="(?P<group>[^"]*)")? '
    r'data-start="(?P<start>[0-9.]+)" data-end="(?P<end>[0-9.]+)" '
    r'style="(?P<style>[^"]*)" title="(?P<title>[^"]*)">(?P<body>.*?)</div>'
)
_RUN_RE = re.compile(
    r'<div class="flurry-run" data-flurry-group="(?P<group>[^"]+)" '
    r'style="left:(?P<left>-?\d+\.\d+)%;width:(?P<width>-?\d+\.\d+)%">'
)


def _milli(text: str) -> int:
    sign = -1 if text.startswith("-") else 1
    body = text[1:] if sign < 0 else text
    whole, frac = body.split(".")
    return sign * (int(whole) * 1000 + int(frac.ljust(3, "0")[:3]))


def _box_millis(style: str) -> tuple[int, int]:
    match = re.search(r"left:(-?\d+\.\d+)%;width:calc\((-?\d+\.\d+)% \+ 1px\)", style)
    assert match, style
    return _milli(match.group(1)), _milli(match.group(2))


def test_rendered_slot_geometry_has_no_horizontal_gaps() -> None:
    """Shot blocks use the time edges. Chrome does not paint a gap between them."""

    tiny = _shot_box_style(0.0, 0.05, 0.0, 60.0)
    assert tiny == "left:0.000%;width:calc(0.083% + 1px)"
    slots, _beat_s = generate(DESK, "travel")
    view = {
        "regions": DESK["regions"],
        "duration_seconds": DESK["duration_seconds"],
        "bpm": DESK["bpm"],
        "confidence": 0.8,
        "provider": "beat_this+heuristic",
        "schema_version": "0.1.0",
        "status": "draft",
        "read_only": False,
        "acceptance": {"ok": False, "unknown_region_ids": ["r02"]},
        "versions": [],
        "version_id": "regions-v01",
        "warnings": [],
        "beats_seconds": DESK["beats_seconds"],
        "downbeats_seconds": DESK["downbeats_seconds"],
        "phrases": DESK["phrases"],
        "shot_slots": slots,
        "shot_style": "travel",
        "shot_rules_version": RULES_VERSION,
        "region_cut_anchors": [],
    }
    page = render_timeline_page(
        project_title="示例数据",
        project_id="sample",
        project_path="/tmp/sample",
        track_label="示例",
        view=view,
        message="",
        selected="r05",
        playhead="40.74",
        kind_labels={
            "hook": "可卡点",
            "unknown": "未定",
            "establish": "叙事/铺陈",
            "build": "推进",
            "peak_cut": "高潮",
            "settle_outro": "收束",
        },
        snap_labels={"downbeat": "强拍", "beat": "拍", "free": "自由"},
        warning_labels={},
    )
    assert "margin:0;padding:0;border:0;border-radius:0;min-width:1px" in page
    assert "cutedge" not in page
    shots = page.split('id="shots"', 1)[1].split('id="track-how"', 1)[0]
    overview = list(_BOX_RE.finditer(shots))
    assert len(overview) == len(slots)
    previous = None
    short_hidden = 0
    wide_labeled = 0
    for box in overview:
        left, width = _box_millis(box.group("style"))
        if previous is not None:
            assert left == previous, (box.group("id"), previous, left)
        previous = left + width
        assert "0.200%" not in box.group("style")
        duration = float(box.group("end")) - float(box.group("start"))
        if duration < 0.3:
            assert "<b>" not in box.group("body")
            assert box.group("title")
            short_hidden += 1
        if duration >= 1.2:
            assert "<b>" in box.group("body")
            wide_labeled += 1
    assert short_hidden >= 20
    assert wide_labeled >= 1
    groups: dict[str, list[re.Match[str]]] = {}
    for box in overview:
        if box.group("group"):
            groups.setdefault(box.group("group"), []).append(box)
    runs = list(_RUN_RE.finditer(shots))
    assert runs and len(runs) == len(groups)
    for run in runs:
        members = groups[run.group("group")]
        assert len(members) >= 2
        first_left, _first_width = _box_millis(members[0].group("style"))
        last_left, last_width = _box_millis(members[-1].group("style"))
        assert _milli(run.group("left")) == first_left
        assert _milli(run.group("left")) + _milli(run.group("width")) == last_left + last_width
        for member in members[1:]:
            assert "hair" in member.group("class").split()
    detail = page.split('id="zoom-lane"', 1)[1].split('class="zph"', 1)[0]
    zoomed = list(_BOX_RE.finditer(detail))
    assert len(zoomed) >= 2
    previous = None
    detail_label = False
    for box in zoomed:
        left, width = _box_millis(box.group("style"))
        if previous is not None:
            assert left == previous, (box.group("id"), previous, left)
        previous = left + width
        duration = float(box.group("end")) - float(box.group("start"))
        if duration < 0.3 and "<b>" in box.group("body"):
            detail_label = True
    assert detail_label
    script = page[page.index("function fmtMilli"): page.index("function renderDetail")]
    program = script + """
var slots = [{start:0,end:0.24},{start:0.24,end:0.5},{start:0.5,end:2}];
var prev = null;
function milli(text) {
  var sign = text[0] === "-" ? -1 : 1;
  var body = sign < 0 ? text.slice(1) : text;
  var parts = body.split(".");
  return sign * (Number(parts[0]) * 1000 + Number(parts[1]));
}
for (var i = 0; i < slots.length; i++) {
  var style = shotBoxStyle(slots[i].start, slots[i].end, 0, 60);
  var match = style.match(/left:(-?\\d+\\.\\d+)%;width:calc\\((-?\\d+\\.\\d+)% \\+ 1px\\)/);
  if (!match) throw new Error(style);
  var left = milli(match[1]);
  var width = milli(match[2]);
  if (prev !== null && prev !== left) throw new Error("gap " + prev + " vs " + left);
  prev = left + width;
}
var tiny = shotBoxStyle(0, 0.05, 0, 60);
if (tiny.indexOf("0.200") !== -1) throw new Error(tiny);
if (tiny !== "left:0.000%;width:calc(0.083% + 1px)") throw new Error(tiny);
"""
    completed = subprocess.run(["node", "-e", program], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="/usr/local/bin/google-chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        tab = browser.new_page(viewport={"width": 1440, "height": 900})
        tab.route("**/vendor/**", lambda route: route.abort())
        tab.set_content(page, wait_until="domcontentloaded")
        report = tab.evaluate(
            """() => {
              renderDetail(40.74);
              function paintGaps(selector, timebox) {
                const nodes = [...document.querySelectorAll(selector)];
                const bad = [];
                const chrome = [];
                for (let i = 0; i < nodes.length; i++) {
                  const node = nodes[i];
                  const rect = node.getBoundingClientRect();
                  const style = getComputedStyle(node);
                  const horizontal = ["marginLeft", "marginRight", "paddingLeft", "paddingRight", "borderLeftWidth", "borderRightWidth"];
                  horizontal.forEach(function (name) {
                    if (parseFloat(style[name]) > 0) chrome.push(node.getAttribute("data-slot-id") + " " + name);
                  });
                  if (parseFloat(style.borderTopLeftRadius) > 0) chrome.push("radius");
                  if (i === 0) continue;
                  const prev = nodes[i - 1].getBoundingClientRect();
                  const gap = rect.left - prev.right;
                  if (gap > 0.6 || gap < -2.5) bad.push({id: node.getAttribute("data-slot-id"), gap: gap});
                  const start = Number(node.getAttribute("data-start"));
                  const expected = timebox.left + (start - timebox.origin) / timebox.span * timebox.width;
                  if (Math.abs(rect.left - expected) > 1.5) bad.push({id: node.getAttribute("data-slot-id"), shift: rect.left - expected});
                }
                return {n: nodes.length, bad: bad, chrome: chrome};
              }
              const lane = document.querySelector("#shots").getBoundingClientRect();
              const duration = Number(state.duration_seconds);
              const shots = paintGaps("#shots > .sl", {left: lane.left, origin: 0, span: duration, width: lane.width});
              const row = document.querySelector("#zoom-lane .zrow").getBoundingClientRect();
              const origin = Number(document.querySelector("#zoom-lane").getAttribute("data-origin"));
              const limit = Number(document.querySelector("#zoom-lane").getAttribute("data-limit"));
              const detail = paintGaps("#zoom-lane .zshot", {left: row.left, origin: origin, span: limit - origin, width: row.width});
              return {shots: shots, detail: detail};
            }"""
        )
        browser.close()
    assert report["shots"]["n"] == len(slots)
    assert report["shots"]["bad"] == []
    assert report["shots"]["chrome"] == []
    assert report["detail"]["n"] >= 2
    assert report["detail"]["bad"] == []
    assert report["detail"]["chrome"] == []


_GUIDE_KEYS = {
    "shot_size",
    "motion",
    "transition_in",
    "transition_out",
    "sound_cue",
    "sound_cues",
    "story_beat",
    "content_hint",
    "reserve_best",
    "seam_zh",
}
_SHOT_SIZES = set(get_args(ShotSize))
_MOTIONS = set(get_args(MotionKind))
_GUIDE_TRANSITIONS = set(get_args(GuideTransition))
_SOUNDS = set(get_args(SoundCue))
_STORIES = set(get_args(StoryBeat))
_PAIRED = {"whip", "match", "zoom"}


def _time_rows(document):
    return [(slot.slot_id, slot.start, slot.end) for slot in document.shot_slots]


def _without_guidance(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in _GUIDE_KEYS}


def test_guidance_keeps_times_and_narrative_fields(monkeypatch) -> None:
    import director.shot_slots as slots_mod

    song = _covered_song()
    monkeypatch.setattr(slots_mod, "attach_guidance", lambda document: document)
    before = {style: plan_shot_slots(song, style=style) for style in ("narrative", "travel", "event")}
    monkeypatch.undo()
    for style, earlier in before.items():
        later = plan_shot_slots(song, style=style)
        assert hashlib.sha256(json.dumps(_time_rows(earlier)).encode()).hexdigest() == hashlib.sha256(
            json.dumps(_time_rows(later)).encode()
        ).hexdigest()
        assert _time_rows(earlier) == _time_rows(later)
        for left, right in zip(earlier.shot_slots, later.shot_slots, strict=True):
            assert left.model_dump(mode="json") == _without_guidance(right.model_dump(mode="json"))
            assert (left.start, left.end, left.beats, left.shot_type, left.transition, left.reason_code) == (
                right.start,
                right.end,
                right.beats,
                right.shot_type,
                right.transition,
                right.reason_code,
            )
            assert right.story_beat in _STORIES
            assert right.content_hint
            if right.shot_type == "?":
                assert right.story_beat == "待定"
                assert right.shot_size is None
            else:
                assert right.shot_size in _SHOT_SIZES
                assert right.motion in _MOTIONS
            if right.transition_in is not None:
                assert right.transition_in in _GUIDE_TRANSITIONS
            if right.transition_out is not None:
                assert right.transition_out in _GUIDE_TRANSITIONS
            if right.sound_cue is not None:
                assert right.sound_cue in _SOUNDS
                assert right.sound_cue in right.sound_cues
            for cue in right.sound_cues:
                assert cue in _SOUNDS
        slots = later.shot_slots
        for left, right in zip(slots, slots[1:]):
            if left.transition_out in _PAIRED or right.transition_in in _PAIRED:
                assert left.transition_out == right.transition_in
            if right.transition_in == "mask_optional":
                assert left.transition_out in (None, "cut")
            if left.transition_out == "end":
                assert right.transition_in in (None, "cut")


def test_travel_establish_rotation_changes_type_order_only() -> None:
    assert SHOT_CYCLES["travel"]["base"]["establish"] == ["动", "细", "脸"]
    assert SHOT_CYCLES["event"]["base"]["establish"] == ["动", "脸", "细"]
    current = _slots("travel")
    saved = list(SHOT_CYCLES["travel"]["base"]["establish"])
    SHOT_CYCLES["travel"]["base"]["establish"] = ["细", "脸", "动"]
    try:
        previous = generate(DESK, "travel")[0]
    finally:
        SHOT_CYCLES["travel"]["base"]["establish"] = saved
    assert [(row["start"], row["end"], row["beats"], row["pattern_role"], row["cut_on"]) for row in current] == [
        (row["start"], row["end"], row["beats"], row["pattern_role"], row["cut_on"]) for row in previous
    ]
    now = [row["shot_type"] for row in current if row["region_role"] == "establish" and row["pattern_role"] == "base"]
    old = [row["shot_type"] for row in previous if row["region_role"] == "establish" and row["pattern_role"] == "base"]
    assert now and now != old
    assert now[0] == "动"


def test_creator_rules_keep_the_user_track_times() -> None:
    for style in ("travel", "event"):
        raw = _slots(style)
        guided = creator_guidance(raw, DESK, style)
        assert timing_hash(raw) == timing_hash(guided)
        assert validate_guidance(guided) == []
        for left, right in zip(raw, guided, strict=True):
            assert (left["start"], left["end"], left["shot_type"], left["transition"]) == (
                right["start"],
                right["end"],
                right["shot_type"],
                right["transition"],
            )
            assert right["story_beat"] in _STORIES
            assert right["content_hint"]
            if right["shot_type"] != "?":
                assert right["shot_size"] in _SHOT_SIZES
                assert right["motion"] in _MOTIONS
    travel = creator_guidance(_slots("travel"), DESK, "travel")
    whips = [(left, right) for left, right in zip(travel, travel[1:]) if right["transition_in"] == "whip"]
    assert whips
    for left, right in whips:
        assert left["transition_out"] == "whip"
        assert "嗖声" in right["sound_cues"]
    hit = next(row for row in travel if row["pattern_role"] == "hit")
    assert hit["_reserve_best"] is True
    assert hit["story_beat"] == "高潮"
    assert {"重击", "嗖声"} <= set(hit["sound_cues"])
    lift = next(row for row in travel if row["pattern_role"] == "lift")
    assert "上升音" in lift["sound_cues"]
    hold = next(row for row in travel[travel.index(hit) + 1 :] if row["pattern_role"] == "hero")
    assert hold["story_beat"] == "高潮"
    assert hold["shot_size"] == "全"
    establish = [row for row in travel if row["region_role"] == "establish"]
    assert establish[0]["shot_size"] == "全" and establish[0]["_title"] is True
    assert establish[1]["shot_size"] == "中"
    assert sum(1 for row in travel if row["_title"]) == 1
    direction = None
    for row in travel:
        motion = row["motion"]
        if motion in ("→", "←"):
            assert direction in (None, motion)
            direction = motion
        if row["pattern_role"] in ("hero", "breath", "final") and float(row["beats"]) >= 2:
            direction = None


def test_guide_toggle_is_collapsed_by_default() -> None:
    document = plan_shot_slots(_covered_song(), style="travel")
    view = document.model_dump(mode="json")
    view.update(
        {
            "status": "draft",
            "read_only": False,
            "has_draft": False,
            "acceptance": {"ok": True, "unknown_region_ids": []},
            "versions": [],
            "version_id": "regions-v01",
            "warnings": [],
            "region_cut_anchors": [],
        }
    )
    page = render_timeline_page(
        project_title="示例数据",
        project_id="sample",
        project_path="/tmp/sample",
        track_label="示例",
        view=view,
        message="",
        selected=None,
        playhead="0",
        kind_labels={"hook": "钩子", "establish": "铺陈", "build": "推进", "peak_cut": "高潮", "settle_outro": "收束"},
        snap_labels={"downbeat": "强拍"},
        warning_labels={},
    )
    assert 'id="guide-toggle"' in page
    assert "展开剪辑思路" in page
    assert 'id="guide-rows" hidden' in page
    assert 'id="cut-click"' in page
    assert 'id="cut-click" checked' not in page
    assert "刀口嗒嗒声" in page
    assert "★" in page
    assert any(slot.seam_zh for slot in document.shot_slots)
    for row_id in ("guide-size", "guide-transition", "guide-sound", "guide-story"):
        assert f'id="{row_id}"' in page
    hint = next(slot.content_hint for slot in document.shot_slots if slot.content_hint)
    assert hint in page


def _slot_blob(regions) -> bytes:
    payload = [slot.model_dump(mode="json") for slot in regions.shot_slots]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def test_confirmed_shot_track_bytes_stay_put_when_rules_change(tmp_path, monkeypatch) -> None:
    """Changing a rule parameter must not rewrite a confirmed shot track."""

    from director.confirm_serve import _desk_view
    from director.shot_slots import NEW_RULES_NOTICE
    from director.shot_track import fastcut

    document = plan_shot_slots(_covered_song(), style="travel")
    paths = _project(tmp_path)
    save_regions_draft(paths, document)
    listing = confirm_regions_draft(paths)
    confirmed = load_regions_version(paths, listing.version_id)
    before = _confirmed_bytes(paths, listing.version_id)
    frozen_slots = _slot_blob(confirmed.regions)
    assert confirmed.regions.shot_track_locked is True
    assert b'"shot_track_locked":true' in before or b'"shot_track_locked": true' in before

    monkeypatch.setitem(fastcut.SHOT_CYCLES["travel"]["base"], "establish", ["脸"])
    reloaded = load_regions_version(paths, listing.version_id)
    assert _confirmed_bytes(paths, listing.version_id) == before
    assert _slot_blob(reloaded.regions) == frozen_slots
    view = _desk_view(paths, reloaded)
    assert _slot_blob_from_view(view) == frozen_slots
    assert view["snapshot_notice"] == ""

    save_regions_draft(paths, document)
    draft_view = _desk_view(paths, load_regions_version(paths, "regions-v02"))
    assert draft_view["status"] == "draft"
    assert _slot_blob_from_view(draft_view) != frozen_slots
    assert _confirmed_bytes(paths, listing.version_id) == before

    monkeypatch.setattr(fastcut, "RULES_VERSION", "fastcut-9.9")
    drifted = _desk_view(paths, load_regions_version(paths, listing.version_id))
    assert drifted["snapshot_notice"] == NEW_RULES_NOTICE
    assert drifted["shot_rules_version"] == RULES_VERSION
    assert _slot_blob_from_view(drifted) == frozen_slots
    assert _confirmed_bytes(paths, listing.version_id) == before


def _slot_blob_from_view(view: dict) -> bytes:
    return json.dumps(view["shot_slots"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def test_old_confirmed_without_snapshot_prompts_and_migrates(tmp_path, monkeypatch) -> None:
    from director.confirm_serve import render_music_page
    from director.music_edit_regions_versions import migrate_unlocked_confirmed_regions
    from director.shot_slots import MISSING_SNAPSHOT_NOTICE, plan_shot_slots as real_plan
    import director.shot_slots as shot_slots

    document = plan_shot_slots(_covered_song(), style="travel")
    paths = _project(tmp_path)
    real_freeze = shot_slots.freeze_shot_track
    monkeypatch.setattr(shot_slots, "freeze_shot_track", lambda regions, **_kwargs: regions)
    save_regions_draft(paths, document)
    listing = confirm_regions_draft(paths)
    before = _confirmed_bytes(paths, listing.version_id)
    assert b"shot_track_locked" not in before
    monkeypatch.setattr(shot_slots, "freeze_shot_track", real_freeze)

    def explode(regions, style=None):
        raise AssertionError("a confirmed version without a snapshot must not be replanned")

    monkeypatch.setattr(shot_slots, "plan_shot_slots", explode)
    page = render_music_page(paths.root, version_id=listing.version_id)
    assert MISSING_SNAPSHOT_NOTICE in page
    assert 'id="snapshot-notice"' in page
    assert _confirmed_bytes(paths, listing.version_id) == before

    monkeypatch.setattr(shot_slots, "plan_shot_slots", real_plan)
    migrated = migrate_unlocked_confirmed_regions(paths, listing.version_id)
    assert migrated.status == "draft"
    assert migrated.regions.shot_track_locked is False
    assert migrated.regions.shot_slots
    assert migrated.regions.shot_style == "travel"
    assert _confirmed_bytes(paths, listing.version_id) == before
    assert b"shot_track_locked" not in before


def _silent_wav(path: Path, seconds: float, rate: int = 8000) -> None:
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(seconds * rate))


def _freeze_music(paths, seconds: float) -> None:
    import hashlib

    from director.audio_import import ImportedMusicAsset
    from director.project import record_supporting_artifact

    relative = Path("generation") / "assets" / "music-export.wav"
    target = paths.root / relative
    _silent_wav(target, seconds)
    payload = target.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    asset = ImportedMusicAsset(
        original_absolute_path=str(target.resolve()),
        frozen_relative_path=relative.as_posix(),
        source_sha256=digest,
        size_bytes=len(payload),
        duration_seconds=seconds,
        sample_rate=8000,
        channels=1,
        mime_type="audio/wav",
    )
    record_supporting_artifact(paths, paths.generated_music, asset, state_key="music_asset")


def _fcpx_seconds(value: str) -> float:
    text = value.removesuffix("s")
    if "/" in text:
        num, den = text.split("/", 1)
        return int(num) / int(den)
    return float(text)


def test_export_fcpxml_uses_the_confirmed_snapshot_only(tmp_path, monkeypatch) -> None:
    import xml.etree.ElementTree as ET
    from urllib.parse import unquote, urlparse

    from director.confirm_serve import render_music_page
    from director.music_edit_regions_versions import (
        RegionsConfirmGateError,
        export_fcpxml_for_confirmed_regions,
    )
    from director.regions_fcpxml import EXPORT_FPS, frame_index
    import director.shot_slots as shot_slots

    draft_only = _project(tmp_path / "draft")
    save_regions_draft(draft_only, plan_shot_slots(_covered_song(), style="travel"))
    with pytest.raises(RegionsConfirmGateError):
        export_fcpxml_for_confirmed_regions(draft_only, "regions-v01", tmp_path / "nope")
    assert not (tmp_path / "nope").exists()

    document = plan_shot_slots(_covered_song(), style="travel")
    paths = _project(tmp_path / "locked")
    save_regions_draft(paths, document)
    listing = confirm_regions_draft(paths)
    before = _confirmed_bytes(paths, listing.version_id)
    _freeze_music(paths, document.duration_seconds)
    page = render_music_page(paths.root, version_id=listing.version_id)
    assert 'id="export-fcpxml"' in page
    assert 'id="export-fcpxml" disabled' not in page
    assert "导出按已确认的分区边界" not in page
    assert "还没在这台机器上验证" in page
    assert "30fps" in page
    assert "正在生成占位" in page
    assert "顶部角标" in page

    result = export_fcpxml_for_confirmed_regions(paths, listing.version_id, tmp_path / "package")
    root = ET.parse(result.fcpxml_path).getroot()
    assert root.tag == "fcpxml"
    assert root.findall(".//gap") == []
    stored = load_regions_version(paths, listing.version_id).regions
    spine = root.find(".//spine")
    assert spine is not None
    clips = [node for node in list(spine) if node.tag == "asset-clip"]
    assert len(clips) == len(stored.shot_slots)
    fmt = root.find(".//format")
    assert fmt is not None
    assert fmt.attrib["width"] == "1080"
    assert fmt.attrib["height"] == "1920"
    half = 0.5 / EXPORT_FPS
    cursor = None
    for clip, slot in zip(clips, stored.shot_slots):
        start = _fcpx_seconds(clip.attrib["offset"])
        duration = _fcpx_seconds(clip.attrib["duration"])
        if cursor is None:
            cursor = start
        assert abs(start - cursor) < 1e-6
        cursor += duration
        assert abs(start - slot.start) <= half + 1e-9
        assert abs(start + duration - slot.end) <= half + 1e-9
        assert slot.slot_id in clip.attrib["name"]
        if slot.technique_name_zh:
            assert slot.technique_name_zh in clip.attrib["name"]
        assert clip.attrib.get("lane") is None
        expected = frame_index(slot.end) - frame_index(slot.start)
        assert _video_frames(_src_path(clip, root)) == max(1, expected)
    assert all(node.attrib.get("lane") != "1" for node in root.findall(".//asset-clip"))
    music = clips[0].find("asset-clip")
    assert music is not None and music.attrib["lane"] == "-1" and music.attrib["audioRole"] == "music"
    assert abs(_fcpx_seconds(music.attrib["duration"]) - stored.duration_seconds) <= 1 / EXPORT_FPS
    assert all(node.find("asset-clip") is None for node in clips[1:])
    for asset in root.findall(".//asset"):
        assert Path(unquote(urlparse(asset.attrib["src"]).path)).is_file()
    marker_values = [node.attrib["value"] for node in root.findall(".//marker")]
    for region in stored.regions:
        assert any(region.region_id in value and value.startswith("分区") for value in marker_values)
    assert any(value.startswith("落点") for value in marker_values)
    assert stored.technique_uses
    for use in stored.technique_uses:
        assert any(value.startswith("手法") and use.name_zh in value for value in marker_values)
    sheet = result.sheet_path.read_text(encoding="utf-8")
    for use in stored.technique_uses:
        assert use.name_zh in sheet
    assert "| 序号 | 起点 | 终点 | 景别 | 转场 | 声音 | 画面建议 |" in sheet
    assert "00:" in sheet
    assert "还没在这台机器上验证" in sheet
    assert "30fps" in sheet
    assert "顶部角标" in sheet
    assert _confirmed_bytes(paths, listing.version_id) == before

    def explode(regions, style=None):
        raise AssertionError("export must not replan")

    monkeypatch.setattr(shot_slots, "plan_shot_slots", explode)
    monkeypatch.setitem(shot_slots_cycles(), "establish", ["脸"])
    again = export_fcpxml_for_confirmed_regions(paths, listing.version_id, tmp_path / "package")
    again_root = ET.parse(again.fcpxml_path).getroot()
    again_spine = again_root.find(".//spine")
    assert again_spine is not None
    again_clips = [node for node in list(again_spine) if node.tag == "asset-clip"]
    assert [node.attrib["name"] for node in again_clips] == [node.attrib["name"] for node in clips]
    assert _confirmed_bytes(paths, listing.version_id) == before

    server = start_confirm_desk(paths.root, host="127.0.0.1", port=0)
    try:
        port = _port(server)
        code, body = _post_json(port, "/api/regions-export", {"version_id": "draft"})
        assert code == 400
        assert "草稿" in body["error"]
        code, body = _post_json(port, "/api/regions-export", {"version_id": listing.version_id, "path": "/tmp/nope"})
        assert code == 400
        code, body = _post_json(
            port, "/api/regions-export", {"version_id": listing.version_id}, timeout=120
        )
        assert code == 200, body
        assert body["frame_rate"] == 30
        assert "还没在这台机器上验证" in body["notice"]
        assert (paths.root / body["fcpxml"]).is_file()
        assert (paths.root / body["sheet"]).is_file()
        ET.parse(paths.root / body["fcpxml"])
    finally:
        server.shutdown()
        server.server_close()


def _src_path(clip, root):
    from urllib.parse import unquote, urlparse

    asset = root.find(f".//asset[@id='{clip.attrib['ref']}']")
    assert asset is not None
    return Path(unquote(urlparse(asset.attrib["src"]).path))


def _video_frames(path: Path) -> int:
    payload = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "csv=p=0",
            str(path),
        ],
        text=True,
    )
    return int(payload.strip())


def test_placeholder_tools_missing_are_chinese(monkeypatch) -> None:
    import director.regions_fcpxml as exporter

    monkeypatch.setattr(exporter.shutil, "which", lambda _name: None)
    monkeypatch.setattr(exporter, "_HOMEBREW_FFMPEG", Path("/no/such/ffmpeg"))
    with pytest.raises(ValueError, match="找不到 ffmpeg"):
        exporter.ffmpeg_executable()
    monkeypatch.setattr(exporter, "_FONT_CANDIDATES", (Path("/no/such/font.ttc"),))
    with pytest.raises(ValueError, match="找不到中文字体"):
        exporter.cjk_font_path()


def shot_slots_cycles():
    from director.shot_track.fastcut import SHOT_CYCLES

    return SHOT_CYCLES["travel"]["base"]
