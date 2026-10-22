"""Deterministic travel / event shot-track rules (fastcut).

Timing comes only from beats, downbeats, phrases, region edges, and optional
onsets already stored on the desk. No audio read and no model call. The same
desk and style always produce the same slots.

``narrative`` is not planned here. The narrative planner in ``shot_slots``
stays the byte-identical path.

Rule version ``fastcut-0.3`` keeps the 0.2 build→drop ladder and halves the
event establish flurries (0.2 made that section denser than the build).
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

RULES_VERSION = "fastcut-0.3"
EPS = 0.06
MIN_SLOT_S = 0.20
MAX_SAME_RUN = 3
MAX_FLURRY = 4


@dataclass(frozen=True)
class FastCutConfig:
    """Tunables. ``lead_frames`` defaults to 0 so cuts stay on the beat grid."""

    min_slot_s: float = MIN_SLOT_S
    max_same_run: int = MAX_SAME_RUN
    max_flurry: int = MAX_FLURRY
    eps: float = EPS
    lead_frames: int = 0
    frame_rate: float = 30.0

# ---------------------------------------------------------------------------
# 规则表。长度单位 = tick（半拍）。1 = ½拍，2 = 1拍，4 = 2拍，8 = 1小节(4/4)
# 每项：(ticks, role, extra)；extra 可含 ramp / transition / flash
# role: hero 主镜停住 | base 常规 | flurry 快闪组 | bridge 快闪后的运动衔接
#       hit 落点主镜 | ramp_in 冲进下一段 | breath 呼吸 | final 收尾停住 | pickup 弱起
# ---------------------------------------------------------------------------
F = "flurry"


def fl(n, **kw):
    """n 个半拍快闪。"""
    return [(1, F, kw if i == 0 else {}) for i in range(n)]


STYLES = {
    "travel": {
        "label_zh": "旅拍快剪",
        "hook": {"pickup": [(99, "pickup", {"ramp": "ramp_in"})],
                 "bars": [fl(4, flash=True) + [(4, "hero", {"ramp": "ramp_out"})]]},
        "unknown": {"bars": [[(4, "base", {}), (4, "base", {})],
                             [(6, "base", {}), (2, "base", {})],
                             [(8, "base", {})]]},
        "establish": {
            "first": [(8, "hero", {"ramp": "slow"})],
            "mid": [[(4, "base", {}), (4, "base", {})],
                    [(6, "base", {}), (2, "base", {})],
                    [(4, "base", {}), (2, "base", {}), (2, "base", {})]],
            "phrase_last": [(4, "base", {})] + fl(4),
            "region_last": [(6, "base", {}), (2, "ramp_in", {"transition": "match"})],
        },
        # 加速梯：每小节 1→2→2→3→3→3→4 刀，最后一小节是落点前的「吸气」（一个加速长镜 + 甩镜），
        # 故意比前一小节稀，让 drop 的快闪爆发有对比
        "build": {"ladder": [
            [(8, "hero", {})],
            [(4, "base", {}), (4, "base", {})],
            [(6, "base", {}), (2, "base", {})],
            [(4, "base", {}), (2, "base", {}), (2, "base", {})],
            [(2, "base", {}), (4, "base", {}), (2, "base", {})],
            [(3, "base", {}), (3, "base", {}), (2, "base", {})],
            [(4, "base", {})] + fl(2) + [(2, "bridge", {})],
        ], "pre_drop": [(6, "lift", {"ramp": "ramp_in"}), (2, "ramp_in", {"transition": "whip"})]},
        # drop：落点主镜 + 4 刀快闪 + 甩镜（1 小节 6 刀）→ 下一小节整小节主镜慢放（释放）
        "peak_cut": {
            "drop": [(2, "hit", {"flash": True})] + fl(4) + [(2, "bridge", {"transition": "whip"})],
            "release": [(8, "hero", {"ramp": "slow"})],
            "cycle": [[(2, "base", {}), (2, "base", {}), (4, "hero", {})],
                      fl(4) + [(2, "base", {}), (2, "hero", {})],
                      fl(4) + [(4, "bridge", {"transition": "whip"})]],
            "last": [(2, "base", {}), (6, "breath", {"ramp": "slow"})],
        },
        "settle_outro": {"bars": [[(2, "base", {}), (2, "base", {}), (4, "base", {"ramp": "slow"})],
                                  [(8, "hero", {})]],
                         "final": (0, "final", {"transition": "fade"})},
    },
    "event": {
        "label_zh": "活动快剪",
        "hook": {"pickup": [(99, "pickup", {})],
                 "bars": [fl(4, flash=True) + [(2, "base", {}), (2, "base", {"transition": "zoom"})]]},
        "unknown": {"bars": [[(4, "base", {}), (2, "base", {}), (2, "base", {})],
                             [(4, "base", {}), (4, "base", {})],
                             [(2, "base", {}), (2, "base", {}), (4, "base", {})]]},
        # 0.3：铺陈快闪减半。0.2 的 mid fl(2)、乐句末 fl(4)、段末 fl(2) 让铺陈比推进还密。
        "establish": {
            "first": [(4, "hero", {}), (2, "base", {}), (2, "base", {})],
            "mid": [[(4, "base", {})] + fl(1) + [(2, "base", {})],
                    [(2, "base", {}), (2, "base", {}), (4, "base", {})],
                    [(4, "base", {}), (2, "base", {}), (2, "base", {})]],
            "phrase_last": [(2, "base", {})] + fl(2) + [(2, "bridge", {"transition": "zoom"})],
            "region_last": [(4, "base", {})] + fl(1) + [(2, "ramp_in", {"transition": "zoom"})],
        },
        # 加速梯：每小节 2→3→3→4→3→6→5 刀，最后一小节「吸气」：两刀人脸 + 2 拍推镜冲进 drop
        "build": {"ladder": [
            [(4, "base", {}), (4, "base", {})],
            [(4, "base", {}), (2, "base", {}), (2, "base", {})],
            [(2, "base", {}), (4, "base", {}), (2, "base", {})],
            [(4, "hero", {})] + fl(2) + [(2, "base", {})],
            [(2, "base", {}), (2, "base", {}), (4, "base", {})],
            [(2, "base", {})] + fl(4) + [(2, "base", {})],
            [(4, "hero", {})] + fl(4),
        ], "pre_drop": [(2, "base", {}), (2, "base", {}), (4, "lift", {"ramp": "ramp_in", "transition": "zoom"})]},
        # drop：½拍落点闪白 + 4 刀快闪 + 两刀（1 小节 7 刀）→ 定格主镜（全场）；之后高密度维持，整体比推进密
        "peak_cut": {
            "drop": [(1, "hit", {"flash": True, "transition": "zoom"})] + fl(4) + [(1, "base", {}), (2, "base", {})],
            "release": [(4, "hero", {"ramp": "freeze", "flash": True}), (4, "base", {})],
            "cycle": [[(2, "base", {}), (2, "base", {})] + fl(2) + [(2, "base", {})],
                      fl(4) + [(2, "base", {}), (2, "base", {})],
                      [(2, "hero", {})] + fl(4) + [(2, "bridge", {"transition": "zoom"})]],
            "last": [(2, "base", {}), (2, "base", {}), (4, "breath", {})],
        },
        "settle_outro": {"bars": [[(2, "base", {}), (2, "base", {}), (4, "base", {})],
                                  [(4, "base", {}), (4, "hero", {})]],
                         "final": (0, "final", {"transition": "cut"})},
    },
}

# 镜头类型轮换（同一类型不连续出现）
SHOT_CYCLES = {
    "travel": {
        "flurry": ["细", "动", "脸", "细", "动"],
        "base": {"establish": ["细", "脸", "动"], "build": ["动", "细", "脸"],
                 "peak_cut": ["动", "脸", "细"], "settle_outro": ["脸", "细"], "hook": ["细", "动"]},
        "hero": {"establish": "远", "build": "远", "peak_cut": "远", "settle_outro": "远", "hook": "远"},
        "hit": "远", "bridge": "动", "ramp_in": "转", "breath": "空", "final": "空", "pickup": "动", "lift": "动",
    },
    "event": {
        "flurry": ["脸", "动", "细", "脸", "动", "远"],
        "base": {"establish": ["动", "脸", "细"], "build": ["脸", "动", "细"],
                 "peak_cut": ["脸", "动", "细"], "settle_outro": ["脸", "动"], "hook": ["脸", "动"]},
        "hero": {"establish": "远", "build": "脸", "peak_cut": "远", "settle_outro": "远", "hook": "远"},
        "hit": "远", "bridge": "动", "ramp_in": "转", "breath": "脸", "final": "细", "pickup": "动", "lift": "脸",
    },
}

ROLE_ZH = {"hero": "主镜停住", "base": "常规镜", "flurry": "快闪组", "bridge": "快闪后衔接",
           "hit": "落点主镜", "ramp_in": "冲进下一段", "breath": "呼吸镜", "final": "收尾停住",
           "pickup": "弱起开场", "placeholder": "待定占位",
           "lift": "落点前吸气"}
TRIGGER_ZH = {"downbeat": "强拍", "beat": "拍点", "half": "后半拍", "edge": "分区边界", "accent": "重音"}
RAMP_ZH = {"ramp_in": "加速冲刀口", "ramp_out": "落点后由快转慢", "slow": "慢放/升格", "freeze": "定格约半拍"}
TRANS_ZH = {"whip": "甩镜", "match": "匹配剪辑", "zoom": "推镜冲击", "mask": "遮挡", "fade": "渐隐", "cut": "硬切"}
SHOT_HINT = {
    "travel": {"远": "大场景/航拍", "细": "小景别细节", "脸": "人物神情", "动": "运动镜头/有动势",
               "空": "空镜留白", "转": "转场动作（甩/推）", "?": "待定"},
    "event": {"远": "全场/舞台全景", "细": "KV/道具/logo", "脸": "嘉宾或观众反应", "动": "人群流动/互动",
              "空": "场地空镜", "转": "推镜/闪白转场", "?": "待定"},
}


def fmt_beats(b):
    return ("%g" % b).replace("0.5", "½") + "拍" if b != 0.5 else "½拍"


def near(t, arr, eps=EPS):
    return any(abs(t - a) <= eps for a in arr)


def build_grid(beats):
    pts = []
    for i, b in enumerate(beats):
        pts.append((b, "beat"))
        if i + 1 < len(beats):
            pts.append(((b + beats[i + 1]) / 2, "half"))
    return pts


def fit(items, n):
    """把一个小节的模式塞进 n 个 tick：多了从尾部截，少了加长最后一个非快闪镜（或补一个常规镜）。"""
    out = [list(x) for x in items]
    total = sum(x[0] for x in out)
    while total > n and out:
        over = total - n
        if out[-1][0] > over:
            out[-1][0] -= over
            total = n
        else:
            total -= out[-1][0]
            out.pop()
    if total < n:
        if out and out[-1][1] != F:
            out[-1][0] += n - total
        else:
            out.append([n - total, "base", {}])
    return [tuple(x) for x in out]


def tempo_guard(items, half_s, force=False, min_slot_s=MIN_SLOT_S):
    """半拍短于 min_slot_s（约 >150 BPM）时，半拍镜两两合并成 1 拍；落单的并进前一个镜头。"""
    if half_s >= min_slot_s and not force:
        return items
    out, buf = [], []

    def flush():
        while len(buf) >= 2:
            a = buf.pop(0); buf.pop(0)
            out.append((2, a[1], a[2]))
        if buf:
            a = buf.pop()
            if out:
                t, r, x = out[-1]
                out[-1] = (t + 1, r, x)
            else:
                out.append((1, a[1], a[2]))  # 段首落单：下一项会吸收
    for it in items:
        if it[0] == 1:
            buf.append(it)
        else:
            flush()
            if out and out[-1][0] == 1:
                t, r, x = out.pop()
                it = (it[0] + t, r, x)
            out.append(it)
    flush()
    return out


def region_ticks(r, grid, half_s):
    s, e = r["start"], r["end"]
    pts = [s] + [t for t, _ in grid if s + EPS < t < e - EPS] + [e]
    if len(pts) > 2 and pts[1] - pts[0] < 0.4 * half_s:
        pts.pop(1)
    if len(pts) > 2 and pts[-1] - pts[-2] < 0.4 * half_s:
        pts.pop(-2)
    return pts


def plan_region(style, role, r, pts, downbeats, phrase_ends, half_s):
    """返回 [(tick_count, role, extra), ...]，总 tick 数 = len(pts)-1"""
    S = STYLES[style]
    rule = S.get(role) or S["unknown"]
    n_ticks = len(pts) - 1
    db_idx = [i for i, t in enumerate(pts[:-1]) if near(t, downbeats)]
    if not db_idx or db_idx[0] != 0:
        db_idx = [0] + db_idx  # 段首当作一个起点（弱起或边界不在强拍）
    segs = []
    for k, i0 in enumerate(db_idx):
        i1 = db_idx[k + 1] if k + 1 < len(db_idx) else n_ticks
        segs.append((i0, i1))
    has_pickup = not near(pts[0], downbeats)
    plan = []
    if role == "unknown" or role not in S:
        for k, (i0, i1) in enumerate(segs):
            pat = rule["bars"][k % len(rule["bars"])]
            plan += [(t, "placeholder", x) for t, _, x in fit(pat, i1 - i0)]
        return plan
    if role == "settle_outro":
        bars = rule["bars"]
        used = 0
        for k, (i0, i1) in enumerate(segs):
            if k < len(bars) and (n_ticks - i1) >= 4:  # 留至少 2 拍给收尾停住
                plan += fit(bars[k], i1 - i0); used = i1
            else:
                break
        ft, frole, fx = rule["final"]
        plan.append((n_ticks - used, frole, fx))
        return plan
    bar_segs = segs
    if has_pickup and "pickup" in rule:
        i0, i1 = segs[0]
        plan += fit(rule["pickup"], i1 - i0)
        bar_segs = segs[1:]
    nb = len(bar_segs)
    for k, (i0, i1) in enumerate(bar_segs):
        n = i1 - i0
        bar_end = pts[i1]
        if role == "hook":
            pat = rule["bars"][k % len(rule["bars"])]
        elif role == "establish":
            if k == 0:
                pat = rule["first"]
            elif k == nb - 1:
                pat = rule["region_last"]
            elif any(abs(bar_end - pe) <= EPS for pe in phrase_ends):
                pat = rule["phrase_last"]
            else:
                pat = rule["mid"][(k - 1) % len(rule["mid"])]
        elif role == "build":
            L = rule["ladder"]
            if k == nb - 1 and "pre_drop" in rule and nb > 1:
                pat = rule["pre_drop"]  # 最后一小节固定是「吸气」，和 drop 形成对比
            else:
                m = nb - 1 if "pre_drop" in rule and nb > 1 else nb
                idx = 0 if m == 1 else round(k * (len(L) - 1) / (m - 1))
                if m < len(L) and k == m - 1:  # 段短时保证最密的一级一定出现
                    idx = len(L) - 1
                pat = L[idx]
        elif role == "peak_cut":
            has_rel = "release" in rule and nb >= 3
            if k == 0:
                pat = rule["drop"]
            elif k == 1 and has_rel:
                pat = rule["release"]
            elif k == nb - 1 and nb > 1:
                pat = rule["last"]
            else:
                pat = rule["cycle"][(k - (2 if has_rel else 1)) % len(rule["cycle"])]
        else:
            pat = [(n, "base", {})]
        plan += fit(pat, n)
    return plan


def pick_shot(style, role, region_role, prev, counters):
    C = SHOT_CYCLES[style]
    if role == "placeholder":
        return "?"
    if role == F:
        cyc = C["flurry"]
    elif role == "base":
        cyc = C["base"].get(region_role, ["细", "动", "脸"])
    elif role == "hero":
        cyc = [C["hero"].get(region_role, "远")]
    else:
        cyc = [C[role]]
    key = (role, region_role if role == "base" else "")
    i = counters.get(key, 0)
    st = cyc[i % len(cyc)]
    tries = 0
    while st == prev and tries < len(cyc):
        i += 1; tries += 1
        st = cyc[i % len(cyc)]
    if st == prev and len(cyc) == 1:  # 单一类型撞车 → 用备用
        st = {"远": "空", "空": "远", "动": "细", "转": "动", "脸": "动", "细": "动"}.get(st, st)
    counters[key] = i + 1
    return st


def trigger_of(t, region, downbeats, beats, onsets, half_pts):
    if near(t, onsets, 0.03) and (near(t, beats) or near(t, half_pts)):
        return "accent"
    if near(t, downbeats):
        return "downbeat"
    if near(t, beats):
        return "beat"
    if near(t, half_pts):
        return "half"
    return "edge"


def make_reason(style, role, beats_len, trig, shot, ramp, trans, flash, grp):
    parts = [f"{ROLE_ZH.get(role, role)}：{fmt_beats(beats_len)}"]
    if grp:
        parts[0] += f"（第 {grp[0]}/{grp[1]} 刀）"
    parts.append(f"切在{TRIGGER_ZH[trig]}")
    parts.append(f"拍{SHOT_HINT[style].get(shot, shot)}")
    if role == F:
        parts.append("看不清也没关系，只带节奏")
    if role == "bridge":
        parts.append("快闪之后接一个有动势的镜头再回到长镜")
    if role == "lift":
        parts.append("落点前收一口气：比前一小节更稀，让 drop 的快闪更炸")
    if role == "hero" and ramp == "slow":
        parts.append("drop 之后的释放：整段停住看清")
    if flash:
        parts.append("开头加 2–4 帧闪白")
    if ramp:
        parts.append(RAMP_ZH[ramp])
    if trans and trans != "cut":
        parts.append(f"转场：{TRANS_ZH[trans]}")
    return "，".join(parts) + "。"


def _apply_lead(slots, config: FastCutConfig):
    """Move hit and flurry cuts earlier by ``lead_frames`` at ``frame_rate``.

    Both neighbours stay contiguous. Default ``lead_frames`` is 0, so the beat
    grid does not move. A shift that would push either slot under the minimum
    length is skipped.
    """

    if config.lead_frames <= 0 or config.frame_rate <= 0:
        return slots
    shift = config.lead_frames / config.frame_rate
    floor = config.min_slot_s - 1e-6
    for index, slot in enumerate(slots):
        if index == 0 or slot["pattern_role"] not in ("hit", "flurry"):
            continue
        previous = slots[index - 1]
        if previous["region_id"] != slot["region_id"]:
            continue
        new_start = slot["start"] - shift
        if new_start - previous["start"] < floor or slot["end"] - new_start < floor:
            continue
        if new_start <= previous["start"]:
            continue
        previous["end"] = round(new_start, 3)
        previous["length_s"] = round(previous["end"] - previous["start"], 3)
        slot["start"] = previous["end"]
        slot["length_s"] = round(slot["end"] - slot["start"], 3)
    return slots


def generate(desk, style, density="dense", config: FastCutConfig | None = None):
    """density: dense = 默认。standard（半拍镜机械两两合并）只做实验：会造成 1拍×4+ 连续等长，违反变化规则，不要直接上线。"""
    config = config or FastCutConfig()
    beats = desk["beats_seconds"]
    downbeats = desk["downbeats_seconds"]
    onsets_raw = desk.get("onsets_seconds") or desk.get("onsets") or []
    onsets = [o["t"] if isinstance(o, dict) else o for o in onsets_raw]
    if not onsets:  # 退路：desk.json 没落盘 onset 时间，只用现有槽的 accent_at_start 标记
        onsets = [x["start"] for x in desk.get("shot_slots", []) if x.get("accent_at_start")]
    beat_s = statistics.median([b - a for a, b in zip(beats, beats[1:])])
    half_s = beat_s / 2
    grid = build_grid(beats)
    half_pts = [t for t, k in grid if k == "half"]
    phrase_ends = [p["end"] for p in desk.get("phrases", [])]
    slots, counters, prev = [], {}, None
    for r in desk["regions"]:
        role = r["edit_role"]
        pts = region_ticks(r, grid, half_s)
        plan = tempo_guard(
            plan_region(style, role, r, pts, downbeats, phrase_ends, half_s),
            half_s,
            force=(density == "standard"),
            min_slot_s=config.min_slot_s,
        )
        assert sum(p[0] for p in plan) == len(pts) - 1, (style, r["region_id"])
        # 快闪组编号
        groups, gi = [], 0
        for j, p in enumerate(plan):
            if p[1] == F and (j == 0 or plan[j - 1][1] != F):
                gi += 1
            groups.append(gi if p[1] == F else None)
        i = 0
        for j, (nt, prole, extra) in enumerate(plan):
            s, e = pts[i], pts[i + nt]
            i += nt
            blen = round((e - s) / beat_s * 2) / 2
            if prole in ("pickup", "final"):
                blen = round((e - s) / beat_s, 1)
            shot = pick_shot(style, prole, role, prev, counters)
            prev = shot
            trig = trigger_of(s, r, downbeats, beats, onsets, half_pts)
            if j == 0:
                trig = "downbeat" if near(s, downbeats) else "edge"
            gid = groups[j]
            grp = None
            if gid is not None:
                members = [k for k, g in enumerate(groups) if g == gid]
                grp = (members.index(j) + 1, len(members))
            ramp = extra.get("ramp")
            trans = extra.get("transition", "cut")
            flash = bool(extra.get("flash"))
            sid = f"{r['region_id']}-{style[0]}{len([x for x in slots if x['region_id']==r['region_id']])+1:02d}"
            slots.append({
                "slot_id": sid, "region_id": r["region_id"], "region_role": role,
                "start": round(s, 3), "end": round(e, 3), "length_s": round(e - s, 3),
                "beats": blen, "shot_type": shot, "pattern_role": prole,
                "cut_on": trig, "flurry_group": f"{r['region_id']}-g{gid}" if gid else None,
                "ramp": ramp, "transition": trans, "flash": flash,
                "reason_code": f"{style.upper()}_{role.upper()}_{prole.upper()}",
                "reason_zh": make_reason(style, prole, blen, trig, shot, ramp, trans, flash, grp),
                "source": "rules", "rules_version": RULES_VERSION,
                "style": style,
            })
    return _apply_lead(slots, config), beat_s


def validate(slots, desk, beat_s, config: FastCutConfig | None = None):
    config = config or FastCutConfig()
    issues = []
    for a, b in zip(slots, slots[1:]):
        if abs(a["end"] - b["start"]) > 1e-6:
            issues.append(f"gap {a['slot_id']}->{b['slot_id']}")
        if a["shot_type"] == b["shot_type"] and a["shot_type"] != "?":
            issues.append(f"same_type {a['slot_id']},{b['slot_id']}")
    if abs(slots[0]["start"]) > 1e-6 or abs(slots[-1]["end"] - desk["duration_seconds"]) > 1e-3:
        issues.append("coverage")
    run, runs = 1, []
    for a, b in zip(slots, slots[1:]):
        if b["beats"] == a["beats"] and not (a["flurry_group"] and a["flurry_group"] == b["flurry_group"]):
            run += 1
            if run > config.max_same_run:
                runs.append(b["slot_id"])
        else:
            run = 1
    if runs:
        issues.append(f"same_length_run>{config.max_same_run}: {runs}")
    groups = {}
    for x in slots:
        if x["flurry_group"]:
            groups.setdefault(x["flurry_group"], []).append(x)
    long_groups = [g for g, xs in groups.items() if len(xs) > config.max_flurry]
    if long_groups:
        issues.append(f"flurry_group>{config.max_flurry}: {long_groups}")
    short = [s["slot_id"] for s in slots if s["length_s"] < config.min_slot_s - 1e-6]
    if short:
        issues.append(f"too_short: {short}")
    return issues


def stats(slots, desk, beat_s):
    bar_s = beat_s * 4
    out = {}
    for r in desk["regions"]:
        ss = [s for s in slots if s["region_id"] == r["region_id"]]
        if not ss:
            continue
        L = [s["beats"] if "beats" in s else 0 for s in ss]
        dur = r["end"] - r["start"]
        dbs = [d for d in desk["downbeats_seconds"] if r["start"] - EPS <= d < r["end"] - EPS]
        if not dbs or abs(dbs[0] - r["start"]) > EPS:
            dbs = [r["start"]] + dbs
        edges = dbs + [r["end"]]
        bar_cuts = [sum(1 for s in ss if edges[i] - EPS <= s["start"] < edges[i + 1] - EPS) for i in range(len(dbs))]
        out[r["region_id"]] = {
            "role": r["edit_role"], "dur_s": round(dur, 2), "count": len(ss),
            "min_beats": min(L), "median_beats": statistics.median(L), "max_beats": max(L),
            "mean_beats": round(statistics.mean(L), 2),
            "cuts_per_bar": round(len(ss) / (dur / bar_s), 2),
            "flurry_slots": sum(1 for s in ss if s.get("pattern_role") == F),
            "flash": sum(1 for s in ss if s.get("flash")),
            "ramps": sum(1 for s in ss if s.get("ramp")),
            "transitions": sum(1 for s in ss if s.get("transition") not in (None, "cut")),
            "bar_cuts": bar_cuts,
            "first_bar_cuts": bar_cuts[0], "last_bar_cuts": bar_cuts[-1],
            "longest_hold_beats_first2bars": max(s["beats"] for s in ss if s["start"] < edges[min(2, len(dbs))] - EPS),
        }
    return out


_SECTION_ZH = {
    "hook": "开场",
    "unknown": "待定",
    "establish": "铺陈",
    "narrative_hold": "叙事",
    "build": "推进",
    "peak_cut": "高潮",
    "breath": "换气",
    "settle_outro": "收尾",
}


def region_summary_zh(style, role, stat) -> str:
    """One line for 本段怎么剪. Markers are editing suggestions, not footage claims."""

    label = STYLES[style]["label_zh"]
    name = _SECTION_ZH.get(role, role)
    bits = [f"{label} · {name}", f"{stat['count']} 镜", f"{stat['cuts_per_bar']} 刀/小节"]
    if stat.get("flurry_slots"):
        bits.append(f"快闪 {stat['flurry_slots']}")
    if stat.get("flash"):
        bits.append("有闪白")
    if stat.get("ramps"):
        bits.append("有变速")
    if stat.get("transitions"):
        bits.append("有转场")
    return "，".join(bits) + "。"


def drop_contrast(st, build="r04", peak="r05"):
    """build→drop 对比指标：整体密度比、落点小节 vs 推进最后一小节、推进前后半段（不含吸气小节）是否在加速。"""
    b, p = st[build], st[peak]
    ladder = b["bar_cuts"][:-1]
    h = len(ladder) // 2
    return {
        "peak_vs_build_cuts_per_bar": round(p["cuts_per_bar"] / b["cuts_per_bar"], 2),
        "drop_bar_cuts": p["first_bar_cuts"], "pre_drop_bar_cuts": b["last_bar_cuts"],
        "drop_vs_pre_drop": round(p["first_bar_cuts"] / max(1, b["last_bar_cuts"]), 2),
        "build_first_half_mean": round(statistics.mean(ladder[:h]), 2) if h else None,
        "build_second_half_mean": round(statistics.mean(ladder[h:]), 2) if h else None,
        "release_hold_beats": p["longest_hold_beats_first2bars"],
    }


def main():
    here = Path(__file__).resolve().parent
    desk_path = Path(sys.argv[1]) if len(sys.argv) > 1 else here.parent / "user-track-desk.json"
    outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else here
    desk = json.loads(desk_path.read_text())
    beats = desk["beats_seconds"]
    beat_s = statistics.median([b - a for a, b in zip(beats, beats[1:])])
    summary = {}
    cur = [dict(s, beats=float(s["beats"])) for s in desk["shot_slots"]]
    nst = stats(cur, desk, beat_s)
    summary["narrative"] = {"label_zh": "叙事（现状）", "stats": nst, "drop_contrast": drop_contrast(nst),
                            "validation": validate([dict(s, flurry_group=None, length_s=s["end"] - s["start"]) for s in cur], desk, beat_s)}
    for style in ("travel", "event"):
        slots, _ = generate(desk, style)
        v = validate(slots, desk, beat_s)
        st = stats(slots, desk, beat_s)
        doc = {"style": style, "style_label_zh": STYLES[style]["label_zh"], "rules_version": RULES_VERSION,
               "bpm": desk.get("bpm"), "beat_s": beat_s, "source_music_sha8": desk.get("source_music_sha8"),
               "accent_source": "onsets" if (desk.get("onsets_seconds") or desk.get("onsets")) else "narrative_accent_at_start_flags",
               "slot_count": len(slots), "stats": st, "validation": v, "shot_slots": slots}
        (outdir / f"slots_{style}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        summary[style] = {"label_zh": STYLES[style]["label_zh"], "stats": st, "validation": v,
                          "drop_contrast": drop_contrast(st)}
    (outdir / "stats.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    try:
        from fastcut_preview import render
        render(desk, cur, {st: json.loads((outdir / f"slots_{st}.json").read_text())["shot_slots"] for st in ("travel", "event")}, outdir)
    except ImportError as exc:  # 没装 matplotlib 时只出 JSON
        print("skip preview:", exc)
    for k, v in summary.items():
        print(k, v["label_zh"], "issues:", v["validation"], "drop_contrast:", v.get("drop_contrast"))
        for rid, s in v["stats"].items():
            print("  ", rid, s)


if __name__ == "__main__":
    main()
