"""剪辑思路（creator-0.1）。

镜头时间已经排完之后才跑。只补景别、运动、进出转场、声音、故事位置和一句中文画面建议。
不改 start / end，也不改原来的 transition。

规则来自 Brandon Li、Peter McKinnon、Sam Kolder 的旅拍剪法和常见音效用法，
取舍写在原型 creator-thinking.md。这里把原型的英文代码收成确认台用的中文字段。
活动快剪沿用同一套结构，画面句子改成嘉宾、人群、舞台、全场。
"""

from __future__ import annotations

import hashlib
import json

GUIDE_VERSION = "creator-0.1"
_TIMING_KEYS = ("slot_id", "start", "end")
_PAIRED = ("whip", "match", "zoom")
_POINT_CUES = ("嗖声", "重击")
_CUE_PRIORITY = ("重击", "上升音", "嗖声", "只留音乐", "环境声提前", "环境声延续", "现场声抬起", "跟音乐收")
_MOVING = {"flurry", "bridge", "ramp_in", "lift", "pickup"}
_STORY_ZH = {
    "BIG_BANG": "钩子",
    "TBD": "待定",
    "ARRIVAL": "到达",
    "EXPLORE": "探索",
    "LEFT_TURN": "探索",
    "ANTICIPATION": "探索",
    "CLIMAX_HIT": "高潮",
    "CLIMAX_HOLD": "高潮",
    "CLIMAX": "高潮",
    "AFTERGLOW": "高潮",
    "SOFT_LANDING": "回味",
    "CALLBACK": "收尾",
}


def _seam_zh(guide: dict) -> str | None:
    """How the cut should look. Empty when this slot is a plain cut."""

    direction = guide.get("motion") if guide.get("motion") in {"→", "←"} else "画面方向"
    parts: list[str] = []
    out_kind = guide.get("transition_out")
    in_kind = guide.get("transition_in")
    if out_kind == "whip":
        parts.append(f"出：结尾 4–8 帧向 {direction} 快甩，要有运动模糊")
    elif out_kind == "match":
        parts.append("出：形状、颜色、亮度要相近")
    elif out_kind == "zoom":
        parts.append("出：顺着推近或拉开")
    if in_kind == "whip":
        parts.append("入：开头同向甩入")
    elif in_kind == "match":
        parts.append("入：形状、颜色、亮度要相近")
    elif in_kind == "zoom":
        parts.append("入：顺着上一镜的推拉进来")
    elif in_kind == "mask_optional":
        parts.append("入：可以用遮挡接上")
    if not parts:
        return None
    return "；".join(parts)


def timing_hash(slots: list[dict]) -> str:
    rows = [[slot.get(key) for key in _TIMING_KEYS] for slot in slots]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def infer_pattern(reason: str, shot_type: str, role: str, index: int, establish_hero_taken: bool) -> str:
    """Narrative slots have no pattern_role. Map the existing reason onto the same roles."""

    if shot_type == "?" or reason == "ROLE_UNKNOWN_BAR_GRID":
        return "placeholder"
    if reason == "HOOK_BEAT":
        return "pickup" if index == 0 else "base"
    if reason == "FINAL_HOLD":
        return "final"
    if reason in {"BREATH_HOLD", "PEAK_BREATH_2BEAT", "POST_PEAK_BREATH"}:
        return "breath"
    if reason == "HIT_HOLD":
        return "hit"
    if reason in {"PRE_DROP_WHIP", "SECTION_TRANSITION"}:
        return "ramp_in"
    if reason == "BUILD_RAMP":
        return "lift"
    if reason == "ACCENT_FLURRY":
        return "flurry"
    if role == "establish" and shot_type == "远" and not establish_hero_taken:
        return "hero"
    if reason in {"DOWNBEAT_HOLD", "PHRASE_START"} and shot_type == "远" and role in {
        "peak_cut",
        "settle_outro",
    }:
        return "hero"
    return "base"


def _phrase_idx(moment: float, phrases: list[dict]) -> int:
    for index, phrase in enumerate(phrases):
        if phrase["start"] - 0.06 <= moment < phrase["end"] - 0.06:
            return index
    return -1


