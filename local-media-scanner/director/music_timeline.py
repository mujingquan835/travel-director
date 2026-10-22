"""Timeline page for ``/music``.

The layout follows the approved static mock: transport, ruler, music lane,
beat ticks, colored region blocks, and a shot lane. Blocks are HTML positioned
by time. They are not draggable. Clicking or dragging a time lane seeks.
When the analyzer stored shot slots, the shot lane uses those lengths and a
detail lane follows the playhead. Otherwise the lane stays the empty
equal-slot placeholder. Role changes go through the existing draft API.
Confirmed versions render a disabled role control.

Peaks are fetched from ``/api/`` + ``wave`` + ``form-peaks`` and drawn by the
vendored wavesurfer build. The page does not decode the file itself.
"""

from __future__ import annotations

import html
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from director.regions_fcpxml import EXPORT_PAGE_NOTE
from director.role_labels import STYLE_LABELS_ZH

ROLE_COLORS = {
    "hook": "#c27a62",
    "establish": "#7f9e9c",
    "narrative_hold": "#5f8f86",
    "build": "#c4a45f",
    "peak_cut": "#a65b6b",
    "breath": "#8d7ea3",
    "settle_outro": "#6f7f9c",
    "unknown": "#c9b48a",
}

_PAGE_CSS = """
:root{
  --bg:#f5f4ef; --panel:#fbfaf7; --line:#e2e0d8; --line2:#ecebe5;
  --ink:#2e3336; --ink2:#5d6469; --mute:#90969a;
  --accent:#4a6670; --warn:#b07a2a; --warnbg:#f6ecd9; --danger:#9c4f4f;
  --hdr:116px;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Noto Sans CJK SC","Noto Sans SC","PingFang SC","Microsoft YaHei","WenQuanYi Micro Hei","Source Han Sans SC",sans-serif;
  font-size:13px}
body{height:100vh;overflow:hidden;display:flex;flex-direction:column}
button,select,input{font-family:inherit;font-size:13px;color:var(--ink)}
a{color:var(--accent);text-decoration:none}
.btn{height:30px;padding:0 10px;border:1px solid #d6d3c9;background:#fffefb;border-radius:6px;cursor:pointer}
.btn.primary{background:#3f5a63;border-color:#3f5a63;color:#f7f6f1}
.btn.ghost{background:transparent}
.btn.danger{color:var(--danger)}
.btn.on{background:#e6ece9;border-color:#a9bab4}
.btn:disabled,.btn[disabled]{opacity:.45;cursor:default}
#import-music-label{cursor:pointer}
#import-status{max-width:320px;line-height:1.3}
#music-picker{max-width:240px}
.top{flex:none;display:flex;align-items:center;gap:6px 8px;padding:6px 16px;min-height:52px;
  border-bottom:1px solid var(--line);background:var(--panel);flex-wrap:wrap}
.logo{width:22px;height:22px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#fff,#dcdcd2 70%);border:1px solid #cfccc1;flex:none}
.brand{min-width:0;max-width:280px}
.pname{font-size:16px;font-weight:600;letter-spacing:.5px;line-height:1.2}
.psub{color:var(--mute);font-size:12px}
.ver{display:flex;align-items:center;gap:6px;height:30px;padding:0 10px;border:1px solid #d6d3c9;border-radius:6px;background:#fffefb}
#version-meta{color:var(--mute);font-size:12px;font-family:"DejaVu Sans Mono",monospace}
.sp{flex:1}
#acceptance{display:flex;align-items:center;height:28px;margin:0;padding:0 12px;border-radius:14px;font-size:12px;font-weight:600}
#acceptance.ok{background:#e7f0ea;color:#2f6b4f;border:1px solid #c5ddd0}
#acceptance.bad{background:var(--warnbg);color:var(--warn);border:1px solid #e8d4ae}
#unknown-warning{flex-basis:100%;margin:0;padding:4px 10px;border-radius:6px;background:var(--warnbg);color:#7a5520;border:1px solid #ecdcbb}
#unknown-warning[hidden]{display:none}
#force-reason{height:30px;border:1px solid #cfccc1;border-radius:5px;background:#fffefb;padding:0 8px;width:132px}
.transport{height:42px;flex:none;display:flex;align-items:center;gap:12px;padding:0 24px;color:var(--ink2);font-size:12px}
.tc{font-family:"DejaVu Sans Mono",monospace;font-size:14px;color:var(--ink)}
.tc small{color:var(--mute);font-size:12px}
.meta span{margin-right:14px}
.legend{display:flex;gap:10px;align-items:center;flex-wrap:nowrap}
.legend i{display:inline-block;width:12px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
.tl{margin:0 24px;border:1px solid var(--line);border-radius:8px;background:var(--panel);position:relative;flex:none}
.row{display:grid;grid-template-columns:var(--hdr) 1fr;border-bottom:1px solid var(--line2)}
.row:last-child{border-bottom:none}
.rh{padding:8px 12px;font-size:12px;color:var(--ink2);border-right:1px solid var(--line2);display:flex;flex-direction:column;justify-content:center;gap:2px}
.rh b{color:var(--ink);font-weight:600;font-size:13px}
.rh small{color:var(--mute);font-size:11px}
.lane{position:relative;margin:0 14px}
.r-mark .lane{height:20px}
.r-ruler .lane{height:30px}
.r-wave .lane{height:124px}
.r-beat .lane{height:22px}
.r-reg .lane{height:66px}
.r-shot .lane{height:100px}
#ruler{position:absolute;inset:0}
#wave{position:absolute;left:0;right:0;top:8px;height:108px}
.blk{position:absolute;top:7px;bottom:7px;border-radius:5px;color:#fff;padding:6px 8px;overflow:hidden;white-space:nowrap;
  border:1px solid rgba(0,0,0,.08);display:flex;flex-direction:column;justify-content:center;cursor:pointer}
.blk .nm{font-size:13px;font-weight:600;letter-spacing:.5px}
.blk .tm{font-size:10.5px;opacity:.85;margin-top:1px}
.blk.unknown{color:#5a4a2a;border:1px dashed #b08a4a;
  background:repeating-linear-gradient(-45deg,#efe4cc 0 6px,#e2d3b1 6px 12px)}
.blk.sel{box-shadow:0 0 0 2px var(--panel),0 0 0 4px #2e3336;z-index:2}
.blk.narrow{padding:6px 4px}
.blk.narrow .nm{font-size:12px;letter-spacing:0}
.blk .wb{display:inline-block;background:#b07a2a;color:#fff;font-size:10px;border-radius:3px;padding:0 4px;margin-left:4px;font-weight:600}
.beat{position:absolute;top:8px;bottom:4px;width:1px;background:#b9bcbc}
.beat.db{top:2px;background:#6c7579;width:1.5px}
.slotgrp{position:absolute;top:0;bottom:0}
.slotcap{position:absolute;top:5px;left:2px;right:2px;font-size:10.5px;color:var(--mute);white-space:nowrap;overflow:hidden}
.slot{position:absolute;top:24px;bottom:8px;border:1.2px dashed #b4b7b3;border-radius:4px;background:rgba(255,255,255,.55);
  display:flex;align-items:center;justify-content:center;text-align:center;font-size:10px;line-height:1.25;color:#a2a6a6;overflow:hidden}
.slotgrp.sel .slot{border-color:#7d8a8e;color:#6f7a7e;background:#fff}
.slotgrp.sel .slotcap{color:var(--ink2)}
.rsep{position:absolute;top:0;bottom:0;width:1px;background:var(--line)}
.ov{position:absolute;top:0;bottom:0;left:calc(var(--hdr) + 14px);right:14px;pointer-events:none;z-index:5}
.ov *{pointer-events:none}
.loopband{position:absolute;top:0;bottom:0;background:rgba(63,90,99,.06);border-left:1px solid rgba(46,51,54,.35);border-right:1px solid rgba(46,51,54,.35)}
.loopband[hidden]{display:none}
.brk{position:absolute;top:20px;width:9px;height:14px;border:2px solid #2e3336;border-bottom:none}
.brk.l{left:-1px;border-right:none;border-radius:2px 0 0 0}
.brk.r{right:-1px;border-left:none;border-radius:0 2px 0 0}
.loopcap{position:absolute;top:3px;right:12px;font-size:11px;color:#2e3336;background:var(--bg);padding:0 6px;white-space:nowrap}
.ph{position:absolute;top:0;bottom:0;width:0;border-left:1.5px solid #c0453a;pointer-events:auto;cursor:ew-resize;z-index:6}
.ph,.ph *{pointer-events:auto}
.ph:before{content:"";position:absolute;top:20px;left:-6.5px;border:5.5px solid transparent;border-top:8px solid #c0453a}
.ph:after{content:"";position:absolute;left:-8px;top:0;bottom:0;width:16px}
.phcap{position:absolute;top:3px;right:5px;background:#fbeeec;padding:0 4px;border-radius:3px;font-size:11px;color:#c0453a;font-family:"DejaVu Sans Mono",monospace}
.now-shot{margin-left:10px;font-size:12px;color:var(--ink);white-space:nowrap}
.insp{flex:1;margin:12px 24px 16px;border:1px solid var(--line);border-radius:8px;background:var(--panel);
  display:grid;grid-template-columns:1.25fr 1fr 1.15fr;min-height:0;overflow:auto}
.col{padding:14px 18px;border-right:1px solid var(--line2);display:flex;flex-direction:column;gap:10px;min-width:0}
.col:last-child{border-right:none}
.ih{display:flex;align-items:center;gap:10px}
.ih .sw{width:14px;height:14px;border-radius:3px;flex:none}
.ih b{font-size:15px}
.ih .rid{color:var(--mute);font-family:"DejaVu Sans Mono",monospace;font-size:12px}
.f{display:grid;grid-template-columns:72px 1fr;align-items:center;gap:8px}
.f label{color:var(--mute);font-size:12px}
.f .v{color:var(--ink)}
.ro{display:flex;align-items:center;gap:8px;min-width:0;flex-wrap:wrap}
.ro .box{height:28px;display:flex;align-items:center;padding:0 10px;border:1px solid var(--line);border-radius:5px;background:#f1f0eb;color:var(--ink2);font-family:"DejaVu Sans Mono",monospace;font-size:12.5px}
.note{font-size:11px;color:var(--mute)}
#snapshot-notice{margin:8px 16px 0;padding:8px 12px;background:var(--warnbg);color:var(--warn);border:1px solid #e8d4ae;border-radius:8px;font-size:13px}
.note.ms{border:1px solid var(--line);border-radius:10px;padding:1px 8px}
select{height:30px;border:1px solid #cfccc1;border-radius:5px;background:#fffefb;padding:0 8px}
select:disabled{background:#f1f0eb;color:var(--ink2)}
.cbar{flex:1;height:6px;background:#e7e5de;border-radius:3px;overflow:hidden;max-width:170px}
.cbar i{display:block;height:100%;background:#6f8b86}
.cbar.low i{background:#c3964a}
.sub{font-size:12px;color:var(--mute);font-weight:600;letter-spacing:.5px}
.warns{display:flex;flex-direction:column;gap:7px}
.w{display:flex;gap:8px;align-items:flex-start;padding:7px 10px;border-radius:6px;background:var(--warnbg);color:#7a5520;font-size:12px;line-height:1.45;border:1px solid #ecdcbb}
.w.info{background:#eef0ee;color:#5d6469;border-color:#e0e3df}
.w code{font-family:"DejaVu Sans Mono",monospace;font-size:11px}
.none{color:var(--mute);font-size:12px}
.acts{display:flex;gap:8px;margin-top:auto}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:12px;color:var(--ink2)}
.kv span:nth-child(odd){color:var(--mute)}
#error{margin:8px 24px 0;padding:8px 12px;background:var(--warnbg);border:1px solid #e8d4ae;border-radius:6px}
#error[hidden]{display:none}
details#region-list{margin-top:4px}
details#region-list summary{cursor:pointer;color:var(--mute);font-size:12px}
details#region-list ul{margin:6px 0 0;padding-left:18px;color:var(--ink2);font-size:12px}
audio{position:absolute;width:0;height:0;opacity:0}
body.has-slots{--hdr:108px}
body.has-slots .transport{height:36px}
body.has-slots .r-mark .lane{height:16px}
body.has-slots .r-ruler .lane{height:24px}
body.has-slots .r-wave .lane{height:64px}
body.has-slots #wave{top:4px;height:56px}
body.has-slots .r-beat .lane{height:16px}
body.has-slots .r-reg .lane{height:64px}
body.has-slots .r-reg .blk{top:2px;bottom:20px;padding:2px 6px}
body.has-slots .r-reg .blk .nm{font-size:12px}
body.has-slots .r-phrase .lane{height:22px}
body.has-slots .r-shot .lane{height:72px;overflow:hidden}
body.has-slots .r-how .lane{height:34px}
body.has-slots .insp{margin-top:8px}
#beat-backend-note{flex:none;margin:0 24px 6px;padding:4px 10px;background:#f6ecd9;border:1px solid #e8d4ae;border-radius:6px;color:#7a5520;font-size:12px;line-height:1.45}
.phr{position:absolute;top:3px;bottom:3px;border:1px solid #c5c9c6;border-bottom:none;border-radius:5px 5px 0 0;color:#6a7378;font-size:11px;padding:0 4px;overflow:hidden;white-space:nowrap}
.phr.on{background:rgba(63,90,99,.14);color:#2e3336;border-color:#3f5a63}
.how{position:absolute;top:2px;bottom:2px;padding:1px 4px;overflow:hidden;color:#3c4448;font-size:11px;line-height:1.25;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.how.on{background:#f6ecd9;box-shadow:inset 0 0 0 1px #c9a15b}
.sl,.zshot{position:absolute;margin:0;padding:0;border:0;border-radius:0;min-width:1px;overflow:hidden;cursor:pointer;box-sizing:border-box}
.sl{top:4px;bottom:8px;z-index:1;color:#2e3336;font-size:11px;line-height:1.15}
.sl.fast,.zshot.fast{color:#fff}
.sl.faint,.zshot.faint{outline:1px dashed rgba(46,51,54,.55);outline-offset:-1px}
.sl.pending{color:#5a4a2a;background:repeating-linear-gradient(-45deg,#efe4cc 0 4px,#e2d3b1 4px 8px)}
.sl.alt,.zshot.alt{background-image:linear-gradient(rgba(255,255,255,.16),rgba(255,255,255,.16))}
.sl.hair,.zshot.hair{box-shadow:inset 1px 0 0 rgba(28,28,28,.72)}
.sl.on,.zshot.on{box-shadow:inset 0 0 0 2px #2e3336;z-index:3}
.sl.on.hair,.zshot.on.hair{box-shadow:inset 1px 0 0 rgba(28,28,28,.72), inset 0 0 0 2px #2e3336}
.flurry-run{position:absolute;top:4px;bottom:8px;margin:0;padding:0;border:0;pointer-events:none;z-index:2}
.flurry-run .bracket{position:absolute;inset:0;border:0 solid #1c1c1c;border-left-width:2px;border-right-width:2px;border-bottom-width:2px;pointer-events:none}
.mark{position:absolute;right:2px;bottom:2px;color:#9c2b22;font-size:10px;font-weight:700;background:rgba(255,252,248,.94);padding:0 2px;border-radius:2px;line-height:1.3;z-index:3}
.zshot .mark{font-size:12px;top:2px;bottom:auto}
.stylelane{display:flex;align-items:center;gap:12px;height:34px;font-size:12px}
#shot-style{height:26px;border:1px solid #d6d3c9;border-radius:5px;background:#fffefb;padding:0 6px}
.r-shot{position:relative}
#guide-toggle{position:absolute;left:calc(var(--hdr) + 8px);top:6px;z-index:6;height:26px;padding:0 10px;font-weight:700;background:#fff8e8;border:1px solid var(--accent);color:var(--accent);border-radius:6px;cursor:pointer}
#guide-rows[hidden]{display:none !important}
.r-guide .lane{height:20px;overflow:hidden}
.r-guide .rh{padding:1px 10px}
.gcell{position:absolute;top:1px;bottom:1px;margin:0;padding:0 0 0 2px;border:0;border-radius:0;min-width:1px;overflow:hidden;z-index:1;font-size:10px;line-height:18px;white-space:nowrap;cursor:pointer}
.gcell.hair{box-shadow:inset 1px 0 0 rgba(28,28,28,.72)}
.gcell.on{box-shadow:inset 0 0 0 2px #2e3336;z-index:3}
.gcell.on.hair{box-shadow:inset 1px 0 0 rgba(28,28,28,.72), inset 0 0 0 2px #2e3336}
.guide-run{position:absolute;top:1px;bottom:1px;margin:0;padding:0;border:0;pointer-events:none;z-index:2}
.guide-run .bracket{position:absolute;inset:0;border:0 solid #1c1c1c;border-left-width:2px;border-right-width:2px;border-bottom-width:2px;pointer-events:none}
#drop-contrast{color:#8a3b32;font-weight:650}
#detail-contrast{margin:4px 0 0;color:#8a3b32;font-weight:650;font-size:12px}
#detail-contrast:empty{display:none}
.marklegend{display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:12px;color:#3c4448;margin:6px 0 0}
.marklegend .mark{position:static;font-size:12px}
.flurrykey{display:inline-block;width:36px;height:12px;background:#d9d3cc;border-left:2px solid #1c1c1c;border-right:2px solid #1c1c1c;border-bottom:2px solid #1c1c1c;vertical-align:-2px;background-image:linear-gradient(90deg,transparent 11px,rgba(28,28,28,.72) 11px,rgba(28,28,28,.72) 12px,transparent 12px,transparent 23px,rgba(28,28,28,.72) 23px,rgba(28,28,28,.72) 24px,transparent 24px)}
.sl b,.zshot b{font-weight:650;margin-left:2px}
.sl em,.zshot em{font-style:normal;font-size:10px;opacity:.85;margin-left:2px}
.exc{position:absolute;left:4px;bottom:3px;width:5px;height:5px;border-radius:50%;background:#d07a2a}
.accent-mark{position:absolute;top:0;width:0;height:0;border-left:4px solid transparent;border-right:4px solid transparent;border-top:6px solid #c0453a;transform:translateX(-4px)}
.breath-mark{position:absolute;top:0;transform:translateX(-6px);color:#3d6f9a;font-size:11px;font-weight:700}
.snapchip{position:absolute;bottom:1px;z-index:4;transform:translateX(-50%);background:#fff8e8;border:1px solid #c9a15b;border-radius:4px;font-size:10px;line-height:1.15;padding:1px 3px;color:#5a4a2a;white-space:nowrap;pointer-events:auto}
.snapchip button{margin-left:3px;height:16px;padding:0 4px;font-size:10px;border:1px solid #c9a15b;border-radius:3px;background:#fff;cursor:pointer}
.snapchip button:disabled{cursor:not-allowed;opacity:.55}
#adopt-all{height:20px;margin-top:2px;padding:0 6px;font-size:11px}
#snap-notes{margin:0;padding-left:16px;font-size:12px;line-height:1.45;color:var(--ink2)}
.density{position:absolute;top:18px;bottom:10px;border-radius:3px;background:#c7b2b6;color:#fff;font-size:10px;display:flex;align-items:center;justify-content:center}
.zoom{flex:none;margin:8px 24px 0;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 12px 10px}
.zoom h3{margin:0 0 6px;font-size:13px;font-weight:600}
.zoom .note{margin:0 0 6px}
.zlane{position:relative;height:78px;margin:0 0 6px;background:#f3f2ec;border-radius:4px;cursor:ew-resize;touch-action:none;overflow:hidden}
.zrow{position:absolute;left:0;right:0;top:24px;bottom:4px}
.zlane .beat{top:2px;bottom:auto;height:16px;z-index:1}
.zlane .beat.db{height:22px}
.zlane .zlab{position:absolute;top:0;left:2px;font-size:10px;color:#5c656a;line-height:1}
.zold{position:relative;height:18px;margin-top:4px}
.zold[hidden]{display:none}
.zph{position:absolute;top:0;bottom:0;width:0;border-left:1.5px solid #c0453a;z-index:4;pointer-events:none}
.zshot{top:0;bottom:0;z-index:1;color:#2e3336;font-size:12px;line-height:1.15}
.zrow .flurry-run{top:0;bottom:0}
.osl{position:absolute;top:1px;bottom:1px;border-radius:3px;overflow:hidden;font-size:10px;line-height:1.2;padding:2px 4px;border:1px dashed #c5c9c6;color:#8a9094;background:#eceae4}
.r-ruler .lane,.r-wave .lane,.r-reg .lane,.r-phrase .lane,.r-shot .lane{touch-action:none}
#slot-detail p{margin:0 0 4px;font-size:12px;line-height:1.4}
#how-list{margin:0;padding-left:16px;font-size:12px;line-height:1.4;color:var(--ink2)}
.typelegend{font-size:11px;color:var(--mute);line-height:1.4}
"""


