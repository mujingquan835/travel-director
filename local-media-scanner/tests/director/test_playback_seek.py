"""Playhead seeking is navigation. Blocks stay fixed."""

from __future__ import annotations

import subprocess

from director.confirm_serve import (
    clamp_seek,
    detail_window,
    neighbor_mark,
    playback_span_step,
    seek_from_fraction,
)
from director.music_timeline import render_timeline_page


def test_seek_helpers_clamp_and_step_marks() -> None:
    assert clamp_seek(-1, 60) == 0
    assert clamp_seek(70, 60) == 60
    assert clamp_seek(12.5, 60) == 12.5
    assert seek_from_fraction(0.5, 60) == 30
    assert seek_from_fraction(-1, 60) == 0
    assert seek_from_fraction(2, 60) == 60

    marks = [0.0, 0.5, 1.0, 2.0]
    assert neighbor_mark(marks, 0.5, 1) == 1.0
    assert neighbor_mark(marks, 0.5, -1) == 0.0
    assert neighbor_mark(marks, 2.0, 1) == 2.0
    assert neighbor_mark(marks, 0.0, -1) == 0.0
    assert neighbor_mark([], 4.0, 1) == 4.0

    assert detail_window(10, 60) == (6, 14)
    assert detail_window(1, 60) == (0, 8)
    assert detail_window(59, 60) == (52, 60)
    assert detail_window(3, 5) == (0, 5)
    assert playback_span_step(9.96, 0.0, 10.0, False) == "pause"
    assert playback_span_step(9.96, 0.0, 10.0, True) == "seek"


def test_detail_lane_follows_the_playhead_and_hides_the_old_split() -> None:
    region = {
        "region_id": "r03",
        "edit_role": "establish",
        "kind_label": "前奏",
        "start": 8.0,
        "end": 16.0,
        "suggested_shot_mean_s": 2.0,
        "shot_min_s": 1.0,
        "shot_max_s": 4.0,
        "snap_policy": "beat",
        "confidence": 0.65,
        "energy_slope": 0.0,
        "mean_energy": 0.62,
        "musical_proxy": "intro",
        "desired_motion": "low",
        "content_need": "orientation_detail",
        "source": "analyzer",
        "cut_summary_zh": "先把小节点定下来",
    }
    view = {
        "regions": [region],
        "duration_seconds": 60.0,
        "bpm": 120.0,
        "confidence": 0.8,
        "provider": "beat_this+heuristic",
        "schema_version": "0.1.0",
        "status": "draft",
        "read_only": False,
        "acceptance": {"ok": True, "unknown_region_ids": []},
        "versions": [],
        "version_id": "regions-v01",
        "warnings": [],
        "beats_seconds": [8.0, 8.5, 9.0, 9.5, 10.0],
        "downbeats_seconds": [8.0, 10.0],
        "beat_grid": {"period_s": 0.5},
        "phrases": [{"start": 8.0, "end": 16.0}],
        "shot_slots": [
            {
                "slot_id": "r03-s04",
                "region_id": "r03",
                "start": 10.0,
                "end": 12.0,
                "shot_type": "细",
                "pace": "medium",
                "confidence": 0.8,
                "reason_zh": "落在强拍上",
                "reason_code": "DOWNBEAT_HOLD",
                "beats": 4,
                "evidence": {},
            }
        ],
        "region_cut_anchors": [],
    }
    page = render_timeline_page(
        project_title="示例数据",
        project_id="sample",
        project_path="/tmp/sample",
        track_label="示例",
        view=view,
        message="",
        selected="r01",
        playhead="11",
        kind_labels={"establish": "前奏"},
        snap_labels={"beat": "按拍"},
        warning_labels={},
    )
    assert "局部细节 · 跟随播放头 · 前后 4 秒" in page
    assert "放大 ·" not in page
    assert 'id="compare-old"' in page
    assert 'id="compare-row" hidden' in page
    assert 'id="zoom-lane"' in page
    assert 'data-origin="7.000000"' in page
    assert 'data-limit="15.000000"' in page
    assert "镜头 r03-s4 · 细 · 2.0s" in page
    assert 'id="loop" checked' not in page
    assert "循环本段" in page
    assert "waveform" not in page.lower()
    assert '"enabled"' not in page
    assert "drag:true" not in page
    assert 'draggable="true"' not in page
    assert "<table" not in page
    assert 'type="number"' not in page
    assert 'class="how on"' in page
    assert 'class="phr on"' in page
    assert "data-selected=\"r03\"" in page


def test_page_javascript_matches_the_seek_helpers() -> None:
    page = render_timeline_page(
        project_title="示例数据",
        project_id="sample",
        project_path="/tmp/sample",
        track_label="示例",
        view=None,
        message="",
        selected=None,
        playhead=None,
        kind_labels={},
        snap_labels={},
        warning_labels={},
    )
    start = page.index("function playbackSpanStep")
    end = page.index("function loopOn")
    script = page[start:end]
    program = script + """
if (detailWindow(10, 60)[0] !== 6 || detailWindow(10, 60)[1] !== 14) throw new Error("center");
var nearStart = detailWindow(1, 60);
if (nearStart[0] !== 0 || nearStart[1] !== 8) throw new Error("start");
var nearEnd = detailWindow(59, 60);
if (nearEnd[0] !== 52 || nearEnd[1] !== 60) throw new Error("end");
if (detailWindow(3, 5)[1] !== 5) throw new Error("short");
var marks = [0, 0.5, 1, 2];
if (neighborMark(marks, 0.5, 1) !== 1) throw new Error("next");
if (neighborMark(marks, 0.5, -1) !== 0) throw new Error("prev");
if (neighborMark([], 4, 1) !== 4) throw new Error("empty");
if (seekFromFraction(0.5, 60) !== 30) throw new Error("fraction");
if (clampSeek(-3, 10) !== 0 || clampSeek(12, 10) !== 10) throw new Error("clamp");
if (playbackSpanStep(9.96, 0, 10, false) !== "pause") throw new Error("pause");
if (playbackSpanStep(9.96, 0, 10, true) !== "seek") throw new Error("loop");
"""
    completed = subprocess.run(
        ["node", "-e", program],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