def _story_code(slot: dict, region_slots: list[dict], desk: dict) -> str:
    role, pattern = slot["region_role"], slot["pattern_role"]
    if role == "hook":
        return "BIG_BANG"
    if role == "unknown":
        return "TBD"
    if role == "breath":
        return "SOFT_LANDING"
    if role == "narrative_hold":
        return "EXPLORE"
    if role == "establish":
        region = next(item for item in desk["regions"] if item["region_id"] == slot["region_id"])
        midpoint = (float(region["start"]) + float(region["end"])) / 2
        return "ARRIVAL" if slot["start"] < midpoint else "EXPLORE"
    if role == "build":
        return "ANTICIPATION" if pattern in ("lift", "ramp_in") else "LEFT_TURN"
    if role == "peak_cut":
        first_hold = next((index for index, item in enumerate(region_slots) if item["pattern_role"] == "hero"), None)
        index = region_slots.index(slot)
        if first_hold is None or index < first_hold:
            return "CLIMAX_HIT"
        if index == first_hold:
            return "CLIMAX_HOLD"
        return "AFTERGLOW" if pattern == "breath" else "CLIMAX"
    if role == "settle_outro":
        return "CALLBACK" if pattern == "final" else "SOFT_LANDING"
    return "TBD"


def _shot_size(slot: dict, story: str) -> str | None:
    shot_type, pattern = slot["shot_type"], slot["pattern_role"]
    if shot_type == "远":
        wide = pattern == "hit" or (story in ("ARRIVAL", "CLIMAX_HOLD") and pattern == "hero")
        return "全" if wide else "远"
    if shot_type == "空":
        return "远"
    if shot_type in ("动", "转"):
        return "中"
    if shot_type == "脸":
        return "近"
    if shot_type == "细":
        return "特写" if pattern == "flurry" else "细节"
    return None


def _add_cue(guide: dict, cue: str) -> None:
    if cue not in guide["sound_cues"]:
        guide["sound_cues"].append(cue)


def _primary_cue(cues: list[str]) -> str | None:
    for cue in _CUE_PRIORITY:
        if cue in cues:
            return cue
    return cues[0] if cues else None


def _content(style: str, role: str, pattern: str, shot_type: str, story: str, title: bool) -> str:
    event = style == "event"
    if role == "hook":
        lines = {
            "pickup": "开场第一眼：一个有动势的现场局部，不用高潮画面" if event else "开场第一眼：一个有动势的奇特局部，不用高潮画面",
            "flurry": "4 个快闪预告：现场的人和气氛，不剧透高潮" if event else "4 个快闪预告：地点的奇特之处，不剧透高潮",
            "hero": "停住的全场：先让观众知道这是哪一场" if event else "停住的大景：先让观众知道「这是哪里」",
        }
        return lines.get(pattern, "开场")
    if role == "establish":
        if title:
            if event:
                return "场地全貌（舞台 / 全场），后面依次推近到物料和人。标题停在这里，短、对比高，够读两遍。"
            return "地点全貌（航拍 / 大远景），后面依次推近到细节和人。标题停在这里，短、对比高，够读两遍。"
        if pattern == "flurry":
            return "物料和反应快闪：胸牌、举牌、脚步、手，在动作中间切" if event else "细节快闪：招牌、食物、脚步、手，在动作中间切"
        if shot_type == "脸":
            return "人物：嘉宾或观众的反应" if event else "人物：自拍或当地人的反应"
        if shot_type == "细":
            return "细节：物料、手、道具" if event else "细节：材质、手、物件"
        return "走进去：人群流动或跟拍" if event else "走进去：行走 / 交通 / 跟拍"
    if role == "build":
        named = {
            "hero": "推进前的一个全场，停住" if event else "深入前的一个大景，停住",
            "lift": "蓄力：推向舞台或出口的跟拍" if event else "蓄力：向前推进的 POV / 跟拍（奔跑、上楼、出隧道）",
            "ramp_in": "转场动作：甩镜 / 转身 / 穿过前景",
            "flurry": "手部和反应快闪" if event else "手部或脚步 POV 快闪",
            "bridge": "快闪后接一个有动势的镜头",
        }.get(pattern)
        if named:
            return named
        if shot_type == "脸":
            return "嘉宾或观众的反应一瞬" if event else "人物反应 / 自拍一瞬"
        if shot_type == "细":
            return "细节"
        return "行进中的运动镜"
    if role == "peak_cut":
        if pattern == "hit":
            return "全片最好的一镜第一次出现：全场里最清楚的大动作" if event else "全片最好的一镜第一次出现：大动作的大远景"
        if story == "CLIMAX_HOLD":
            return "大景停住：人在场里，让观众看清" if event else "大景慢动作：人在景里，让观众看清"
        if pattern == "flurry":
            return "高能快闪：跳、转身、举手、人群，动作要清楚" if event else "高能快闪：跳、泼水、转身、人群，动作要清楚"
        if pattern == "breath":
            return "空镜换气：舞台边缘 / 观众席 / 场外" if event else "空镜换气：海面 / 天空 / 街道"
        return "高潮里的人物和动作"
    if role == "settle_outro":
        if pattern == "final":
            return "回扣开场：同一舞台或同一动作的另一个时刻" if event else "回扣开场：同一地点 / 同一动作的另一个时刻（比如日落版）"
        return "慢下来：人物神情、回望"
    if role in {"narrative_hold", "breath"}:
        if shot_type == "脸":
            return "人物神情，停一下"
        if shot_type == "细":
            return "细节：材质、手、物件"
        return "慢下来：让这一段自己待一会儿"
    return "开场"