def brief_title(brief_path: Path, fallback: str) -> str:
    """First line of the project's raw brief, capped for the top bar."""

    try:
        payload = json.loads(brief_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    raw = payload.get("raw_description") if isinstance(payload, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return fallback
    line = raw.strip().splitlines()[0].strip()
    return line[:80] or fallback


def _beat_words(slot: dict) -> str:
    length = slot.get("beat_length")
    if not isinstance(length, (int, float)):
        return f"{int(slot.get('beats') or 0)} 拍"
    value = float(length)
    if abs(value - 0.5) < 1e-6:
        return "½拍"
    if abs(value * 2 - round(value * 2)) < 1e-6 and abs(value - round(value)) > 0.2:
        whole = int(value)
        return ("½拍" if whole == 0 else f"{whole}½拍")
    return f"{value:g}拍"


def _mmss(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:
        seconds = 0.0
    minutes = int(seconds // 60)
    remain = seconds - minutes * 60
    return f"{minutes:02d}:{remain:06.3f}"


def _span_style(start: float, end: float, duration: float) -> str:
    left = start / duration * 100
    width = (end - start) / duration * 100
    return f"left:{left:.3f}%;width:{width:.3f}%"


def _edge_milli(moment: float, origin: float, span: float) -> int:
    """Thousandths of a percent. Shared edges use the same integer, so neighbors abut."""

    if span <= 0:
        return 0
    return int(round((float(moment) - origin) / span * 100000))


def _fmt_milli(milli: int) -> str:
    sign = "-" if milli < 0 else ""
    whole, frac = divmod(abs(int(milli)), 1000)
    return f"{sign}{whole}.{frac:03d}"


def _shot_box_style(start: float, end: float, origin: float, span: float) -> str:
    """Exact time position. The extra pixel covers subpixel cracks without moving the next left."""

    left = _edge_milli(start, origin, span)
    width = max(0, _edge_milli(end, origin, span) - left)
    return f"left:{_fmt_milli(left)}%;width:calc({_fmt_milli(width)}% + 1px)"


def _span_milli_style(start: float, end: float, origin: float, span: float) -> str:
    left = _edge_milli(start, origin, span)
    width = max(0, _edge_milli(end, origin, span) - left)
    return f"left:{_fmt_milli(left)}%;width:{_fmt_milli(width)}%"


def _item_at(items: list, moment: float) -> dict | None:
    """The span that contains ``moment``. The last span also owns its end."""

    if not items:
        return None
    last = len(items) - 1
    for index, item in enumerate(items):
        start = float(item["start"])
        end = float(item["end"])
        if start <= moment < end or (index == last and start <= moment <= end):
            return item
    return None


def _display_slot_id(slot_id: str) -> str:
    for marker in ("-s", "-t", "-e"):
        if marker not in slot_id:
            continue
        head, tail = slot_id.rsplit(marker, 1)
        if tail.isdigit():
            return f"{head}{marker}{int(tail)}"
    return slot_id


_MARK_ZH = {
    "flash": "闪",
    "ramp_in": "冲",
    "ramp_out": "落",
    "slow": "慢",
    "freeze": "定",
    "whip": "甩",
    "match": "配",
    "zoom": "推",
    "mask": "遮",
    "fade": "隐",
}


def _slot_marks(slot: dict) -> str:
    parts: list[str] = []
    if slot.get("flash"):
        parts.append(_MARK_ZH["flash"])
    ramp = slot.get("ramp")
    if ramp:
        parts.append(_MARK_ZH.get(str(ramp), "变速"))
    transition = slot.get("transition")
    if transition and transition != "cut":
        parts.append(_MARK_ZH.get(str(transition), "转"))
    if not parts:
        return ""
    return f'<span class="mark">{html.escape("·".join(parts))}</span>'


def _style_options(current: str) -> str:
    labels = tuple(STYLE_LABELS_ZH.items())
    parts = []
    for value, label in labels:
        selected = " selected" if value == current else ""
        parts.append(f'<option value="{value}"{selected}>{label}</option>')
    return "".join(parts)


def _style_row(view: dict) -> str:
    current = str(view.get("shot_style") or "narrative")
    blocked = bool(view.get("read_only") and view.get("has_draft"))
    disabled = " disabled" if blocked else ""
    title = (
        "已经有打开的草稿。先确认或丢弃它，再基于确认版另开。"
        if blocked
        else "换剪法会重排镜头轨。已确认的版本不会被改写。"
    )
    rules = str(view.get("shot_rules_version") or "")
    rules_html = f'<span class="note">{html.escape(rules)}</span>' if rules else ""
    contrast = html.escape(str(view.get("drop_contrast_zh") or ""))
    return (
        '<div class="row r-style" id="track-style"><div class="rh"><b>剪法</b></div>'
        f'<div class="lane stylelane"><label>镜头轨 <select id="shot-style" title="{html.escape(title)}"'
        f'{disabled}>{_style_options(current)}</select></label>{rules_html}'
        f'<span id="drop-contrast">{contrast}</span></div></div>'
    )


def _mark_legend() -> str:
    return (
        '<p class="marklegend" id="mark-legend">'
        '<span class="mark">闪</span> 闪白'
        '<span class="mark">慢</span> 变速（冲 加速 / 落 转慢 / 慢 慢放 / 定 定格）'
        '<span class="mark">甩</span> 转场（甩镜 / 推 推镜 / 配 匹配 / 遮 遮挡 / 隐 渐隐）'
        '<i class="flurrykey"></i> 快闪组'
        "</p>"
    )


def _shot_caption(slot: dict) -> str:
    length = float(slot["end"]) - float(slot["start"])
    kind = str(slot.get("shot_type") or "")
    return f"镜头 {_display_slot_id(str(slot.get('slot_id') or ''))} · {kind} · {length:.1f}s"


def _slot_count(region: dict) -> int:
    length = float(region["end"]) - float(region["start"])
    mean = float(region["suggested_shot_mean_s"]) or 1.0
    return max(1, int(round(length / mean)))


def _json_script(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def _role_options(current: str, kind_labels: dict[str, str]) -> str:
    parts = []
    for role, label in kind_labels.items():
        selected = " selected" if role == current else ""
        parts.append(
            f'<option value="{html.escape(role)}"{selected}>{html.escape(label)}</option>'
        )
    return "".join(parts)


def _version_chrome(view: dict) -> str:
    options = []
    for item in view.get("versions") or []:
        selected = " selected" if item["version_id"] == view["version_id"] else ""
        options.append(
            f'<option value="{html.escape(str(item["version_id"]))}"{selected}>'
            f'{html.escape(str(item["label"]))}</option>'
        )
    when = view.get("confirmed_at") or "尚未确认"
    meta = f"{html.escape(str(view.get('source_music_sha8') or ''))} · {html.escape(str(when))}"
    acceptance = view.get("acceptance") or {}
    ok = bool(acceptance.get("ok"))
    unknown = [str(item) for item in (acceptance.get("unknown_region_ids") or [])]
    if unknown:
        warning = "这些分段的角色还没定：" + ", ".join(unknown) + "。普通确认已停用。"
        warning_attr = ""
        verdict = f"还有 {len(unknown)} 段待定角色"
        pill = "bad"
    elif ok:
        warning = ""
        warning_attr = " hidden"
        verdict = "验收通过"
        pill = "ok"
    else:
        warning = ""
        warning_attr = " hidden"
        verdict = "还不能确认"
        pill = "bad"
    read_only = bool(view.get("read_only"))
    confirm_disabled = " disabled" if read_only or not ok else ""
    fork_hidden = "" if read_only and not view.get("has_draft") else " hidden"
    save_disabled = " disabled" if read_only else ""
    pick_unknown = (
        '<button type="button" class="btn" id="pick-unknown">去选角色</button>'
        if unknown and not read_only
        else ""
    )
    return (
        f'<label class="ver">版本 <select id="version-picker">{"".join(options)}</select></label>'
        f'<span id="version-meta">{meta}</span>'
        '<button type="button" class="btn ghost" id="compare-previous" disabled title="后续版本开放">对比上次</button>'
        '<div class="sp"></div>'
        f'<p id="acceptance" class="{pill}">{verdict}</p>'
        f"{pick_unknown}"
        f'<button type="button" class="btn ghost" id="save"{save_disabled}>保存草稿</button>'
        f'<button type="button" class="btn ghost danger" id="discard"{save_disabled}>丢弃草稿</button>'
        f'<button type="button" class="btn primary" id="confirm-version"{confirm_disabled}>确认分区</button>'
        f'<button type="button" class="btn" id="export-fcpxml"{"" if read_only else " disabled"}>导出剪辑</button>'
        f'<p id="unknown-warning"{warning_attr}>{html.escape(warning)}</p>'
        '<label><input type="checkbox" id="force-confirm"> 强制确认</label>'
        '<input id="force-reason" type="text" placeholder="强制确认的原因">'
        f'<button type="button" class="btn ghost" id="draft-from-confirmed"{fork_hidden}>基于此版另开草稿</button>'
    )


def _beats_html(view: dict, duration: float) -> str:
    downs = [float(item) for item in (view.get("downbeats_seconds") or [])]
    parts = []
    for beat in view.get("beats_seconds") or []:
        moment = float(beat)
        down = any(abs(moment - item) < 1e-3 for item in downs)
        css = "beat db" if down else "beat"
        parts.append(f'<div class="{css}" style="left:{moment / duration * 100:.3f}%"></div>')
    return "".join(parts)


def _blocks_html(view: dict, duration: float, selected: str, kind_labels: dict[str, str]) -> str:
    parts = []
    for region in view["regions"]:
        start = float(region["start"])
        end = float(region["end"])
        role = str(region["edit_role"])
        region_id = str(region["region_id"])
        fraction = (end - start) / duration
        classes = ["blk"]
        style = _span_style(start, end, duration)
        if role == "unknown":
            classes.extend(["unknown", "is-unknown"])
        else:
            style += f";background:{ROLE_COLORS.get(role, '#7f9e9c')}"
        if region_id == selected:
            classes.append("sel")
        if fraction < 0.065:
            classes.append("narrow")
        label = str(region.get("kind_label") or kind_labels.get(role, role))
        badge = '<span class="wb">⚠</span>' if role == "unknown" and fraction >= 0.055 else ""
        if fraction > 0.105:
            sub = f"{region_id} · {_mmss(start)[:7]}–{_mmss(end)[:7]}"
        else:
            sub = region_id
        parts.append(
            f'<div class="{" ".join(classes)}" data-region-id="{html.escape(region_id)}" '
            f'style="{style}"><div class="nm">{html.escape(label)}{badge}</div>'
            f'<div class="tm">{html.escape(sub)}</div></div>'
        )
    return "".join(parts)


def _shots_html(view: dict, duration: float, selected: str) -> str:
    parts = []
    for region in view["regions"]:
        start = float(region["start"])
        end = float(region["end"])
        length = end - start
        fraction = length / duration
        count = _slot_count(region)
        slot_fraction = fraction / count
        region_id = str(region["region_id"])
        sel = " sel" if region_id == selected else ""
        slots = []
        for index in range(count):
            if slot_fraction > 0.059:
                text = "空槽·未选片"
            elif slot_fraction > 0.028:
                text = "空槽"
            else:
                text = ""
            slots.append(
                f'<div class="slot" style="left:{index / count * 100:.3f}%;width:{100 / count:.3f}%">{text}</div>'
            )
        mean = float(region["suggested_shot_mean_s"])
        if fraction > 0.105:
            caption = f"{count} 空槽 · 均长 {mean:g}s"
        elif fraction > 0.045:
            caption = f"{count} 空槽"
        else:
            caption = str(count)
        sep = ""
        if start > 0:
            sep = f'<div class="rsep" style="left:{start / duration * 100:.3f}%"></div>'
        parts.append(
            f'<div class="slotgrp{sel}" data-region-id="{html.escape(region_id)}" '
            f'style="{_span_style(start, end, duration)}">'
            f'<div class="slotcap">{html.escape(caption)}</div>{"".join(slots)}</div>{sep}'
        )
    return "".join(parts)


def _rgba(hex_color: str, alpha: float) -> str:
    text = hex_color.lstrip("#")
    if len(text) != 6:
        return f"rgba(127,158,156,{alpha})"
    red, green, blue = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    return f"rgba({red},{green},{blue},{alpha})"


def _pace_alpha(pace: str) -> float:
    if pace == "hold":
        return 0.28
    if pace == "fast":
        return 0.92
    return 0.55


def _slot_title(slot: dict) -> str:
    kind = str(slot.get("shot_type") or "")
    dur = float(slot["end"]) - float(slot["start"])
    reason = str(slot.get("reason_zh") or "")
    text = f"{kind} · {dur:.2f}s"
    if slot.get("reserve_best"):
        text = "★最好一镜 · " + text
    if reason:
        text += f" · {reason}"
    hint = str(slot.get("content_hint") or "")
    if hint:
        text += f" · {hint}"
    seam = str(slot.get("seam_zh") or "")
    if seam:
        text += f" · {seam}"
    return html.escape(text)


def _slot_face(slot: dict, pixels: float, *, detail: bool) -> str:
    """Hide or shorten the label when the block is narrower than the text. Hover keeps the full line."""

    kind = html.escape(str(slot.get("shot_type") or ""))
    dur = float(slot["end"]) - float(slot["start"])
    type_at = 14 if detail else 18
    time_at = 40 if detail else 46
    mark_at = 52 if detail else 64
    body = "★" if slot.get("reserve_best") else ""
    if pixels >= type_at and kind:
        body += f"<b>{kind}</b>"
    if pixels >= time_at:
        body += f"<em>{dur:.2f}s</em>"
    if pixels >= mark_at:
        body += _slot_marks(slot)
    return body


def _planned_slot_div(
    slot: dict,
    duration: float,
    *,
    zoom: tuple[float, float] | None = None,
    active: bool = False,
    hair: bool = False,
    alt: bool = False,
) -> str:
    start = float(slot["start"])
    end = float(slot["end"])
    if zoom is None:
        origin, span = 0.0, duration
        pixels = (end - start) / duration * 1200 if duration else 0.0
        css = "sl"
        detail = False
    else:
        origin, span = zoom
        pixels = (end - start) / span * 1100 if span else 0.0
        css = "zshot"
        detail = True
    role = str(slot.get("role") or "")
    pace = str(slot.get("pace") or "medium")
    classes = [css, "fast" if pace == "fast" else "hold" if pace == "hold" else "med"]
    if float(slot.get("confidence") or 1) < 0.5:
        classes.append("faint")
    if active:
        classes.append("on")
    if slot.get("flurry_group") or slot.get("pattern_role") == "flurry":
        classes.append("flurry")
    if hair:
        classes.append("hair")
    if alt and slot.get("shot_type") != "?":
        classes.append("alt")
    box = _shot_box_style(start, end, origin, span)
    if slot.get("shot_type") == "?":
        classes.append("pending")
        style = box
    else:
        color = ROLE_COLORS.get(role, "#7f9e9c")
        style = f"{box};background-color:{_rgba(color, _pace_alpha(pace))}"
    extra = '<i class="exc"></i>' if slot.get("budget_exception") else ""
    flurry_attr = (
        f' data-flurry-group="{html.escape(str(slot.get("flurry_group")))}"'
        if slot.get("flurry_group")
        else ""
    )
    return (
        f'<div class="{" ".join(classes)}" data-slot-id="{html.escape(str(slot["slot_id"]))}" '
        f'data-region-id="{html.escape(str(slot["region_id"]))}"{flurry_attr} '
        f'data-start="{start:.6f}" data-end="{end:.6f}" style="{style}" title="{_slot_title(slot)}">'
        f"{_slot_face(slot, pixels, detail=detail)}{extra}</div>"
    )


def _flurry_brackets(slots: list[dict], origin: float, span: float) -> str:
    """One under-bracket per flurry group. Members stay separate blocks with hairlines between them."""

    parts: list[str] = []
    index = 0
    while index < len(slots):
        group = slots[index].get("flurry_group")
        if not group:
            index += 1
            continue
        end_index = index + 1
        while end_index < len(slots) and slots[end_index].get("flurry_group") == group:
            end_index += 1
        start = float(slots[index]["start"])
        end = float(slots[end_index - 1]["end"])
        parts.append(
            f'<div class="flurry-run" data-flurry-group="{html.escape(str(group))}" '
            f'style="{_span_milli_style(start, end, origin, span)}"><i class="bracket"></i></div>'
        )
        index = end_index
    return "".join(parts)


def _with_role(view: dict, slot: dict) -> dict:
    payload = dict(slot)
    for region in view.get("regions") or []:
        if str(region["region_id"]) == str(slot["region_id"]):
            payload["role"] = region.get("edit_role")
            break
    return payload


def _planned_shots_html(view: dict, duration: float, active_id: str = "") -> str:
    slots = [_with_role(view, slot) for slot in view.get("shot_slots") or []]
    threshold = 3 * duration / 1200 if duration >= 180 else 0.0
    parts: list[str] = []
    bucket: list[dict] = []

    def flush() -> None:
        if not bucket:
            return
        if len(bucket) == 1 or threshold <= 0:
            parts.append(_planned_slot_div(bucket[0], duration, active=str(bucket[0].get("slot_id")) == active_id))
        else:
            start = float(bucket[0]["start"])
            end = float(bucket[-1]["end"])
            parts.append(
                f'<div class="density" data-region-id="{html.escape(str(bucket[0]["region_id"]))}" '
                f'style="{_span_style(start, end, duration)}" title="这里镜头太密，看下方局部细节">密</div>'
            )
        bucket.clear()

    emitted: list[dict] = []
    for index, slot in enumerate(slots):
        tiny = threshold > 0 and float(slot["end"]) - float(slot["start"]) < threshold
        if tiny and (not bucket or bucket[-1]["region_id"] == slot["region_id"]):
            bucket.append(slot)
            continue
        flush()
        if tiny:
            bucket.append(slot)
        else:
            parts.append(
                _planned_slot_div(
                    slot,
                    duration,
                    active=str(slot.get("slot_id")) == active_id,
                    hair=index > 0,
                    alt=not slot.get("flurry_group") and index % 2 == 1,
                )
            )
            emitted.append(slot)
    flush()
    parts.append(_flurry_brackets(emitted, 0.0, duration))
    for slot in slots:
        if slot.get("accent_at_start"):
            moment = float(slot["start"])
            parts.append(f'<div class="accent-mark" style="left:{moment / duration * 100:.3f}%"></div>')
    for moment in view.get("breath_marks") or []:
        parts.append(f'<div class="breath-mark" style="left:{float(moment) / duration * 100:.3f}%">≈</div>')
    return "".join(parts)


def _phrases_html(view: dict, duration: float, moment: float) -> str:
    parts = []
    for index, phrase in enumerate(view.get("phrases") or [], start=1):
        start = float(phrase["start"])
        end = float(phrase["end"])
        fraction = (end - start) / duration if duration else 0.0
        if fraction >= 0.055:
            label = f"句 {index}"
        elif fraction >= 0.028:
            label = str(index)
        else:
            label = ""
        on = " on" if start <= moment < end or (index == len(view.get("phrases") or []) and start <= moment <= end) else ""
        parts.append(
            f'<div class="phr{on}" data-start="{start:.6f}" data-end="{end:.6f}" '
            f'style="{_span_style(start, end, duration)}" '
            f'title="句 {index}">{html.escape(label)}</div>'
        )
    return "".join(parts)


def _how_html(view: dict, duration: float, moment: float) -> str:
    parts = []
    regions = list(view.get("regions") or [])
    current = _item_at(regions, moment)
    current_id = str(current["region_id"]) if current else ""
    for region in regions:
        start = float(region["start"])
        end = float(region["end"])
        summary = str(region.get("cut_summary_zh") or "")
        stats = str(region.get("cut_stats_zh") or "")
        fraction = (end - start) / duration if duration else 0.0
        shown = region["region_id"] if fraction < 0.08 or not summary else summary
        region_id = str(region["region_id"])
        on = " on" if region_id == current_id else ""
        parts.append(
            f'<div class="how{on}" data-region-id="{html.escape(region_id)}" '
            f'data-start="{start:.6f}" data-end="{end:.6f}" '
            f'style="{_span_style(start, end, duration)}" '
            f'title="{html.escape(stats or summary)}">{html.escape(str(shown))}</div>'
        )
    return "".join(parts)


def _detail_ticks(view: dict, origin: float, limit: float, span: float) -> str:
    downs = [float(item) for item in view.get("downbeats_seconds") or []]
    beats = [float(item) for item in view.get("beats_seconds") or []]
    seen: set[int] = set()
    moments = []
    for moment in beats + downs:
        key = int(round(moment * 1000))
        if key in seen:
            continue
        seen.add(key)
        if origin - 1e-6 <= moment <= limit + 1e-6:
            moments.append(moment)
    parts = []
    for moment in moments:
        down_index = next((index for index, item in enumerate(downs, start=1) if abs(item - moment) < 1e-3), 0)
        left = (moment - origin) / span * 100
        if down_index:
            parts.append(
                f'<div class="beat db" style="left:{left:.3f}%" title="强拍 {down_index}">'
                f'<span class="zlab">{down_index}</span></div>'
            )
        else:
            parts.append(f'<div class="beat" style="left:{left:.3f}%"></div>')
    return "".join(parts)


def _detail_old_row(view: dict, playhead: float, origin: float, limit: float, span: float) -> str:
    region = _item_at(list(view.get("regions") or []), playhead)
    if region is None:
        return ""
    count = _slot_count(region)
    start = float(region["start"])
    end = float(region["end"])
    parts = []
    for index in range(count):
        piece_start = start + (end - start) * index / count
        piece_end = start + (end - start) * (index + 1) / count
        if piece_end <= origin or piece_start >= limit:
            continue
        parts.append(
            f'<div class="osl" style="left:{(piece_start - origin) / span * 100:.3f}%;'
            f'width:{(piece_end - piece_start) / span * 100:.3f}%">旧</div>'
        )
    return "".join(parts)


def _detail_html(view: dict, duration: float, playhead: float) -> str:
    from director.confirm_serve import detail_window

    origin, limit = detail_window(playhead, duration, 4.0)
    span = max(0.001, limit - origin)
    active = _item_at(list(view.get("shot_slots") or []), playhead)
    active_id = str(active["slot_id"]) if active else ""
    slots = [
        _with_role(view, slot)
        for slot in view.get("shot_slots") or []
        if float(slot["end"]) > origin and float(slot["start"]) < limit
    ]
    shot_html = "".join(
        _planned_slot_div(
            slot,
            duration,
            zoom=(origin, span),
            active=str(slot.get("slot_id")) == active_id,
            hair=index > 0 or float(slot["start"]) > 1e-6,
            alt=not slot.get("flurry_group") and index % 2 == 1,
        )
        for index, slot in enumerate(slots)
    )
    shot_html = f'<div class="zrow">{shot_html}{_flurry_brackets(slots, origin, span)}</div>'
    play_left = (playhead - origin) / span * 100
    window_label = f"{origin:.1f}–{limit:.1f}s"
    return (
        '<section class="zoom" id="zoom">'
        '<h3 id="detail-title">局部细节 · 跟随播放头 · 前后 4 秒 '
        f'<small id="detail-range">{html.escape(window_label)}</small></h3>'
        f'<p class="note" id="export-note">{html.escape(EXPORT_PAGE_NOTE)} '
        "拖动这一条也可以挪播放头。"
        '<label class="note"><input type="checkbox" id="compare-old"> 对比旧版</label></p>'
        f'<div class="zlane" id="zoom-lane" data-origin="{origin:.6f}" data-limit="{limit:.6f}">'
        f'{_detail_ticks(view, origin, limit, span)}{shot_html}'
        f'<div class="zph" style="left:{play_left:.3f}%"></div></div>'
        f'{_mark_legend()}'
        f'<p id="detail-contrast">{html.escape(str(view.get("drop_contrast_zh") or ""))}</p>'
        f'<div class="zold" id="compare-row" hidden title="旧：按均长平分">'
        f'{_detail_old_row(view, playhead, origin, limit, span)}</div></section>'
    )


def _offset_text(value: float) -> str:
    rounded = Decimal(str(round(float(value), 6))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{abs(rounded):.2f}"
    if value < 0:
        return f"-{text}"
    return f"+{text}"


def _boundary_anchors(view: dict) -> list[dict]:
    regions = {str(region["region_id"]): region for region in view.get("regions") or []}
    chosen: list[dict] = []
    seen: set[str] = set()
    for anchor in view.get("region_cut_anchors") or []:
        region_id = str(anchor.get("region_id") or "")
        region = regions.get(region_id)
        if region is None or region_id in seen:
            continue
        if abs(float(anchor.get("boundary_s") or 0) - float(region["start"])) > 0.02:
            continue
        seen.add(region_id)
        chosen.append(anchor)
    return chosen


def _snap_chips_html(view: dict, duration: float) -> str:
    if duration <= 0:
        return ""
    blocked = bool(view.get("read_only") and view.get("has_draft"))
    blocked_title = "已经有打开的草稿。先确认或丢弃它，再基于确认版另开。"
    parts = []
    for anchor in _boundary_anchors(view):
        if not anchor.get("pending"):
            continue
        moment = float(anchor["boundary_s"])
        rule = str(anchor.get("rule") or "")
        title = str(anchor.get("explanation_zh") or "")
        if blocked:
            title = blocked_title
        if rule == "beyond_bar":
            label = "超过1小节，不移动"
            button = ""
        elif rule in {"downbeat", "beat"}:
            snapped = float(anchor.get("snapped_s") or moment)
            offset = float(anchor.get("offset_s") or 0)
            label = f"建议 {snapped:.2f}s {_offset_text(offset)}s"
            disabled = " disabled" if blocked else ""
            button = (
                f'<button type="button" data-adopt="{html.escape(str(anchor["region_id"]))}"'
                f'{disabled}>采纳</button>'
            )
        else:
            continue
        parts.append(
            f'<div class="snapchip" style="left:{moment / duration * 100:.3f}%" '
            f'title="{html.escape(title)}">{html.escape(label)}{button}</div>'
        )
    return "".join(parts)


def _adopt_all_html(view: dict) -> str:
    adoptable = [
        anchor
        for anchor in _boundary_anchors(view)
        if anchor.get("pending") and anchor.get("rule") in {"downbeat", "beat"}
    ]
    if not adoptable:
        return ""
    blocked = bool(view.get("read_only") and view.get("has_draft"))
    disabled = " disabled" if blocked else ""
    title = "已经有打开的草稿。先确认或丢弃它，再基于确认版另开。" if blocked else "把还能动的边界都吸到建议的格点上"
    return f'<button type="button" id="adopt-all"{disabled} title="{html.escape(title)}">全部采纳</button>'


def _snap_notes_html(view: dict) -> str:
    items = []
    for anchor in _boundary_anchors(view):
        text = str(anchor.get("explanation_zh") or "").strip()
        if not text:
            continue
        if not anchor.get("pending") and anchor.get("boundary_raw_s") is None:
            continue
        items.append(f"<li>{html.escape(str(anchor['region_id']))} {html.escape(text)}</li>")
    if not items:
        return ""
    return '<div class="sub">边界吸附</div><ul id="snap-notes">' + "".join(items) + "</ul>"


def _slot_panel(view: dict, region: dict, slot: dict | None = None) -> str:
    slots = [slot_row for slot_row in view.get("shot_slots") or [] if slot_row["region_id"] == region["region_id"]]
    if slot is None or str(slot.get("region_id")) != str(region["region_id"]):
        slot = slots[0] if slots else None
    if slot is None:
        body = "<p>这一段还没有镜头建议。</p>"
    else:
        length = float(slot["end"]) - float(slot["start"])
        evidence = slot.get("evidence") or {}
        budget = slot.get("budget_exception") or "在镜长范围内"
        body = (
            f'<p id="slot-when">{html.escape(_mmss(float(slot["start"])))} – '
            f'{html.escape(_mmss(float(slot["end"])))} · {html.escape(_beat_words(slot))} · {length:.3f}s</p>'
            f'<p id="slot-why"><b>为什么切</b> {html.escape(str(slot.get("reason_zh") or ""))}</p>'
            f'<p id="slot-type">建议镜头 {html.escape(str(slot.get("shot_type") or ""))} · '
            f'{html.escape(str(slot.get("reason_code") or ""))}</p>'
            f'<p id="slot-hint">{html.escape(str(slot.get("content_hint") or ""))}</p>'
            + (
                '<p id="slot-best">★ 最好一镜</p>'
                if slot.get("reserve_best")
                else '<p id="slot-best" hidden></p>'
            )
            + (
                f'<p id="slot-seam">{html.escape(str(slot.get("seam_zh") or ""))}</p>'
                if slot.get("seam_zh")
                else '<p id="slot-seam" hidden></p>'
            )
            + f'<p id="slot-budget">预算 {html.escape(str(budget))}</p>'
            f'<p id="slot-evidence">证据 拍 {html.escape(str(evidence.get("beat_ids") or []))}'
            f' · 强拍 {html.escape(str(evidence.get("downbeat_ids") or []))}'
            f' · 乐句 {html.escape(str(evidence.get("phrase_id") or "—"))}'
            f' · 起音 {html.escape(str(evidence.get("onset_ids") or []))}'
            f' · 区段 {html.escape(str(evidence.get("region_id") or ""))}'
            f' · 置信度 {float(slot.get("confidence") or 0):.2f}</p>'
        )
    lines = []
    for item in view.get("regions") or []:
        summary = str(item.get("cut_summary_zh") or "")
        if not summary:
            continue
        lines.append(f"<li>{html.escape(str(item['region_id']))} {html.escape(summary)}</li>")
    legend = "远 远景立地 · 细 细节 · 动 运动/甩镜 · 脸 人脸/反应 · 空 空镜长停 · 转 转场 · ? 待定"
    return (
        '<div id="slot-detail"><div class="sub">选中镜头</div>'
        + body
        + f'<p class="note">{html.escape(EXPORT_PAGE_NOTE)}</p></div>'
        + _snap_notes_html(view)
        + '<div class="sub">各段怎么剪</div><ul id="how-list">'
        + "".join(lines)
        + f'</ul><p class="typelegend">{legend}</p>'
    )


def _legend(kind_labels: dict[str, str]) -> str:
    parts = []
    for role, label in kind_labels.items():
        if role == "unknown":
            swatch = "repeating-linear-gradient(-45deg,#efe4cc 0 3px,#d9c69c 3px 6px)"
        else:
            swatch = ROLE_COLORS.get(role, "#7f9e9c")
        parts.append(f'<span><i style="background:{swatch}"></i>{html.escape(label)}</span>')
    return "".join(parts)


def _warnings_html(view: dict, region: dict) -> str:
    items = []
    if region.get("edit_role") == "unknown":
        proxy = html.escape(str(region.get("musical_proxy") or ""))
        items.append(
            '<div class="w"><span>⚠</span><span>角色还没定：'
            f"分析器没能判断本段功能（musical_proxy = {proxy}）。确认前要指定角色。</span></div>"
        )
    confidence = float(region.get("confidence") or 0)
    if confidence < 0.5:
        items.append(
            f'<div class="w"><span>⚠</span><span>置信度偏低（{confidence:.2f}），建议试听后再确认。</span></div>'
        )
    for item in view.get("warnings") or []:
        items.append(
            '<div class="w info"><span>ⓘ</span><span>文件级：'
            f'{html.escape(str(item.get("label") or ""))} '
            f'<code>{html.escape(str(item.get("code") or ""))}</code></span></div>'
        )
    if not items:
        return '<div class="none">无</div>'
    return "".join(items)


def _list_html(view: dict, kind_labels: dict[str, str]) -> str:
    rows = []
    for region in view["regions"]:
        role = str(region["edit_role"])
        label = str(region.get("kind_label") or kind_labels.get(role, role))
        source = "已修改" if region.get("source") == "user" else "分析"
        rows.append(
            f'<li data-region-id="{html.escape(str(region["region_id"]))}">'
            f'{float(region["start"]):.1f}–{float(region["end"]):.1f} '
            f'{html.escape(label)} 建议镜长 {float(region["suggested_shot_mean_s"]):.1f} '
            f'{html.escape(source)}</li>'
        )
    return (
        '<details id="region-list"><summary>列表视图</summary><ul>'
        + "".join(rows)
        + "</ul></details>"
    )


def _inspector_html(
    view: dict,
    region: dict,
    kind_labels: dict[str, str],
    snap_labels: dict[str, str],
) -> str:
    role = str(region["edit_role"])
    label = str(region.get("kind_label") or kind_labels.get(role, role))
    start = float(region["start"])
    end = float(region["end"])
    length = end - start
    if role == "unknown":
        swatch = "repeating-linear-gradient(-45deg,#efe4cc 0 3px,#d9c69c 3px 6px)"
    else:
        swatch = ROLE_COLORS.get(role, "#7f9e9c")
    if view.get("read_only"):
        select = "<select disabled>" + _role_options(role, kind_labels) + "</select>"
    else:
        select = '<select id="role">' + _role_options(role, kind_labels) + "</select>"
    snap = snap_labels.get(str(region.get("snap_policy")), str(region.get("snap_policy")))
    confidence = float(region.get("confidence") or 0)
    low = " low" if confidence < 0.5 else ""
    count = _slot_count(region)
    slope = float(region.get("energy_slope") or 0)
    slope_text = f"{slope:+.3f}"
    source = "已修改" if region.get("source") == "user" else "分析"
    hint = '<span class="note" id="role-hint" style="color:#b07a2a">请选择</span>' if role == "unknown" else '<span class="note" id="role-hint" hidden>请选择</span>'
    summary = str(region.get("cut_summary_zh") or "")
    if summary:
        slot_line = summary
    else:
        slot_line = (
            f"本段约 {count} 个镜头槽（{length:.1f}s ÷ {float(region['suggested_shot_mean_s']):g}s）"
        )
    return f"""
<div class="col">
  <div class="ih"><span class="sw" id="insp-sw" style="background:{swatch}"></span><b id="insp-role-label">{html.escape(label)}</b><span class="rid" id="insp-rid">{html.escape(str(region["region_id"]))} · {html.escape(role)}</span><span class="sp"></span><span class="note">选中区段</span></div>
  <div class="f"><label>时段</label><div class="ro"><span class="box" id="insp-start">{_mmss(start)}</span>–<span class="box" id="insp-end">{_mmss(end)}</span><span class="note" id="insp-len">{length:.3f} s · 只读</span></div></div>
  <div class="f"><label></label><div class="ro"><span class="note ms">边界拖动：里程碑 B</span></div></div>
  <div class="f"><label>角色</label><div class="ro">{select}{hint}</div></div>
  <div class="acts"><button type="button" class="btn" id="play-span">▶ 播放本段</button><button type="button" class="btn" id="loop-button">⟲ 循环本段</button><label class="note"><input type="checkbox" id="loop"> 循环本段</label></div>
</div>
<div class="col">
  <div class="f"><label>建议镜长</label><div class="v" id="insp-shot">均值 <b>{float(region["suggested_shot_mean_s"]):g}s</b> · 范围 {float(region["shot_min_s"]):g}–{float(region["shot_max_s"]):g}s</div></div>
  <div class="f"><label></label><div class="note" id="insp-slots">{html.escape(slot_line)}</div></div>
  <div class="f"><label>卡点规则</label><div class="v" id="insp-snap">{html.escape(snap)}（{html.escape(str(region.get("snap_policy")))}） <small>snap_policy</small></div></div>
  <div class="f"><label>置信度</label><div class="ro"><div class="cbar{low}" id="insp-cbar"><i id="insp-cbar-i" style="width:{confidence * 100:.0f}%"></i></div><span id="insp-conf">{confidence * 100:.0f}%</span></div></div>
  <div class="sub">分析依据</div>
  <div class="kv"><span>音乐代理</span><span id="insp-proxy">{html.escape(str(region.get("musical_proxy") or ""))}</span><span>平均能量</span><span id="insp-energy">{float(region.get("mean_energy") or 0):.3f}（斜率 {slope_text}）</span><span>运动期望</span><span id="insp-motion">{html.escape(str(region.get("desired_motion") or ""))} · {html.escape(str(region.get("content_need") or ""))}</span><span>来源</span><span id="insp-source">{source}</span></div>
</div>
<div class="col">
  <div class="sub">警告</div>
  <div class="warns" id="insp-warns">{_warnings_html(view, region)}</div>
  {_list_html(view, kind_labels)}
</div>
"""


def _empty_inspector() -> str:
    return """
<div class="col"><div class="ih"><b>还没有分段</b></div><div class="note">边界拖动：里程碑 B</div></div>
<div class="col"><div class="sub">建议镜长</div><div class="note">snap_policy</div><div class="sub">置信度</div></div>
<div class="col"><div class="sub">警告</div><details id="region-list"><summary>列表视图</summary></details></div>
"""


_SIZE_INK = {
    "全": ("#24384a", "#f7f6f1"),
    "远": ("#3d5a73", "#f7f6f1"),
    "中": ("#7f9e9c", "#1c2426"),
    "近": ("#c4a07a", "#1c2426"),
    "特写": ("#d7c2a4", "#1c2426"),
    "细节": ("#efe2cf", "#1c2426"),
}
_STORY_INK = {
    "钩子": ("#c27a62", "#fff"),
    "到达": ("#3f6f78", "#fff"),
    "探索": ("#5f8f62", "#fff"),
    "高潮": ("#a65b6b", "#fff"),
    "回味": ("#c4a45f", "#1c2426"),
    "收尾": ("#6f7f9c", "#fff"),
    "待定": ("#e2d3b1", "#5a4a2a"),
}
_TR_MARK = {
    "whip": "甩",
    "match": "配",
    "zoom": "推",
    "mask": "遮",
    "mask_optional": "遮?",
    "fade": "隐",
    "end": "收",
    "cut": "",
}


def _guide_pixels(start: float, end: float, duration: float) -> float:
    if duration <= 0:
        return 0.0
    return (end - start) / duration * 1200


def _guide_cell(
    start: float,
    end: float,
    duration: float,
    *,
    label: str,
    title: str,
    bg: str,
    fg: str,
    hair: bool,
    slot_id: str,
    region_id: str,
    band: bool = False,
    show_at: float = 18,
) -> str:
    pixels = _guide_pixels(start, end, duration)
    classes = ["gcell"]
    if hair:
        classes.append("hair")
    if band:
        classes.append("gband")
    shown = html.escape(label) if pixels >= show_at and label else ""
    box = _shot_box_style(start, end, 0.0, duration)
    return (
        f'<div class="{" ".join(classes)}" data-guide="1" data-start="{start:.6f}" data-end="{end:.6f}" '
        f'data-slot-id="{html.escape(slot_id)}" data-region-id="{html.escape(region_id)}" '
        f'style="{box};background-color:{bg};color:{fg}" title="{html.escape(title)}">{shown}</div>'
    )


def _guide_brackets(slots: list[dict], duration: float) -> str:
    parts: list[str] = []
    index = 0
    while index < len(slots):
        group = slots[index].get("flurry_group")
        if not group:
            index += 1
            continue
        end_index = index + 1
        while end_index < len(slots) and slots[end_index].get("flurry_group") == group:
            end_index += 1
        start = float(slots[index]["start"])
        end = float(slots[end_index - 1]["end"])
        parts.append(
            f'<div class="guide-run" data-guide-group="{html.escape(str(group))}" '
            f'style="{_span_milli_style(start, end, 0.0, duration)}"><i class="bracket"></i></div>'
        )
        index = end_index
    return "".join(parts)


def _guide_hint(slot: dict) -> str:
    return str(slot.get("content_hint") or "")


def _size_lane(slots: list[dict], duration: float) -> str:
    parts: list[str] = []
    for index, slot in enumerate(slots):
        size = str(slot.get("shot_size") or "")
        bg, fg = _SIZE_INK.get(size, ("#f3f1ea", "#2e3336"))
        title = " · ".join(part for part in (size, _guide_hint(slot)) if part)
        parts.append(
            _guide_cell(
                float(slot["start"]),
                float(slot["end"]),
                duration,
                label=size,
                title=title or "景别",
                bg=bg,
                fg=fg,
                hair=index > 0,
                slot_id=str(slot["slot_id"]),
                region_id=str(slot["region_id"]),
            )
        )
    return "".join(parts) + _guide_brackets(slots, duration)


def _transition_lane(slots: list[dict], duration: float) -> str:
    parts: list[str] = []
    for index, slot in enumerate(slots):
        marks = []
        for key in ("transition_in", "transition_out"):
            mark = _TR_MARK.get(str(slot.get(key) or ""), "")
            if mark and mark not in marks:
                marks.append(mark)
        label = "·".join(marks)
        seam = str(slot.get("seam_zh") or "")
        title = " · ".join(part for part in (label, seam, _guide_hint(slot)) if part)
        bg = "#f6e4dc" if "甩" in marks else "#f7f4ee"
        parts.append(
            _guide_cell(
                float(slot["start"]),
                float(slot["end"]),
                duration,
                label=label,
                title=title or "转场",
                bg=bg,
                fg="#9c2b22" if marks else "#8a8478",
                hair=index > 0,
                slot_id=str(slot["slot_id"]),
                region_id=str(slot["region_id"]),
                show_at=22,
            )
        )
    return "".join(parts) + _guide_brackets(slots, duration)


def _sound_lane(slots: list[dict], duration: float) -> str:
    parts: list[str] = []
    for index, slot in enumerate(slots):
        cues = [str(cue) for cue in (slot.get("sound_cues") or []) if cue]
        if not cues and slot.get("sound_cue"):
            cues = [str(slot["sound_cue"])]
        label = "·".join(cues)
        title = " · ".join(part for part in (label, _guide_hint(slot)) if part)
        parts.append(
            _guide_cell(
                float(slot["start"]),
                float(slot["end"]),
                duration,
                label=label,
                title=title or "声音",
                bg="#f4f1ea",
                fg="#3c4448",
                hair=index > 0,
                slot_id=str(slot["slot_id"]),
                region_id=str(slot["region_id"]),
                show_at=28,
            )
        )
    return "".join(parts) + _guide_brackets(slots, duration)


def _story_lane(slots: list[dict], duration: float) -> str:
    bands: list[dict] = []
    for slot in slots:
        beat = str(slot.get("story_beat") or "待定")
        if bands and bands[-1]["beat"] == beat:
            bands[-1]["end"] = float(slot["end"])
        else:
            bands.append(
                {
                    "beat": beat,
                    "start": float(slot["start"]),
                    "end": float(slot["end"]),
                    "slot_id": str(slot["slot_id"]),
                    "region_id": str(slot["region_id"]),
                    "hint": _guide_hint(slot),
                }
            )
    parts: list[str] = []
    for index, band in enumerate(bands):
        bg, fg = _STORY_INK.get(band["beat"], ("#e7e5de", "#2e3336"))
        title = band["beat"] if not band["hint"] else f'{band["beat"]} · {band["hint"]}'
        parts.append(
            _guide_cell(
                band["start"],
                band["end"],
                duration,
                label=band["beat"],
                title=title,
                bg=bg,
                fg=fg,
                hair=index > 0,
                slot_id=band["slot_id"],
                region_id=band["region_id"],
                band=True,
                show_at=36,
            )
        )
    return "".join(parts)


def _guide_rows_html(view: dict, duration: float) -> str:
    slots = list(view.get("shot_slots") or [])
    if not slots or duration <= 0:
        return ""
    lanes = (
        ("guide-size", "景别", _size_lane(slots, duration)),
        ("guide-transition", "转场", _transition_lane(slots, duration)),
        ("guide-sound", "声音", _sound_lane(slots, duration)),
        ("guide-story", "故事", _story_lane(slots, duration)),
    )
    rows = "".join(
        f'<div class="row r-guide" id="{row_id}"><div class="rh"><b>{label}</b></div>'
        f'<div class="lane">{body}</div></div>'
        for row_id, label, body in lanes
    )
    return f'<div id="guide-rows" hidden>{rows}</div>'


def _music_import_html(music_family: list[dict] | None) -> str:
    options = []
    for item in music_family or []:
        selected = " selected" if item.get("current") else ""
        options.append(
            f'<option value="{html.escape(str(item.get("path") or ""))}"{selected}>'
            f'{html.escape(str(item.get("label") or ""))}</option>'
        )
    picker = ""
    if options:
        picker = (
            f'<label class="ver">配乐 <select id="music-picker">{"".join(options)}</select></label>'
        )
    return (
        '<label class="btn" id="import-music-label" title="只接受本机的 mp3、m4a、wav，不超过 100MB、10 分钟。旧版本会留下来。">'
        "导入 / 换音乐"
        '<input id="import-music" type="file" accept=".mp3,.m4a,.wav" hidden>'
        "</label>"
        '<span id="import-status" class="note"></span>'
        + picker
    )


def render_timeline_page(
    *,
    project_title: str,
    project_id: str,
    project_path: str,
    track_label: str,
    view: dict | None,
    message: str,
    selected: str | None,
    playhead: str | None,
    kind_labels: dict[str, str],
    snap_labels: dict[str, str],
    warning_labels: dict[str, str],
    music_family: list[dict] | None = None,
) -> str:
    """Return the music desk as one HTML document."""

    regions = list((view or {}).get("regions") or [])
    duration = float((view or {}).get("duration_seconds") or 0) or 1.0
    try:
        moment = max(0.0, float(playhead)) if playhead else 0.0
    except ValueError:
        moment = 0.0
    if view and moment > float(view["duration_seconds"]):
        moment = float(view["duration_seconds"])
    at_playhead = _item_at(regions, moment)
    if at_playhead is not None:
        chosen = str(at_playhead["region_id"])
    elif selected and any(str(region["region_id"]) == selected for region in regions):
        chosen = selected
    elif regions:
        chosen = str(regions[0]["region_id"])
    else:
        chosen = ""
    current = next((region for region in regions if str(region["region_id"]) == chosen), None)
    status_word = {"draft": "草稿", "confirmed": "已确认", "history": "历史确认"}.get(
        str((view or {}).get("status") or ""), ""
    )
    count_label = f"{len(regions)} 段" + (f" · {status_word}" if status_word else "")
    bpm = (view or {}).get("bpm")
    bpm_text = f"{float(bpm):.1f}" if isinstance(bpm, (int, float)) else "—"
    beat_count = len((view or {}).get("beats_seconds") or [])
    overall = float((view or {}).get("confidence") or 0)
    provider = html.escape(str((view or {}).get("provider") or "—"))
    schema = html.escape(str((view or {}).get("schema_version") or ""))
    hidden = "" if message else " hidden"
    loop_style = ""
    loop_text = ""
    if current is not None:
        loop_style = _span_style(float(current["start"]), float(current["end"]), duration)
        loop_text = f"循环 {_mmss(float(current['start']))[:7]}–{_mmss(float(current['end']))[:7]}"
    inspector = (
        _inspector_html(view, current, kind_labels, snap_labels)
        if view and current is not None
        else _empty_inspector()
    )
    has_slots = bool(view and view.get("shot_slots"))
    snapshot = str((view or {}).get("snapshot_notice") or "")
    notice_html = (
        f'<p id="snapshot-notice">{html.escape(snapshot)}</p>' if snapshot else ""
    )
    note = str((view or {}).get("beat_backend_note") or "")
    note_html = (
        f'<p id="beat-backend-note" title="{html.escape(note)}">{html.escape(note)}</p>'
        if note
        else ""
    )
    if has_slots and view is not None and current is not None:
        active_slot = _item_at(list(view.get("shot_slots") or []), moment)
        active_id = str(active_slot["slot_id"]) if active_slot else ""
        phrase_row = (
            '<div class="row r-phrase" id="track-phrases"><div class="rh"><b>乐句</b>'
            f'<small>4 小节</small></div><div class="lane">{_phrases_html(view, duration, moment)}</div></div>'
        )
        how_row = (
            '<div class="row r-how" id="track-how"><div class="rh"><b>本段怎么剪</b></div>'
            f'<div class="lane">{_how_html(view, duration, moment)}</div></div>'
        )
        shot_small = "建议 · 按拍，不能拖"
        shot_body = _planned_shots_html(view, duration, active_id)
        style_row = _style_row(view)
        guide_rows = _guide_rows_html(view, duration)
        zoom_html = _detail_html(view, duration, moment)
        guide_button = '<button type="button" id="guide-toggle">展开剪辑思路</button>'
        inspector = inspector.replace(
            '<div class="sub">警告</div>',
            _slot_panel(view, current, active_slot) + '<div class="sub">警告</div>',
            1,
        )
    else:
        phrase_row = ""
        how_row = ""
        style_row = ""
        guide_rows = ""
        shot_small = "（预留·未启用）"
        shot_body = _shots_html(view, duration, chosen) if view else ""
        zoom_html = ""
        guide_button = ""
        active_slot = None
    shot_caption = _shot_caption(active_slot) if active_slot else ""
    body_class = ' class="has-slots"' if has_slots else ""
    import_html = _music_import_html(music_family)
    chrome = _version_chrome(view) if view else (
        '<div class="sp"></div>'
        '<button type="button" class="btn ghost" id="save" disabled>保存草稿</button>'
        '<button type="button" class="btn ghost danger" id="discard" disabled>丢弃草稿</button>'
    )
    data = "null" if view is None else _json_script(view)
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>确认台 · 音乐分段</title>
<script src="/vendor/wavesurfer/wavesurfer.min.js"></script>
<script src="/vendor/wavesurfer/plugins/regions.min.js"></script>
<script src="/vendor/wavesurfer/plugins/timeline.min.js"></script>
<style>{_PAGE_CSS}</style>
</head>
<body{body_class} data-ready="0" data-selected="{html.escape(chosen)}" data-time="{moment:.3f}">
<div class="top">
  <div class="logo"></div>
  <div class="brand">
    <div class="pname" id="project-title">{html.escape(project_title)}</div>
    <div class="psub"><span id="project-name">{html.escape(project_id)}</span> · {html.escape(track_label)} · <span id="hdrdur">{_mmss(float((view or {}).get("duration_seconds") or 0))}</span></div>
  </div>
  <a href="/">项目</a>
  {chrome}
</div>
<section id="error" class="panel"{hidden}>{html.escape(message)}</section>
{notice_html}
<div class="transport">
  {import_html}
  <button type="button" class="btn" id="transport-play" style="width:34px;padding:0">▶</button>
  <label class="note" id="cut-click-label"><input type="checkbox" id="cut-click"> 刀口嗒嗒声</label>
  <div class="tc"><span id="playhead">{_mmss(moment)}</span> <small>/ <span id="duration-readout">{_mmss(float((view or {}).get("duration_seconds") or 0))}</span></small></div>
  <span class="now-shot" id="now-shot">{html.escape(shot_caption)}</span>
  <div class="meta"><span>BPM {bpm_text}</span><span>节拍 {beat_count}</span><span>整体置信度 {overall * 100:.0f}%</span><span>分析器 {provider} · schema {schema}</span></div>
  <div class="sp"></div>
  <div class="legend">{_legend(kind_labels)}</div>
</div>
{note_html}
<div class="tl" id="tl">
  <div class="row r-mark"><div class="rh" style="padding:2px 12px"><small>循环 / 播放头</small></div><div class="lane"></div></div>
  <div class="row r-ruler"><div class="rh"><small>时间 (mm:ss)</small></div><div class="lane"><div id="ruler"></div></div></div>
  <div class="row r-wave" id="track-wave"><div class="rh"><b>音乐轨</b><small>{html.escape(track_label)}</small></div><div class="lane"><div id="wave"></div></div></div>
  <div class="row r-beat"><div class="rh" style="padding:2px 12px"><small>节拍 · 重拍加粗</small></div><div class="lane" id="track-beats">{_beats_html(view, duration) if view else ""}</div></div>
  <div class="row r-reg"><div class="rh"><b>分区轨</b><small id="regcount">{html.escape(count_label)}</small>{_adopt_all_html(view) if view else ""}</div><div class="lane" id="track-regions">{(_blocks_html(view, duration, chosen, kind_labels) + _snap_chips_html(view, duration)) if view else ""}</div></div>
  {phrase_row}
  {style_row}
  <div class="row r-shot" id="track-shots"><div class="rh"><b>镜头轨</b><small>{shot_small}</small></div>{guide_button}<div class="lane" id="shots">{shot_body}</div></div>
  {guide_rows}
  {how_row}
  <div class="ov" id="ov">
    <div class="loopband" id="loopband" hidden style="{loop_style}"><div class="brk l"></div><div class="brk r"></div><div class="loopcap" id="loopcap">{html.escape(loop_text)}</div></div>
    <div class="ph" id="ph" style="left:{moment / duration * 100:.3f}%"><div class="phcap" id="phcap">{_mmss(moment)[:7]}</div></div>
  </div>
</div>
{zoom_html}
<div class="insp" id="insp">{inspector}</div>
<audio id="track" src="/audio/frozen" preload="metadata"></audio>
<script type="application/json" id="desk-data">{data}</script>
<script type="application/json" id="kind-data">{_json_script(kind_labels)}</script>
<script type="application/json" id="snap-data">{_json_script(snap_labels)}</script>
<script type="application/json" id="color-data">{_json_script(ROLE_COLORS)}</script>
<script type="application/json" id="warn-data">{_json_script(warning_labels)}</script>
<script>
var KIND = JSON.parse(document.getElementById("kind-data").textContent);
var SNAP = JSON.parse(document.getElementById("snap-data").textContent);
var COLORS = JSON.parse(document.getElementById("color-data").textContent);
var track = document.getElementById("track");
var state = JSON.parse(document.getElementById("desk-data").textContent);
var selectedId = document.body.getAttribute("data-selected") || null;
var selectedSlotId = null;
try {{
  var slotParam = new URLSearchParams(window.location.search).get("slot");
  if (slotParam) selectedSlotId = slotParam;
}} catch (err) {{}}
function deskUrl(regionId, slotId) {{
  var version = state && state.version_id ? ("version=" + encodeURIComponent(state.version_id) + "&") : "";
  var slot = slotId ? ("&slot=" + encodeURIComponent(slotId)) : "";
  return "/music?" + version + "sel=" + encodeURIComponent(regionId) + slot;
}}
function playbackSpanStep(current, start, end, looping) {{
  var tolerance = 0.08;
  if (current >= end - tolerance) return looping ? "seek" : "pause";
  if (current < start - tolerance) return "seek";
  return "continue";
}}
function clampSeek(seconds, duration) {{
  if (duration < 0) duration = 0;
  if (seconds < 0) return 0;
  if (seconds > duration) return duration;
  return seconds;
}}
function seekFromFraction(fraction, duration) {{
  if (fraction < 0) fraction = 0;
  if (fraction > 1) fraction = 1;
  return clampSeek(fraction * (duration < 0 ? 0 : duration), duration < 0 ? 0 : duration);
}}
function neighborMark(marks, current, step) {{
  var ordered = marks.slice().sort(function (a, b) {{ return a - b; }});
  if (!ordered.length) return current;
  var epsilon = 0.001;
  var index;
  if (step >= 0) {{
    for (index = 0; index < ordered.length; index++) {{
      if (ordered[index] > current + epsilon) return ordered[index];
    }}
    return current;
  }}
  for (index = ordered.length - 1; index >= 0; index--) {{
    if (ordered[index] < current - epsilon) return ordered[index];
  }}
  return current;
}}
function detailWindow(playhead, duration, half) {{
  if (half == null) half = 4;
  if (duration < 0) duration = 0;
  playhead = clampSeek(playhead, duration);
  var windowSpan = half * 2;
  if (windowSpan < 0) windowSpan = 0;
  if (duration <= windowSpan) return [0, duration];
  var start = playhead - windowSpan / 2;
  var end = playhead + windowSpan / 2;
  if (start < 0) return [0, windowSpan];
  if (end > duration) return [duration - windowSpan, duration];
  return [start, end];
}}
var scrubbing = false;
var scrubMoved = false;
var frozenDetail = null;
function loopOn() {{
  var box = document.getElementById("loop");
  return !!(box && box.checked);
}}
function regionAt(seconds) {{
  if (!state || !state.regions || !state.regions.length) return null;
  var regions = state.regions;
  for (var index = 0; index < regions.length; index++) {{
    var start = Number(regions[index].start);
    var end = Number(regions[index].end);
    if (seconds >= start && (seconds < end || (index === regions.length - 1 && seconds <= end))) return regions[index];
  }}
  return null;
}}
function slotAt(seconds) {{
  if (!state || !state.shot_slots || !state.shot_slots.length) return null;
  var slots = state.shot_slots;
  for (var index = 0; index < slots.length; index++) {{
    var start = Number(slots[index].start);
    var end = Number(slots[index].end);
    if (seconds >= start && (seconds < end || (index === slots.length - 1 && seconds <= end))) return slots[index];
  }}
  return null;
}}
function shotCaption(slot) {{
  var id = String(slot.slot_id || "");
  var parts = id.split("-s");
  if (parts.length === 2 && /^[0-9]+$/.test(parts[1])) id = parts[0] + "-s" + String(Number(parts[1]));
  var length = (Number(slot.end) - Number(slot.start)).toFixed(1);
  return "镜头 " + id + " · " + (slot.shot_type || "") + " · " + length + "s";
}}
function musicHref(versionId) {{
  var version = versionId ? ("version=" + encodeURIComponent(versionId) + "&") : "";
  var sel = selectedId ? ("sel=" + encodeURIComponent(selectedId) + "&") : "";
  var when = track && isFinite(track.currentTime) ? track.currentTime : 0;
  return "/music?" + version + sel + "t=" + encodeURIComponent(String(when));
}}
function formatClock(seconds) {{
  if (!isFinite(seconds) || seconds < 0) seconds = 0;
  var minutes = Math.floor(seconds / 60);
  var remain = seconds - minutes * 60;
  var text = remain.toFixed(3);
  if (text.length < 6) text = "0" + text;
  return (minutes < 10 ? "0" : "") + minutes + ":" + text;
}}
function selectedRegion() {{
  if (!state || !state.regions) return null;
  for (var i = 0; i < state.regions.length; i++) {{
    if (state.regions[i].region_id === selectedId) return state.regions[i];
  }}
  return state.regions[0] || null;
}}
function showError(text) {{
  var box = document.getElementById("error");
  if (!box) return;
  box.hidden = !text;
  box.textContent = text || "";
}}
function slotCount(region) {{
  var mean = Number(region.suggested_shot_mean_s) || 1;
  return Math.max(1, Math.round((Number(region.end) - Number(region.start)) / mean));
}}
function paint() {{
  if (!state || !state.regions) return;
  var duration = state.duration_seconds || 1;
  state.regions.forEach(function (region) {{
    var block = document.querySelector('.blk[data-region-id="' + region.region_id + '"]');
    if (!block) return;
    var fraction = (Number(region.end) - Number(region.start)) / duration;
    var classes = ["blk"];
    if (region.edit_role === "unknown") classes.push("unknown", "is-unknown");
    if (region.region_id === selectedId) classes.push("sel");
    if (fraction < 0.065) classes.push("narrow");
    block.className = classes.join(" ");
    block.style.background = region.edit_role === "unknown" ? "" : (COLORS[region.edit_role] || "#7f9e9c");
    var name = block.querySelector(".nm");
    if (name) {{
      name.textContent = region.kind_label || KIND[region.edit_role] || region.edit_role;
      if (region.edit_role === "unknown" && fraction >= 0.055) {{
        var badge = document.createElement("span");
        badge.className = "wb";
        badge.textContent = "⚠";
        name.appendChild(badge);
      }}
    }}
  }});
  document.querySelectorAll(".slotgrp").forEach(function (node) {{
    node.classList.toggle("sel", node.getAttribute("data-region-id") === selectedId);
  }});
  fillInspector();
  fillSlot();
  moveLoop();
  markSpan();
  renderChrome();
}}
function fillInspector() {{
  var region = selectedRegion();
  if (!region) return;
  var role = region.edit_role;
  var label = region.kind_label || KIND[role] || role;
  var swatch = document.getElementById("insp-sw");
  if (swatch) {{
    swatch.style.background = role === "unknown"
      ? "repeating-linear-gradient(-45deg,#efe4cc 0 3px,#d9c69c 3px 6px)"
      : (COLORS[role] || "#7f9e9c");
  }}
  var roleLabel = document.getElementById("insp-role-label");
  if (roleLabel) roleLabel.textContent = label;
  var rid = document.getElementById("insp-rid");
  if (rid) rid.textContent = region.region_id + " · " + role;
  var start = document.getElementById("insp-start");
  var end = document.getElementById("insp-end");
  var len = document.getElementById("insp-len");
  if (start) start.textContent = formatClock(Number(region.start));
  if (end) end.textContent = formatClock(Number(region.end));
  if (len) len.textContent = (Number(region.end) - Number(region.start)).toFixed(3) + " s · 只读";
  var select = document.getElementById("role");
  if (select) select.value = role;
  var hint = document.getElementById("role-hint");
  if (hint) hint.hidden = role !== "unknown";
  var shot = document.getElementById("insp-shot");
  if (shot) shot.innerHTML = "均值 <b>" + region.suggested_shot_mean_s + "s</b> · 范围 " + region.shot_min_s + "–" + region.shot_max_s + "s";
  var slots = document.getElementById("insp-slots");
  if (slots) {{
    if (region.cut_summary_zh) slots.textContent = region.cut_summary_zh;
    else slots.textContent = "本段约 " + slotCount(region) + " 个镜头槽（" + (Number(region.end) - Number(region.start)).toFixed(1) + "s ÷ " + region.suggested_shot_mean_s + "s）";
  }}
  var snap = document.getElementById("insp-snap");
  if (snap) snap.innerHTML = (SNAP[region.snap_policy] || region.snap_policy) + "（" + region.snap_policy + "） <small>snap_policy</small>";
  var conf = Number(region.confidence) || 0;
  var bar = document.getElementById("insp-cbar");
  var bari = document.getElementById("insp-cbar-i");
  var confText = document.getElementById("insp-conf");
  if (bar) bar.className = "cbar" + (conf < 0.5 ? " low" : "");
  if (bari) bari.style.width = (conf * 100).toFixed(0) + "%";
  if (confText) confText.textContent = (conf * 100).toFixed(0) + "%";
  var proxy = document.getElementById("insp-proxy");
  if (proxy) proxy.textContent = region.musical_proxy || "";
  var energy = document.getElementById("insp-energy");
  if (energy) {{
    var slope = Number(region.energy_slope) || 0;
    energy.textContent = Number(region.mean_energy || 0).toFixed(3) + "（斜率 " + (slope >= 0 ? "+" : "") + slope.toFixed(3) + "）";
  }}
  var motion = document.getElementById("insp-motion");
  if (motion) motion.textContent = (region.desired_motion || "") + " · " + (region.content_need || "");
  var source = document.getElementById("insp-source");
  if (source) source.textContent = region.source === "user" ? "已修改" : "分析";
  var warns = document.getElementById("insp-warns");
  if (warns) {{
    warns.textContent = "";
    if (role === "unknown") warns.appendChild(warnBox("角色还没定。确认前要指定角色。", false));
    if (conf < 0.5) warns.appendChild(warnBox("置信度偏低（" + conf.toFixed(2) + "），建议试听后再确认。", false));
    (state.warnings || []).forEach(function (item) {{
      warns.appendChild(warnBox("文件级：" + item.label + " " + item.code, true));
    }});
    if (!warns.childNodes.length) {{
      var none = document.createElement("div");
      none.className = "none";
      none.textContent = "无";
      warns.appendChild(none);
    }}
  }}
}}
function activeSlot() {{
  var region = selectedRegion();
  if (!region || !state || !state.shot_slots) return null;
  var rows = state.shot_slots.filter(function (slot) {{ return slot.region_id === region.region_id; }});
  if (!rows.length) return null;
  for (var i = 0; i < rows.length; i++) {{
    if (rows[i].slot_id === selectedSlotId) return rows[i];
  }}
  return rows[0];
}}
function beatWords(slot) {{
  if (slot.beat_length == null || slot.beat_length === "") return (slot.beats || 0) + " 拍";
  var value = Number(slot.beat_length);
  if (Math.abs(value - 0.5) < 1e-6) return "½拍";
  if (Math.abs(value * 2 - Math.round(value * 2)) < 1e-6 && Math.abs(value - Math.round(value)) > 0.2) {{
    var whole = Math.floor(value);
    return whole ? (whole + "½拍") : "½拍";
  }}
  return String(value) + "拍";
}}
function slotMarks(slot) {{
  var map = {{flash: "闪", ramp_in: "冲", ramp_out: "落", slow: "慢", freeze: "定", whip: "甩", match: "配", zoom: "推", mask: "遮", fade: "隐"}};
  var parts = [];
  if (slot.flash) parts.push(map.flash);
  if (slot.ramp) parts.push(map[slot.ramp] || "变速");
  if (slot.transition && slot.transition !== "cut") parts.push(map[slot.transition] || "转");
  return parts.length ? '<span class="mark">' + parts.join("·") + "</span>" : "";
}}
function fillSlot() {{
  var slot = activeSlot();
  document.querySelectorAll(".sl,.zshot,.gcell").forEach(function (node) {{
    var on = false;
    if (slot && node.classList.contains("gband")) {{
      var bandStart = Number(node.getAttribute("data-start"));
      var bandEnd = Number(node.getAttribute("data-end"));
      on = Number(slot.start) >= bandStart - 1e-4 && Number(slot.start) < bandEnd - 1e-4;
    }} else if (slot) {{
      on = node.getAttribute("data-slot-id") === slot.slot_id;
    }}
    node.classList.toggle("on", on);
  }});
  var idea = document.getElementById("slot-hint");
  if (idea) idea.textContent = slot && slot.content_hint ? slot.content_hint : "";
  var best = document.getElementById("slot-best");
  if (best) {{
    best.hidden = !(slot && slot.reserve_best);
    best.textContent = slot && slot.reserve_best ? "★ 最好一镜" : "";
  }}
  var seam = document.getElementById("slot-seam");
  if (seam) {{
    seam.hidden = !(slot && slot.seam_zh);
    seam.textContent = slot && slot.seam_zh ? slot.seam_zh : "";
  }}
  if (!slot) return;
  var when = document.getElementById("slot-when");
  var why = document.getElementById("slot-why");
  var kind = document.getElementById("slot-type");
  var budget = document.getElementById("slot-budget");
  var evidence = document.getElementById("slot-evidence");
  var info = slot.evidence || {{}};
  if (when) when.textContent = formatClock(Number(slot.start)) + " – " + formatClock(Number(slot.end)) + " · " + beatWords(slot);
  if (why) why.textContent = "为什么切 " + (slot.reason_zh || "");
  if (kind) kind.textContent = "建议镜头 " + (slot.shot_type || "") + " · " + (slot.reason_code || "");
  if (budget) budget.textContent = "预算 " + (slot.budget_exception || "在镜长范围内");
  if (evidence) {{
    evidence.textContent = "证据 拍 " + JSON.stringify(info.beat_ids || [])
      + " · 强拍 " + JSON.stringify(info.downbeat_ids || [])
      + " · 乐句 " + (info.phrase_id || "—")
      + " · 起音 " + JSON.stringify(info.onset_ids || [])
      + " · 区段 " + (info.region_id || "")
      + " · 置信度 " + Number(slot.confidence || 0).toFixed(2);
  }}
}}
function warnBox(text, info) {{
  var node = document.createElement("div");
  node.className = info ? "w info" : "w";
  node.textContent = (info ? "ⓘ " : "⚠ ") + text;
  return node;
}}
function moveLoop() {{
  var region = selectedRegion();
  var band = document.getElementById("loopband");
  var cap = document.getElementById("loopcap");
  var button = document.getElementById("loop-button");
  var on = loopOn();
  if (button) button.classList.toggle("on", on);
  if (!band) return;
  band.hidden = !on;
  if (!region || !on) return;
  var duration = state.duration_seconds || 1;
  band.style.left = (Number(region.start) / duration * 100).toFixed(3) + "%";
  band.style.width = ((Number(region.end) - Number(region.start)) / duration * 100).toFixed(3) + "%";
  if (cap) cap.textContent = "循环 " + formatClock(Number(region.start)).slice(0, 7) + "–" + formatClock(Number(region.end)).slice(0, 7);
}}
function movePlayhead(seconds) {{
  var duration = (state && state.duration_seconds) || 1;
  var line = document.getElementById("ph");
  var cap = document.getElementById("phcap");
  var readout = document.getElementById("playhead");
  if (line) line.style.left = (seconds / duration * 100).toFixed(3) + "%";
  if (cap) cap.textContent = formatClock(seconds).slice(0, 7);
  if (readout) readout.textContent = formatClock(seconds);
}}
function seekAt(seconds) {{
  var duration = (state && state.duration_seconds) || 0;
  seconds = clampSeek(Number(seconds) || 0, duration);
  if (track) {{
    try {{ track.currentTime = seconds; }} catch (err) {{}}
  }}
  movePlayhead(seconds);
  followPlayhead(seconds);
}}
function togglePlay() {{
  if (!track) return;
  if (track.paused) {{
    var playing = track.play();
    if (playing && playing.catch) playing.catch(function () {{}});
  }} else {{
    track.pause();
  }}
}}
function fmtMilli(milli) {{
  var sign = milli < 0 ? "-" : "";
  var value = Math.abs(milli);
  var whole = Math.floor(value / 1000);
  var frac = value - whole * 1000;
  var digits = String(frac);
  while (digits.length < 3) digits = "0" + digits;
  return sign + String(whole) + "." + digits;
}}
function edgeMilli(moment, origin, span) {{
  if (!(span > 0)) return 0;
  return Math.round((Number(moment) - origin) / span * 100000);
}}
function shotBoxStyle(start, end, origin, span) {{
  var left = edgeMilli(start, origin, span);
  var width = edgeMilli(end, origin, span) - left;
  if (width < 0) width = 0;
  return "left:" + fmtMilli(left) + "%;width:calc(" + fmtMilli(width) + "% + 1px)";
}}
function spanMilliStyle(start, end, origin, span) {{
  var left = edgeMilli(start, origin, span);
  var width = edgeMilli(end, origin, span) - left;
  if (width < 0) width = 0;
  return "left:" + fmtMilli(left) + "%;width:" + fmtMilli(width) + "%";
}}
function attrEscape(text) {{
  return String(text == null ? "" : text).replace(/[&<>"]/g, function (ch) {{
    if (ch === "&") return "&amp;";
    if (ch === "<") return "&lt;";
    if (ch === ">") return "&gt;";
    return "&quot;";
  }});
}}
function renderDetail(seconds) {{
  var lane = document.getElementById("zoom-lane");
  if (!lane || !state) return;
  var duration = Number(state.duration_seconds) || 0;
  var win = detailWindow(seconds, duration, 4);
  var origin = win[0];
  var limit = win[1];
  var span = Math.max(0.001, limit - origin);
  lane.setAttribute("data-origin", String(origin));
  lane.setAttribute("data-limit", String(limit));
  var range = document.getElementById("detail-range");
  if (range) range.textContent = origin.toFixed(1) + "–" + limit.toFixed(1) + "s";
  var html = "";
  var downs = state.downbeats_seconds || [];
  var beats = (state.beats_seconds || []).slice();
  downs.forEach(function (moment) {{
    var found = false;
    for (var i = 0; i < beats.length; i++) {{
      if (Math.abs(Number(beats[i]) - Number(moment)) < 0.001) found = true;
    }}
    if (!found) beats.push(moment);
  }});
  beats.forEach(function (moment) {{
    moment = Number(moment);
    if (moment < origin - 1e-6 || moment > limit + 1e-6) return;
    var left = ((moment - origin) / span * 100).toFixed(3);
    var downIndex = 0;
    for (var i = 0; i < downs.length; i++) {{
      if (Math.abs(Number(downs[i]) - moment) < 0.001) downIndex = i + 1;
    }}
    if (downIndex) html += '<div class="beat db" style="left:' + left + '%" title="强拍 ' + downIndex + '"><span class="zlab">' + downIndex + '</span></div>';
    else html += '<div class="beat" style="left:' + left + '%"></div>';
  }});
  var active = slotAt(seconds);
  var lanePx = lane.clientWidth || 1100;
  var shotHtml = "";
  var runs = [];
  (state.shot_slots || []).forEach(function (slot, index) {{
    var start = Number(slot.start);
    var end = Number(slot.end);
    if (end <= origin || start >= limit) return;
    var role = "";
    (state.regions || []).forEach(function (region) {{
      if (region.region_id === slot.region_id) role = region.edit_role;
    }});
    var color = COLORS[role] || "#7f9e9c";
    var pace = slot.pace === "fast" || slot.pace === "hold" ? slot.pace : "med";
    var on = active && slot.slot_id === active.slot_id ? " on" : "";
    var flurry = (slot.flurry_group || slot.pattern_role === "flurry") ? " flurry" : "";
    var hair = index > 0 ? " hair" : "";
    var alt = !slot.flurry_group && slot.shot_type !== "?" && index % 2 === 1 ? " alt" : "";
    var pending = slot.shot_type === "?" ? " pending" : "";
    var type = String(slot.shot_type || "");
    var safe = attrEscape(type);
    var pixels = span > 0 ? (end - start) / span * lanePx : 0;
    var face = "";
    if (pixels >= 14 && safe) face += "<b>" + safe + "</b>";
    if (pixels >= 40) face += "<em>" + (end - start).toFixed(2) + "s</em>";
    if (pixels >= 52) face += slotMarks(slot);
    var tip = type + " · " + (end - start).toFixed(2) + "s";
    if (slot.reason_zh) tip += " · " + slot.reason_zh;
    if (slot.content_hint) tip += " · " + slot.content_hint;
    var bg = pending ? "" : ";background-color:" + color + "8c";
    if (slot.flurry_group) {{
      var last = runs.length ? runs[runs.length - 1] : null;
      if (last && last.id === slot.flurry_group) last.end = end;
      else runs.push({{id: slot.flurry_group, start: start, end: end}});
    }}
    var groupAttr = slot.flurry_group ? ' data-flurry-group="' + attrEscape(slot.flurry_group) + '"' : "";
    shotHtml += '<div class="zshot ' + pace + on + flurry + hair + alt + pending + '" data-slot-id="' + attrEscape(slot.slot_id) + '" data-region-id="' + attrEscape(slot.region_id) + '"' + groupAttr + ' data-start="' + start.toFixed(6) + '" data-end="' + end.toFixed(6) + '" style="' + shotBoxStyle(start, end, origin, span) + bg + '" title="' + attrEscape(tip) + '">' + face + "</div>";
  }});
  runs.forEach(function (run) {{
    shotHtml += '<div class="flurry-run" data-flurry-group="' + attrEscape(run.id) + '" style="' + spanMilliStyle(run.start, run.end, origin, span) + '"><i class="bracket"></i></div>';
  }});
  html += '<div class="zrow">' + shotHtml + "</div>";
  var playLeft = ((seconds - origin) / span * 100).toFixed(3);
  html += '<div class="zph" style="left:' + playLeft + '%"></div>';
  lane.innerHTML = html;
  var old = document.getElementById("compare-row");
  if (old) {{
    var region = regionAt(seconds);
    var oldHtml = "";
    if (region) {{
      var count = slotCount(region);
      var start = Number(region.start);
      var end = Number(region.end);
      for (var index = 0; index < count; index++) {{
        var pieceStart = start + (end - start) * index / count;
        var pieceEnd = start + (end - start) * (index + 1) / count;
        if (pieceEnd <= origin || pieceStart >= limit) continue;
        oldHtml += '<div class="osl" style="left:' + ((pieceStart - origin) / span * 100).toFixed(3) + '%;width:' + ((pieceEnd - pieceStart) / span * 100).toFixed(3) + '%">旧</div>';
      }}
    }}
    old.innerHTML = oldHtml;
  }}
}}
function followPlayhead(seconds) {{
  if (!state || !state.regions) return;
  var region = regionAt(seconds);
  var slot = slotAt(seconds);
  var changed = false;
  if (region && region.region_id !== selectedId) {{
    selectedId = region.region_id;
    document.body.setAttribute("data-selected", selectedId);
    changed = true;
  }}
  if (slot && slot.slot_id !== selectedSlotId) {{
    selectedSlotId = slot.slot_id;
    changed = true;
  }}
  if (!slot && selectedSlotId) {{
    selectedSlotId = null;
    changed = true;
  }}
  document.querySelectorAll(".blk").forEach(function (block) {{
    block.classList.toggle("sel", block.getAttribute("data-region-id") === selectedId);
  }});
  document.querySelectorAll(".slotgrp").forEach(function (node) {{
    node.classList.toggle("sel", node.getAttribute("data-region-id") === selectedId);
  }});
  document.querySelectorAll(".how").forEach(function (node) {{
    node.classList.toggle("on", node.getAttribute("data-region-id") === selectedId);
  }});
  document.querySelectorAll(".phr").forEach(function (node) {{
    var start = Number(node.getAttribute("data-start"));
    var end = Number(node.getAttribute("data-end"));
    node.classList.toggle("on", seconds >= start && seconds < end);
  }});
  if (!frozenDetail) renderDetail(seconds);
  if (changed) {{
    fillInspector();
    moveLoop();
    markSpan();
  }}
  fillSlot();
  var now = document.getElementById("now-shot");
  if (now) now.textContent = slot ? shotCaption(slot) : "";
}}
function renderChrome() {{
  var acceptance = document.getElementById("acceptance");
  var warning = document.getElementById("unknown-warning");
  if (!acceptance || !state) return;
  var ok = state.acceptance && state.acceptance.ok;
  acceptance.className = ok ? "ok" : "bad";
  var ids = (state.acceptance && state.acceptance.unknown_region_ids) || [];
  if (ids.length) acceptance.textContent = "还有 " + ids.length + " 段待定角色";
  else acceptance.textContent = ok ? "验收通过" : "还不能确认";
  var pickUnknown = document.getElementById("pick-unknown");
  if (pickUnknown) pickUnknown.hidden = !ids.length || !!state.read_only;
  if (warning) {{
    if (ids.length) {{
      warning.hidden = false;
      warning.textContent = "这些分段的角色还没定：" + ids.join(", ") + "。普通确认已停用。";
    }} else {{
      warning.hidden = true;
      warning.textContent = "";
    }}
  }}
  var meta = document.getElementById("version-meta");
  if (meta) meta.textContent = (state.source_music_sha8 || "") + " · " + (state.confirmed_at || "尚未确认");
  var picker = document.getElementById("version-picker");
  if (picker && state.versions) {{
    picker.textContent = "";
    state.versions.forEach(function (item) {{
      var option = document.createElement("option");
      option.value = item.version_id;
      option.textContent = item.label;
      option.selected = item.version_id === state.version_id;
      picker.appendChild(option);
    }});
  }}
  var fork = document.getElementById("draft-from-confirmed");
  if (fork) fork.hidden = !(state.read_only && !state.has_draft);
  var save = document.getElementById("save");
  var discard = document.getElementById("discard");
  if (save) save.disabled = !!state.read_only;
  if (discard) discard.disabled = !!state.read_only;
  syncConfirm();
}}
function syncConfirm() {{
  var button = document.getElementById("confirm-version");
  if (!button) return;
  if (!state || state.read_only) {{ button.disabled = true; return; }}
  var forceBox = document.getElementById("force-confirm");
  var reasonBox = document.getElementById("force-reason");
  var force = !!(forceBox && forceBox.checked);
  var reason = reasonBox ? reasonBox.value.trim() : "";
  var blocked = !(state.acceptance && state.acceptance.ok);
  button.disabled = blocked && !(force && reason);
}}
function rolePayload() {{
  return state.regions.map(function (region) {{
    return {{region_id: region.region_id, edit_role: region.edit_role}};
  }});
}}
function postDraft() {{
  if (!state || state.read_only) return Promise.resolve();
  return fetch("/api/regions-draft", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{expected_revision: state.revision, regions: rolePayload()}})
  }}).then(function (response) {{
    return response.json().then(function (data) {{
      if (!response.ok) {{
        showError(data.error || "保存失败");
        return refreshDesk();
      }}
      if (data.shot_slots && data.shot_slots.length && data.version_id) {{
        window.location.href = musicHref(data.version_id);
        return;
      }}
      state = data;
      showError("");
      paint();
    }});
  }});
}}
function refreshDesk() {{
  var version = state && state.version_id ? ("?version=" + encodeURIComponent(state.version_id)) : "";
  return fetch("/api/music-desk" + version).then(function (response) {{ return response.json(); }}).then(function (data) {{
    if (data.error) {{ showError(data.error); return; }}
    state = data;
    showError("");
    paint();
  }});
}}
function playSelected() {{
  var region = selectedRegion();
  if (!region || !track) {{ showError("先点选一段"); return; }}
  showError("");
  seekAt(Number(region.start) || 0);
  var playing = track.play();
  if (playing && playing.catch) playing.catch(function () {{}});
}}
function markSpan() {{
  var plugin = window.__regions;
  var region = selectedRegion();
  if (!plugin || !region || !plugin.addRegion) return;
  if (plugin.clearRegions) plugin.clearRegions();
  plugin.addRegion({{start: Number(region.start), end: Number(region.end), color: "rgba(63,90,99,0.10)", drag:false, resize:false}});
}}
function markReady() {{
  document.body.dataset.ready = "1";
}}
function bootWave() {{
  if (!window.WaveSurfer || !state) {{ markReady(); return; }}
  fetch("/api/" + "wave" + "form-peaks").then(function (response) {{
    if (!response.ok) throw new Error("peaks");
    return response.json();
  }}).then(function (payload) {{
    var regionsPlugin = WaveSurfer.Regions.create();
    var waveHeight = document.body.classList.contains("has-slots") ? 56 : 108;
    var ws = WaveSurfer.create({{
      container: "#wave",
      height: waveHeight,
      waveColor: "#a9b0b3",
      progressColor: "#56646b",
      cursorWidth: 0,
      barWidth: 2,
      barGap: 1,
      barRadius: 1,
      normalize: true,
      interact: false,
      media: track,
      peaks: [payload.peaks],
      duration: state.duration_seconds,
      plugins: [
        regionsPlugin,
        WaveSurfer.Timeline.create({{
          container: "#ruler",
          height: document.body.classList.contains("has-slots") ? 22 : 30,
          timeInterval: 5,
          primaryLabelInterval: 5,
          style: {{color: "#7d8387", fontSize: "11px"}}
        }})
      ]
    }});
    window.__regions = regionsPlugin;
    ws.on("ready", function () {{
      markSpan();
      var t = Number(document.body.getAttribute("data-time")) || 0;
      if (t > 0) ws.setTime(t);
      markReady();
    }});
    ws.on("error", markReady);
  }}).catch(markReady);
}}
if (track) {{
  track.addEventListener("timeupdate", function () {{
    if (scrubbing) return;
    var region = selectedRegion();
    if (region && loopOn()) {{
      var step = playbackSpanStep(track.currentTime, Number(region.start), Number(region.end), true);
      if (step === "seek") track.currentTime = Number(region.start) || 0;
      else if (step === "pause") track.pause();
    }}
    movePlayhead(track.currentTime);
    followPlayhead(track.currentTime);
    maybeCutClick(track.currentTime);
  }});
  track.addEventListener("play", function () {{
    lastCutAt = track.currentTime;
    var button = document.getElementById("transport-play");
    if (button) button.textContent = "❚❚";
  }});
  track.addEventListener("pause", function () {{
    var button = document.getElementById("transport-play");
    if (button) button.textContent = "▶";
  }});
}}
var playSpan = document.getElementById("play-span");
if (playSpan) playSpan.addEventListener("click", playSelected);
var transportPlay = document.getElementById("transport-play");
if (transportPlay) transportPlay.addEventListener("click", togglePlay);
function adoptBlocked() {{
  return !!(state && state.read_only && state.has_draft);
}}
function adoptBoundaries(which) {{
  if (!state) return;
  if (adoptBlocked()) {{
    showError("已经有打开的草稿。先确认或丢弃它，再基于确认版另开。");
    return;
  }}
  fetch("/api/regions-draft/adopt-boundaries", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{
      expected_revision: state.revision,
      version_id: state.version_id,
      boundaries: which
    }})
  }}).then(function (response) {{
    return response.json().then(function (data) {{
      if (!response.ok) {{
        showError(data.error || "采纳失败");
        return;
      }}
      window.location.href = musicHref(data.version_id);
    }});
  }});
}}
var regionLane = document.getElementById("track-regions");
if (regionLane) {{
  regionLane.addEventListener("click", function (event) {{
    var adopt = event.target.closest ? event.target.closest("[data-adopt]") : null;
    if (adopt) {{
      event.stopPropagation();
      adoptBoundaries([adopt.getAttribute("data-adopt")]);
      return;
    }}
    if (event.target.closest && event.target.closest(".snapchip")) {{
      event.stopPropagation();
      return;
    }}
  }});
}}
function pickSlot(event) {{
  if (scrubMoved) return;
  var node = event.target.closest ? event.target.closest("[data-slot-id]") : null;
  if (!node) return;
  var regionId = node.getAttribute("data-region-id");
  var slotId = node.getAttribute("data-slot-id");
  selectedSlotId = slotId;
  if (regionId) {{
    selectedId = regionId;
    document.body.setAttribute("data-selected", selectedId);
  }}
  paint();
  var now = document.getElementById("now-shot");
  var slot = activeSlot();
  if (now) now.textContent = slot ? shotCaption(slot) : "";
}}
var shotLane = document.getElementById("shots");
if (shotLane) shotLane.addEventListener("click", pickSlot);
var guideRows = document.getElementById("guide-rows");
var guideToggle = document.getElementById("guide-toggle");
var guideKey = "travel-director-guide-open";
function setGuideOpen(open) {{
  if (guideRows) guideRows.hidden = !open;
  if (guideToggle) guideToggle.textContent = open ? "收起" : "展开剪辑思路";
  try {{ localStorage.setItem(guideKey, open ? "1" : "0"); }} catch (err) {{}}
}}
if (guideToggle && guideRows) {{
  var storedGuide = false;
  try {{ storedGuide = localStorage.getItem(guideKey) === "1"; }} catch (err) {{}}
  setGuideOpen(storedGuide);
  guideToggle.addEventListener("click", function () {{
    setGuideOpen(!!guideRows.hidden);
  }});
}}
var cutClick = document.getElementById("cut-click");
var cutClickKey = "travel-director-cut-click";
if (cutClick) {{
  try {{ cutClick.checked = localStorage.getItem(cutClickKey) === "1"; }} catch (err) {{}}
  cutClick.addEventListener("change", function () {{
    try {{ localStorage.setItem(cutClickKey, cutClick.checked ? "1" : "0"); }} catch (err) {{}}
  }});
}}
var cutAudio = null;
var lastCutAt = -1;
function playCutClick() {{
  if (!cutClick || !cutClick.checked) return;
  var Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;
  if (!cutAudio) cutAudio = new Ctx();
  if (cutAudio.state === "suspended") cutAudio.resume();
  var osc = cutAudio.createOscillator();
  var gain = cutAudio.createGain();
  osc.frequency.value = 1400;
  gain.gain.setValueAtTime(0.0001, cutAudio.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.12, cutAudio.currentTime + 0.004);
  gain.gain.exponentialRampToValueAtTime(0.0001, cutAudio.currentTime + 0.04);
  osc.connect(gain);
  gain.connect(cutAudio.destination);
  osc.start();
  osc.stop(cutAudio.currentTime + 0.05);
}}
function maybeCutClick(now) {{
  if (!cutClick || !cutClick.checked || !track || track.paused || !state) return;
  var slots = state.shot_slots || [];
  for (var i = 0; i < slots.length; i++) {{
    var start = Number(slots[i].start);
    if (lastCutAt >= 0 && lastCutAt < start && now >= start && now - start < 0.25) {{
      playCutClick();
      break;
    }}
  }}
  lastCutAt = now;
}}
if (guideRows) guideRows.addEventListener("click", pickSlot);
var zoomLane = document.getElementById("zoom");
if (zoomLane) zoomLane.addEventListener("click", pickSlot);
var pickUnknown = document.getElementById("pick-unknown");
if (pickUnknown) {{
  pickUnknown.addEventListener("click", function () {{
    if (!state || state.read_only) return;
    var ids = (state.acceptance && state.acceptance.unknown_region_ids) || [];
    if (!ids.length) return;
    selectedId = ids[0];
    document.body.setAttribute("data-selected", selectedId);
    paint();
    var role = document.getElementById("role");
    if (role && !role.disabled) role.focus();
  }});
}}
var roleSelect = document.getElementById("role");
if (roleSelect) {{
  roleSelect.addEventListener("change", function () {{
    var region = selectedRegion();
    if (!region || (state && state.read_only)) return;
    region.edit_role = roleSelect.value;
    region.kind_label = KIND[roleSelect.value] || roleSelect.value;
    postDraft();
  }});
}}
var adoptAll = document.getElementById("adopt-all");
if (adoptAll) adoptAll.addEventListener("click", function () {{ adoptBoundaries("all"); }});
var saveButton = document.getElementById("save");
if (saveButton) saveButton.addEventListener("click", function () {{ if (state && !state.read_only) postDraft(); }});
var discardButton = document.getElementById("discard");
if (discardButton) {{
  discardButton.addEventListener("click", function () {{
    if (!state || state.read_only || !confirm("丢弃草稿？未锁定的修改会丢掉。")) return;
    fetch("/api/regions-draft/discard", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{expected_revision: state.revision}})
    }}).then(function (response) {{
      return response.json().then(function (data) {{
        if (!response.ok) {{ showError(data.error || "丢弃失败"); return; }}
        return refreshDesk();
      }});
    }});
  }});
}}
var exportButton = document.getElementById("export-fcpxml");
if (exportButton) {{
  exportButton.addEventListener("click", function () {{
    if (!state || !state.read_only) return;
    fetch("/api/regions-export", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{version_id: state.version_id}})
    }}).then(function (response) {{
      return response.json().then(function (data) {{
        if (!response.ok) {{ showError(data.error || "导出失败"); return; }}
        showError("已写出 " + (data.fcpxml || "") + " 。" + (data.notice || ""));
      }});
    }});
  }});
}}
var confirmButton = document.getElementById("confirm-version");
if (confirmButton) {{
  confirmButton.addEventListener("click", function () {{
    if (!state || state.read_only) return;
    var force = document.getElementById("force-confirm").checked;
    var reason = document.getElementById("force-reason").value.trim();
    fetch("/api/regions-draft/confirm", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{expected_revision: state.revision, force: force, reason: reason}})
    }}).then(function (response) {{
      return response.json().then(function (data) {{
        if (!response.ok) {{ showError(data.error || "确认失败"); return; }}
        state = data;
        showError("");
        window.location.href = musicHref(state.version_id);
      }});
    }});
  }});
  var forceBox = document.getElementById("force-confirm");
  var reasonBox = document.getElementById("force-reason");
  if (forceBox) forceBox.addEventListener("change", syncConfirm);
  if (reasonBox) reasonBox.addEventListener("input", syncConfirm);
}}
var picker = document.getElementById("version-picker");
if (picker) {{
  picker.addEventListener("change", function () {{
    window.location.href = musicHref(this.value);
  }});
}}
var fork = document.getElementById("draft-from-confirmed");
if (fork) {{
  fork.addEventListener("click", function () {{
    if (!state) return;
    fetch("/api/regions-draft/from-confirmed", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{version_id: state.version_id}})
    }}).then(function (response) {{
      return response.json().then(function (data) {{
        if (!response.ok) {{ showError(data.error || "另开草稿失败"); return; }}
        window.location.href = musicHref(data.version_id);
      }});
    }});
  }});
}}
function laneFraction(event, node) {{
  if (!node) return 0;
  var rect = node.getBoundingClientRect();
  if (!rect.width) return 0;
  return (event.clientX - rect.left) / rect.width;
}}
function applyPointer(event, node, mode) {{
  if (!state) return;
  var duration = Number(state.duration_seconds) || 0;
  var seconds;
  if (mode === "detail" && frozenDetail) {{
    var fraction = laneFraction(event, node);
    if (fraction < 0) fraction = 0;
    if (fraction > 1) fraction = 1;
    seconds = frozenDetail[0] + fraction * (frozenDetail[1] - frozenDetail[0]);
  }} else {{
    var basis = mode === "playhead" ? document.getElementById("ov") : node;
    seconds = seekFromFraction(laneFraction(event, basis), duration);
  }}
  seekAt(seconds);
}}
function endScrub(event, node, mode) {{
  applyPointer(event, node, mode);
  scrubbing = false;
  frozenDetail = null;
  if (track) followPlayhead(track.currentTime || 0);
  setTimeout(function () {{ scrubMoved = false; }}, 0);
}}
function bindScrub(node, mode) {{
  if (!node) return;
  node.addEventListener("pointerdown", function (event) {{
    if (event.button !== 0) return;
    if (event.target.closest && event.target.closest("button,select,input,textarea,a,.snapchip,[data-adopt]")) return;
    event.preventDefault();
    scrubbing = true;
    scrubMoved = false;
    if (mode === "detail") {{
      frozenDetail = [
        Number(node.getAttribute("data-origin")) || 0,
        Number(node.getAttribute("data-limit")) || 0
      ];
    }}
    if (node.setPointerCapture) node.setPointerCapture(event.pointerId);
    applyPointer(event, node, mode);
  }});
  node.addEventListener("pointermove", function (event) {{
    if (!scrubbing) return;
    if (node.hasPointerCapture && !node.hasPointerCapture(event.pointerId)) return;
    scrubMoved = true;
    applyPointer(event, node, mode);
  }});
  function finish(event) {{
    if (!scrubbing) return;
    if (node.hasPointerCapture && event.pointerId != null && !node.hasPointerCapture(event.pointerId)) return;
    endScrub(event, node, mode);
  }}
  node.addEventListener("pointerup", finish);
  node.addEventListener("pointercancel", finish);
}}
document.addEventListener("keydown", function (event) {{
  var tag = event.target && event.target.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if (!state || !track) return;
  if (event.code === "Space") {{
    event.preventDefault();
    togglePlay();
    return;
  }}
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  var step = event.key === "ArrowRight" ? 1 : -1;
  var marks = state.beats_seconds || [];
  if (event.shiftKey) {{
    marks = [];
    if (state.shot_slots && state.shot_slots.length) {{
      state.shot_slots.forEach(function (slot) {{
        marks.push(Number(slot.start));
        marks.push(Number(slot.end));
      }});
    }} else {{
      marks = state.downbeats_seconds || [];
    }}
  }}
  seekAt(neighborMark(marks, track.currentTime || 0, step));
}});
var stylePicker = document.getElementById("shot-style");
if (stylePicker) {{
  stylePicker.addEventListener("change", function () {{
    if (!state) return;
    var next = stylePicker.value;
    fetch("/api/regions-draft/shot-style", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{
        expected_revision: state.revision,
        version_id: state.version_id,
        style: next
      }})
    }}).then(function (response) {{
      return response.json().then(function (data) {{
        if (!response.ok) {{
          showError(data.error || "换剪法失败");
          stylePicker.value = state.shot_style || "narrative";
          return;
        }}
        window.location.href = musicHref(data.version_id || state.version_id);
      }});
    }});
  }});
}}
var compareOld = document.getElementById("compare-old");
if (compareOld) {{
  compareOld.addEventListener("change", function () {{
    var row = document.getElementById("compare-row");
    if (row) row.hidden = !compareOld.checked;
  }});
}}
var loopButton = document.getElementById("loop-button");
var loopBox = document.getElementById("loop");
if (loopButton && loopBox) {{
  loopButton.addEventListener("click", function () {{
    loopBox.checked = !loopBox.checked;
    moveLoop();
  }});
  loopBox.addEventListener("change", moveLoop);
}}
bindScrub(document.querySelector(".r-ruler .lane"), "timeline");
bindScrub(document.querySelector("#track-wave .lane"), "timeline");
bindScrub(document.getElementById("track-regions"), "timeline");
bindScrub(document.querySelector("#track-phrases .lane"), "timeline");
bindScrub(document.getElementById("shots"), "timeline");
bindScrub(document.getElementById("zoom-lane"), "detail");
bindScrub(document.getElementById("ph"), "playhead");
var importInput = document.getElementById("import-music");
var importStatus = document.getElementById("import-status");
function setImportStatus(text) {{
  if (importStatus) importStatus.textContent = text || "";
}}
function switchMusic(path) {{
  return fetch("/api/project", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{path: path}})
  }}).then(function (response) {{
    return response.json().then(function (data) {{
      if (!response.ok || data.error) {{
        showError((data && data.error) || "没能切换配乐");
        return;
      }}
      window.location.href = "/music";
    }});
  }}).catch(function (err) {{
    showError(String(err));
  }});
}}
function pollImport(jobId) {{
  fetch("/api/music-import/status?id=" + encodeURIComponent(jobId)).then(function (response) {{
    return response.json().then(function (data) {{
      if (data.phase === "失败") {{
        setImportStatus(data.error || data.message || "导入失败");
        return;
      }}
      if (!response.ok) {{
        setImportStatus(data.error || "导入失败");
        return;
      }}
      setImportStatus(data.message || data.phase || "");
      if (data.phase === "完成" && data.project_path) {{
        switchMusic(data.project_path);
        return;
      }}
      setTimeout(function () {{ pollImport(jobId); }}, 700);
    }});
  }}).catch(function (err) {{
    setImportStatus(String(err));
  }});
}}
if (importInput) {{
  importInput.addEventListener("change", function () {{
    var file = importInput.files && importInput.files[0];
    if (!file) return;
    var name = String(file.name || "").toLowerCase();
    if (!(name.endsWith(".mp3") || name.endsWith(".m4a") || name.endsWith(".wav"))) {{
      setImportStatus("只接受 mp3、m4a、wav。");
      importInput.value = "";
      return;
    }}
    setImportStatus("正在上传…");
    var body = new FormData();
    body.append("music", file, file.name);
    fetch("/api/music-import", {{method: "POST", body: body}}).then(function (response) {{
      return response.json().then(function (data) {{
        if (!response.ok || !data.job_id) {{
          setImportStatus(data.error || "导入失败");
          return;
        }}
        setImportStatus(data.message || "正在建立新的音乐版本。");
        pollImport(data.job_id);
      }});
    }}).catch(function (err) {{
      setImportStatus(String(err));
    }});
  }});
}}
var musicPicker = document.getElementById("music-picker");
if (musicPicker) {{
  musicPicker.addEventListener("change", function () {{
    if (musicPicker.value) switchMusic(musicPicker.value);
  }});
}}
setTimeout(markReady, 4000);
if (state) {{
  paint();
  followPlayhead(Number(document.body.getAttribute("data-time")) || 0);
}}
bootWave();
</script>
</body>
</html>
"""
    return page