def creator_guidance(slots: list[dict], desk: dict, style: str = "travel") -> list[dict]:
    """Return new slot dicts with guidance fields. Timing keys stay identical."""

    phrases = list(desk.get("phrases") or [])
    out = [dict(slot) for slot in slots]
    before = timing_hash(slots)
    by_region: dict[str, list[dict]] = {}
    for slot in out:
        by_region.setdefault(slot["region_id"], []).append(slot)
    direction = "→"
    directions: dict[str, str] = {}
    for slot in out:
        directions[slot["slot_id"]] = direction
        beats = float(slot.get("beats") or 0)
        if slot.get("pattern_role") in ("hero", "breath", "final") and beats >= 2:
            direction = "←" if direction == "→" else "→"
    guides: list[dict] = []
    for index, slot in enumerate(out):
        story = _story_code(slot, by_region[slot["region_id"]], desk)
        size = _shot_size(slot, story)
        pattern = slot.get("pattern_role")
        guide = {
            "story_code": story,
            "story_beat": _STORY_ZH[story],
            "shot_size": size,
            "motion": None,
            "transition_in": None,
            "transition_out": None,
            "sound_cues": [],
            "content_hint": None,
            "_reserve_best": False,
            "_title": False,
        }
        if slot.get("shot_type") == "?" or pattern == "placeholder":
            guides.append(guide)
            continue
        if pattern in _MOVING or slot.get("shot_type") in ("动", "转"):
            guide["motion"] = directions[slot["slot_id"]]
        elif pattern in ("hero", "hit", "breath", "final"):
            guide["motion"] = "hold"
        else:
            guide["motion"] = "any"
        transition = slot.get("transition") or "cut"
        if transition == "cut" and slot.get("reason_code") == "PRE_DROP_WHIP":
            transition = "whip"
        if pattern == "ramp_in" and transition != "cut":
            guide["transition_out"] = transition
        elif transition not in ("cut", "fade"):
            guide["transition_in"] = transition
        if transition == "fade":
            guide["transition_out"] = "end"
        guides.append(guide)
    for index, slot in enumerate(out):
        guide = guides[index]
        previous = guides[index - 1] if index else None
        nxt = guides[index + 1] if index + 1 < len(out) else None
        if slot.get("transition") == "whip" and slot.get("pattern_role") != "ramp_in" and previous is not None:
            guide["transition_in"] = "whip"
            previous["transition_out"] = "whip"
            _add_cue(guide, "嗖声")
        if guide["transition_out"] == "whip" and nxt is not None and slot.get("pattern_role") == "ramp_in":
            guide["transition_out"] = "whip"
            if nxt["transition_in"] in (None, "whip"):
                nxt["transition_in"] = "whip"
            _add_cue(nxt, "嗖声")
        if guide["transition_out"] == "match" and nxt is not None and nxt["transition_in"] in (None, "match"):
            nxt["transition_in"] = "match"
        if guide["transition_in"] == "zoom" and previous is not None and previous["transition_out"] in (None, "zoom"):
            previous["transition_out"] = "zoom"
        if guide["transition_out"] == "zoom" and nxt is not None and nxt["transition_in"] in (None, "zoom"):
            nxt["transition_in"] = "zoom"
        if (
            previous is not None
            and guide["transition_in"] is None
            and slot.get("pattern_role") in ("base", "hero")
            and out[index - 1].get("pattern_role") in ("base", "hero")
            and slot.get("cut_on") == "downbeat"
            and _phrase_idx(float(slot["start"]), phrases) != _phrase_idx(float(out[index - 1]["start"]), phrases)
            and slot.get("shot_type") != "?"
        ):
            guide["transition_in"] = "mask_optional"
    for index, slot in enumerate(out):
        guide = guides[index]
        previous = guides[index - 1] if index else None
        nxt = guides[index + 1] if index + 1 < len(out) else None
        for kind in _PAIRED:
            if guide["transition_out"] == kind and nxt is not None and nxt["transition_in"] in (None, kind):
                nxt["transition_in"] = kind
            if guide["transition_in"] == kind and previous is not None and previous["transition_out"] in (None, kind):
                previous["transition_out"] = kind
    title_slot = next(
        (
            slot
            for slot in out
            if slot.get("region_role") == "establish" and slot.get("pattern_role") == "hero"
        ),
        None,
    )
    best_given = False
    for index, slot in enumerate(out):
        guide = guides[index]
        pattern = slot.get("pattern_role")
        role = slot.get("region_role")
        shot_type = slot.get("shot_type")
        if shot_type == "?" or pattern == "placeholder":
            guide["content_hint"] = "角色未定，先不给内容建议"
            guide["story_beat"] = "待定"
            continue
        is_title = slot is title_slot
        if is_title:
            guide["_title"] = True
        if role == "peak_cut" and pattern == "hit" and not best_given:
            guide["_reserve_best"] = True
            best_given = True
        guide["content_hint"] = _content(style, str(role), str(pattern), str(shot_type), guide["story_code"], is_title)
        if role == "hook" and pattern == "pickup":
            _add_cue(guide, "环境声提前")
        if role == "hook" and slot.get("flash"):
            _add_cue(guide, "重击")
        if is_title:
            _add_cue(guide, "环境声提前")
        if pattern == "lift":
            _add_cue(guide, "上升音")
        if pattern == "hit" and guide["_reserve_best"]:
            _add_cue(guide, "重击")
        if guide["story_code"] == "CLIMAX_HOLD":
            _add_cue(guide, "只留音乐")
        if pattern == "breath":
            _add_cue(guide, "现场声抬起")
        if pattern == "final":
            _add_cue(guide, "环境声延续")
            _add_cue(guide, "跟音乐收")
    guided: list[dict] = []
    for slot, guide in zip(out, guides):
        row = dict(slot)
        row["shot_size"] = guide["shot_size"]
        row["motion"] = guide["motion"]
        row["transition_in"] = guide["transition_in"]
        row["transition_out"] = guide["transition_out"]
        row["sound_cues"] = list(guide["sound_cues"])
        row["sound_cue"] = _primary_cue(guide["sound_cues"])
        row["story_beat"] = guide["story_beat"]
        row["content_hint"] = guide["content_hint"]
        row["_reserve_best"] = guide["_reserve_best"]
        row["_title"] = guide["_title"]
        row["seam_zh"] = _seam_zh(guide)
        guided.append(row)
    if timing_hash(guided) != before:
        raise RuntimeError("creator guidance changed a slot time")
    for source, row in zip(slots, guided):
        for key in ("start", "end", "slot_id", "beats", "shot_type", "transition", "cut_on", "pattern_role"):
            if key in source and row.get(key) != source.get(key):
                raise RuntimeError(f"creator guidance changed {key} on {source.get('slot_id')}")
    return guided


def validate_guidance(slots: list[dict]) -> list[str]:
    issues: list[str] = []
    for left, right in zip(slots, slots[1:]):
        out_kind = left.get("transition_out")
        in_kind = right.get("transition_in")
        if out_kind in _PAIRED or in_kind in _PAIRED:
            if out_kind != in_kind:
                issues.append(f"pair {left.get('slot_id')}->{right.get('slot_id')} {out_kind}/{in_kind}")
        if in_kind == "mask_optional" and out_kind not in (None, "cut"):
            issues.append(f"mask_optional_blocked {right.get('slot_id')}")
        if out_kind == "end" and in_kind not in (None, "cut"):
            issues.append(f"end_blocked {left.get('slot_id')}")
    for slot in slots:
        cues = list(slot.get("sound_cues") or [])
        if "嗖声" in cues and slot.get("transition_in") not in ("whip", "match"):
            issues.append(f"whoosh_without_transition {slot.get('slot_id')}")
        if slot.get("sound_cue") and slot["sound_cue"] not in cues:
            issues.append(f"sound_cue_missing {slot.get('slot_id')}")
    best = [slot.get("slot_id") for slot in slots if slot.get("_reserve_best")]
    peak_ids = [slot.get("region_id") for slot in slots if slot.get("region_role") == "peak_cut"]
    if peak_ids:
        peak_id = peak_ids[0]
        if len(best) != 1 or not str(best[0]).startswith(str(peak_id)):
            issues.append(f"reserve_best {best}")
    points = sorted(
        float(slot["start"])
        for slot in slots
        for cue in (slot.get("sound_cues") or [])
        if cue in _POINT_CUES
    )
    for index in range(len(points) - 2):
        if points[index + 2] - points[index] < 4.0 - 1e-6:
            window = [
                slot
                for slot in slots
                if points[index] - 1e-6 <= float(slot["start"]) <= points[index + 2] + 1e-6
            ]
            if not any(slot.get("pattern_role") == "hit" for slot in window):
                issues.append(f"sfx_dense@{points[index]}")
                break
    return issues
