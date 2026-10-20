"""Unequal shot slots from the role template, the phrase grid, and accents.

Slots are a suggestion. Region start and end stay where the edit-region
analyzer put them. Cut times snap to a downbeat or a beat only inside the
slot list and the cut anchors.
"""

from __future__ import annotations

from dataclasses import dataclass

from director.music_edit_regions_schema import (
    MusicEditRegion,
    MusicEditRegions,
    RegionCutAnchor,
    ShotSlot,
    SlotEvidence,
)
from director.schema import BeatEvent, OnsetEvent


FRAME = 1.0 / 30.0
_MANAGED_WARNINGS = {
    "meter_assumed_4_4",
    "downbeat_phase_heuristic",
    "beat_grid_gaps",
    "boundary_snapped",
    "slot_budget_exception",
}
_DOWNBEAT_REASONS = {
    "PHRASE_START",
    "DOWNBEAT_HOLD",
    "DOWNBEAT_CUT",
    "LONG_SHORT",
    "ROLE_UNKNOWN_BAR_GRID",
    "POST_PEAK_BREATH",
    "BUILD_RAMP",
    "PRE_DROP_WHIP",
    "HIT_HOLD",
    "SECTION_TRANSITION",
    "PHRASE_REGULAR",
    "FINAL_HOLD",
    "PEAK_DECEL",
}
_REGULAR_REASONS = {"HOOK_BEAT", "DOWNBEAT_CUT", "DOWNBEAT_HOLD", "PHRASE_START", "PEAK_BREATH_2BEAT", "PEAK_DECEL"}


def _r3(value: float) -> float:
    return round(float(value), 3)


def _cv(lengths: list[float]) -> float:
    if len(lengths) < 2:
        return 0.0
    mean = sum(lengths) / len(lengths)
    if mean <= 1e-9:
        return 0.0
    var = sum((item - mean) ** 2 for item in lengths) / len(lengths)
    return var ** 0.5 / mean


def _text(code: str, beats: int) -> str:
    n = max(0, beats)
    sentences = {
        "HOOK_BEAT": f"开场按拍下刀，这一刀隔 {n} 拍，落在拍点上。",
        "PHRASE_START": f"乐句从强拍开始，这一镜走 {n} 拍。",
        "DOWNBEAT_HOLD": f"在强拍上换镜，这一镜留 {n} 拍。",
        "LONG_SHORT": f"这一刀故意改成 {n} 拍，避免整段镜头一样长。",
        "SECTION_TRANSITION": f"段尾留 {n} 拍做转场，再进下一段。",
        "DOWNBEAT_CUT": f"每小节在强拍上切一刀，这一镜 {n} 拍。",
        "BUILD_RAMP": f"进高潮前加快，这一镜只留 {n} 拍。",
        "PRE_DROP_WHIP": f"最后 {n} 拍用甩镜冲进高潮。",
        "HIT_HOLD": f"重音或乐句起点先停 {n} 拍，再往下切。",
        "ACCENT_FLURRY": f"这一小节重音够密，按 1 拍切，这一镜 {n} 拍。",
        "PEAK_BREATH_2BEAT": f"高潮里留 {n} 拍喘气，不要连着密剪。",
        "PEAK_DECEL": f"高潮最后一小节放慢，这一镜 {n} 拍。",
        "POST_PEAK_BREATH": f"高潮刚过，先停 {n} 拍换气。",
        "FINAL_HOLD": "最后一个镜头停到这段结束，不再切。",
        "BREATH_HOLD": "这一段是换气，整段一个镜头停住。",
        "ROLE_UNKNOWN_BAR_GRID": "角色还没定，先按小节占位，确认后再重排。",
        "GRID_GAP_ONSET": "这里拍点断了，刀口改落在够强的起音上。",
        "PHRASE_REGULAR": "这段按乐句等长换镜，所以各镜头一样长。",
    }
    return sentences[code]


def _summary(role: str, codes: set[str]) -> str:
    if role == "hook":
        return "开场跟着拍点切，短镜头轮换，先动再收到细节和人脸。"
    if role == "establish":
        return "前奏按乐句走，大约两小节一个镜头，段尾留一刀转场。"
    if role == "narrative_hold":
        return "叙事段在强拍上换镜，镜头偏长，长短交替。"
    if role == "build":
        if "BUILD_RAMP" in codes or "PRE_DROP_WHIP" in codes:
            return "铺垫每小节一刀往前推；进高潮前两小节加快，最后一拍甩进去。"
        return "铺垫每小节一刀，在强拍上往前推。"
    if role == "peak_cut":
        return "高潮先在乐句起点停一下，密剪和两拍喘气交替，段尾减速。"
    if role == "breath":
        return "这一段是换气，一个镜头停住，不要切。"
    if role == "settle_outro":
        return "收尾先留一个长镜头换气，最后一个镜头停到本段结束。"
    return "角色未定：先按小节占位，确认角色后再排。不给镜头建议。"


def _fit_count(prefer: int, period: float, shot_min: float, shot_max: float) -> int:
    count = max(1, prefer)
    while count > 1 and count * period > shot_max + FRAME:
        count -= 1
    return count


def _nearest(times: list[float], moment: float) -> float | None:
    if not times:
        return None
    return min(times, key=lambda item: abs(item - moment))


def _snap(moment: float, duration: float, downbeats: list[float], beats: list[float], period: float, prefer: bool) -> tuple[float, str]:
    if moment <= 0.0005 or abs(moment - duration) <= 0.0005:
        return _r3(moment if moment > 0 else 0.0), "edge"
    half_bar = 2.0 * period
    down = _nearest(downbeats, moment)
    if down is not None and abs(down - moment) <= half_bar + 1e-6:
        return _r3(down), "downbeat"
    limit = period if prefer else period / 2.0
    beat = _nearest(beats, moment)
    if beat is not None and abs(beat - moment) <= limit + 1e-6:
        return _r3(beat), "beat"
    return _r3(moment), "offbeat_boundary"


@dataclass
class _Piece:
    beats: int
    reason: str
    shot_type: str


@dataclass
class _Draft:
    region_id: str
    start: float
    end: float
    beats: int
    reason: str
    shot_type: str
    accent_at_start: bool = False
    breath_after: bool = False
    budget_exception: str | None = None
    start_beat: int | None = None


def _beats_in(beats: list[BeatEvent], start: float, end: float) -> list[BeatEvent]:
    return [beat for beat in beats if start - 0.02 <= beat.t < end - 0.02]


def _pattern(role: str, span: list[BeatEvent], period: float, region: MusicEditRegion, nxt: MusicEditRegion | None) -> list[_Piece]:
    n = len(span)
    if n <= 0:
        fallback = {
            "hook": ("HOOK_BEAT", "动"),
            "establish": ("DOWNBEAT_HOLD", "远"),
            "narrative_hold": ("DOWNBEAT_HOLD", "空"),
            "build": ("DOWNBEAT_CUT", "动"),
            "peak_cut": ("PEAK_BREATH_2BEAT", "动"),
            "breath": ("BREATH_HOLD", "空"),
            "settle_outro": ("FINAL_HOLD", "空"),
        }.get(role, ("ROLE_UNKNOWN_BAR_GRID", "?"))
        return [_Piece(0, fallback[0], fallback[1])]
    if role == "unknown":
        return _repeat(n, 4, "ROLE_UNKNOWN_BAR_GRID", ["?"])
    if role == "breath":
        return [_Piece(n, "BREATH_HOLD", "空")]
    if role == "hook":
        step = 1 if 2 * period > 1.2 else 2
        step = _fit_count(step, period, region.shot_min_s, region.shot_max_s)
        return _repeat(n, step, "HOOK_BEAT", ["动", "细", "脸"])
    if role == "establish":
        return _establish(n, period, region)
    if role == "narrative_hold":
        return _narrative(n, period, region)
    if role == "build":
        return _build(n, period, region, nxt is not None and nxt.edit_role == "peak_cut")
    if role == "peak_cut":
        return _peak(span, period, region.shot_min_s)
    if role == "settle_outro":
        return _settle(n, period, region)
    return _repeat(n, 4, "ROLE_UNKNOWN_BAR_GRID", ["?"])


def _repeat(n: int, step: int, reason: str, types: list[str]) -> list[_Piece]:
    pieces: list[_Piece] = []
    left = n
    index = 0
    while left > 0:
        count = step if left >= step else left
        pieces.append(_Piece(count, reason, types[index % len(types)]))
        left -= count
        index += 1
    return pieces


def _establish(n: int, period: float, region: MusicEditRegion) -> list[_Piece]:
    step = _fit_count(8, period, region.shot_min_s, region.shot_max_s)
    pieces: list[_Piece] = []
    types = ["远", "细", "脸", "细"]
    reserve = 16 if n >= 16 and step >= 8 else 0
    body = n - reserve
    index = 0
    while body >= step:
        reason = "PHRASE_START" if index % 2 == 0 else "DOWNBEAT_HOLD"
        pieces.append(_Piece(step, reason, types[index % len(types)]))
        body -= step
        index += 1
    if reserve == 16:
        pieces.append(_Piece(8, "PHRASE_START" if index % 2 == 0 else "DOWNBEAT_HOLD", types[index % 4]))
        pieces.append(_Piece(6, "LONG_SHORT", "细"))
        pieces.append(_Piece(2, "SECTION_TRANSITION", "转"))
        body = 0
    left = body
    if left > 2:
        pieces.append(_Piece(left - 2, "DOWNBEAT_HOLD", "细"))
        pieces.append(_Piece(2, "SECTION_TRANSITION", "转"))
    elif left == 2 and pieces:
        pieces.append(_Piece(2, "SECTION_TRANSITION", "转"))
    elif left > 0:
        pieces.append(_Piece(left, "DOWNBEAT_HOLD", "细"))
    return pieces or [_Piece(n, "DOWNBEAT_HOLD", "远")]


def _narrative(n: int, period: float, region: MusicEditRegion) -> list[_Piece]:
    step = _fit_count(8, period, region.shot_min_s, region.shot_max_s)
    short = max(1, step - 2)
    short_ok = short * period >= region.shot_min_s - FRAME
    pieces: list[_Piece] = []
    left = n
    index = 0
    types = ["空", "脸", "细"]
    while left > 0:
        count = step if left >= step else left
        if short_ok and index % 2 == 1 and left >= short and count == step:
            count = short
        reason = "LONG_SHORT" if count != step else ("PHRASE_START" if index % 2 == 0 else "DOWNBEAT_HOLD")
        if left - count < 0:
            count = left
        pieces.append(_Piece(count, reason, types[index % len(types)]))
        left -= count
        index += 1
    return pieces


def _build(n: int, period: float, region: MusicEditRegion, ramp: bool) -> list[_Piece]:
    step = _fit_count(4, period, region.shot_min_s, region.shot_max_s)
    ramp_counts = [2, 2, 1, 1, 1, 1] if ramp and n >= 8 else []
    ramp_n = sum(ramp_counts)
    body = n - ramp_n
    pieces: list[_Piece] = []
    types = ["动", "细", "脸"]
    index = 0
    while body >= step:
        reason = "PHRASE_START" if index == 0 else "DOWNBEAT_CUT"
        pieces.append(_Piece(step, reason, types[index % 3]))
        body -= step
        index += 1
    if body and ramp_counts:
        ramp_counts[0] += body
        body = 0
    elif body:
        pieces.append(_Piece(body, "DOWNBEAT_CUT", types[index % 3]))
    for ramp_index, count in enumerate(ramp_counts):
        last = ramp_index == len(ramp_counts) - 1
        if last:
            pieces.append(_Piece(count, "PRE_DROP_WHIP", "动"))
        else:
            pieces.append(_Piece(count, "BUILD_RAMP", "动" if ramp_index % 2 == 0 else "细"))
    return pieces or [_Piece(n, "DOWNBEAT_CUT", "动")]


def _peak(span: list[BeatEvent], period: float, shot_min: float) -> list[_Piece]:
    one_ok = period >= shot_min - FRAME - 1e-9
    accent_bars = 0
    for start in range(0, len(span), 4):
        if sum(1 for beat in span[start : start + 4] if beat.accent) >= 3:
            accent_bars += 1
    force_short = one_ok and accent_bars == 0 and len(span) >= 8
    pieces: list[_Piece] = []
    flurry_run = 0
    bar_index = 0
    index = 0
    n = len(span)
    while index < n:
        remaining = n - index
        width = min(4, remaining)
        bar = span[index : index + width]
        last = remaining <= 4
        if last and remaining >= 2:
            half = max(1, remaining // 2)
            pieces.append(_Piece(half, "PEAK_DECEL", "脸"))
            if remaining - half:
                pieces.append(_Piece(remaining - half, "PEAK_DECEL", "空"))
            break
        phrase_start = bar_index == 0 or bool(bar and bar[0].is_phrase_start)
        accents = sum(1 for beat in bar if beat.accent)
        consumed = 0
        if phrase_start and width >= 2:
            hold = 1 if 2 * period > 1.4 else min(2, width)
            pieces.append(_Piece(hold, "HIT_HOLD", "远"))
            consumed = hold
        rest = width - consumed
        use_flurry = one_ok and accents >= 3 and flurry_run < 2 and rest > 0 and not last
        use_short = force_short and bar_index == 1 and rest > 0
        if use_flurry or use_short:
            reason = "ACCENT_FLURRY" if use_flurry else "LONG_SHORT"
            for offset in range(rest):
                pieces.append(_Piece(1, reason, "细" if offset % 2 == 0 else "动"))
            flurry_run = flurry_run + 1 if use_flurry else 0
        else:
            while rest >= 2:
                pieces.append(_Piece(2, "PEAK_BREATH_2BEAT", "脸" if rest >= width - consumed else "动"))
                rest -= 2
            if rest:
                kind = "动" if one_ok else "脸"
                pieces.append(_Piece(rest, "PEAK_BREATH_2BEAT", kind))
            flurry_run = 0
        index += width
        bar_index += 1
    return pieces or [_Piece(n, "PEAK_BREATH_2BEAT", "动")]


def _settle(n: int, period: float, region: MusicEditRegion) -> list[_Piece]:
    step = _fit_count(8, period, region.shot_min_s, region.shot_max_s)
    if n <= step:
        return [_Piece(n, "FINAL_HOLD", "空")]
    pieces = [_Piece(step, "POST_PEAK_BREATH", "空")]
    left = n - step
    while left > step:
        pieces.append(_Piece(step, "DOWNBEAT_HOLD", "空"))
        left -= step
    pieces.append(_Piece(left, "FINAL_HOLD", "空"))
    return pieces


def _materialize(
    region: MusicEditRegion,
    start: float,
    end: float,
    beats: list[BeatEvent],
    pieces: list[_Piece],
) -> list[_Draft]:
    span = _beats_in(beats, start, end)
    drafts: list[_Draft] = []
    cursor = start
    beat_cursor = 0
    for piece_index, piece in enumerate(pieces):
        last = piece_index == len(pieces) - 1
        cut = end
        start_beat = span[beat_cursor].i if beat_cursor < len(span) else None
        if not last and piece.beats > 0 and beat_cursor + piece.beats < len(span):
            cut = span[beat_cursor + piece.beats].t
            if cut >= end - 0.02:
                cut = end
        elif not last and piece.beats > 0 and beat_cursor + piece.beats == len(span):
            cut = end
        cut = end if last or cut >= end - 0.02 else cut
        cut = _r3(cut)
        if cut <= cursor + 0.0005:
            beat_cursor += max(0, piece.beats)
            continue
        accent = False
        if start_beat is not None:
            beat = next(item for item in beats if item.i == start_beat)
            accent = bool(beat.accent and abs(beat.t - cursor) <= 0.03)
        drafts.append(
            _Draft(
                region_id=region.region_id,
                start=_r3(cursor),
                end=cut,
                beats=piece.beats,
                reason=piece.reason,
                shot_type=piece.shot_type,
                accent_at_start=accent,
                start_beat=start_beat,
            )
        )
        cursor = cut
        beat_cursor += max(0, piece.beats)
        if cursor >= end - 0.0005:
            break
    if not drafts:
        reason = "ROLE_UNKNOWN_BAR_GRID" if region.edit_role == "unknown" else "DOWNBEAT_HOLD"
        kind = "?" if region.edit_role == "unknown" else "空"
        drafts.append(
            _Draft(
                region.region_id,
                _r3(start),
                _r3(end),
                len(span),
                reason,
                kind,
                start_beat=span[0].i if span else None,
            )
        )
    elif drafts[-1].end < end - 0.0005:
        drafts[-1].end = _r3(end)
    drafts[0].start = _r3(start)
    drafts[-1].end = _r3(end)
    return [item for item in drafts if item.end > item.start + 0.0005]


def _absorb_short_tail(
    drafts: list[_Draft],
    region: MusicEditRegion,
    nxt: MusicEditRegion | None,
    period: float,
) -> list[_Draft]:
    """Fold a trailing fragment under shot_min into the previous slot when it still fits."""

    if len(drafts) < 2:
        return drafts
    tail = drafts[-1]
    previous = drafts[-2]
    length = tail.end - tail.start
    if length + 1e-9 >= region.shot_min_s - FRAME:
        return drafts
    if _exception(tail, region, nxt, period):
        return drafts
    if tail.end - previous.start > region.shot_max_s + FRAME:
        return drafts
    previous.end = tail.end
    previous.beats += tail.beats
    if tail.reason == "FINAL_HOLD":
        previous.reason = "FINAL_HOLD"
        previous.shot_type = tail.shot_type
    return drafts[:-1]


def _exception(draft: _Draft, region: MusicEditRegion, nxt: MusicEditRegion | None, period: float) -> str | None:
    length = draft.end - draft.start
    if region.shot_min_s - FRAME <= length <= region.shot_max_s + FRAME:
        return None
    floor = nxt.shot_min_s if nxt is not None else region.shot_min_s
    if draft.reason in {"BUILD_RAMP", "PRE_DROP_WHIP"} and length + 1e-9 >= floor - FRAME:
        return "below_min_ramp"
    if draft.reason == "SECTION_TRANSITION" and length + 1e-9 >= period - FRAME:
        return "below_min_transition"
    return None


def _mark_regular(drafts: list[_Draft], role: str) -> None:
    if role == "unknown" or len(drafts) < 4:
        return
    lengths = [item.end - item.start for item in drafts]
    need = 0.25 if role == "peak_cut" and len(drafts) >= 8 else 0.15
    if _cv(lengths) + 1e-9 >= need:
        return
    if role == "peak_cut" and len(drafts) >= 8:
        return
    if any(item.reason not in _REGULAR_REASONS for item in drafts):
        return
    for item in drafts:
        item.reason = "PHRASE_REGULAR"


def _evidence(
    draft: _Draft,
    beats: list[BeatEvent],
    onsets: list[OnsetEvent],
    phrases,
    energy_times: list[float],
) -> SlotEvidence:
    beat_ids = [beat.i for beat in beats if draft.start - 0.02 <= beat.t < draft.end - 0.001]
    if draft.start_beat is not None and draft.start_beat not in beat_ids:
        beat_ids.insert(0, draft.start_beat)
    down_ids = [beat.i for beat in beats if beat.i in set(beat_ids) and beat.is_downbeat]
    onset_ids = [onset.id for onset in onsets if abs(onset.t - draft.start) <= 0.05][:8]
    phrase_id = None
    for phrase in phrases:
        if phrase.start - 0.02 <= draft.start < phrase.end + 0.001:
            phrase_id = phrase.id
            break
    if phrase_id is None and phrases and draft.start >= phrases[-1].start - 0.02:
        phrase_id = phrases[-1].id
    bins = [index for index, moment in enumerate(energy_times) if draft.start - 1e-6 <= moment < draft.end - 1e-9]
    if not bins and energy_times:
        bins = [min(range(len(energy_times)), key=lambda index: abs(energy_times[index] - draft.start))]
    return SlotEvidence(
        beat_ids=beat_ids,
        downbeat_ids=down_ids,
        onset_ids=onset_ids,
        phrase_id=phrase_id,
        energy_bins=bins[:24],
        region_id=draft.region_id,
        rule=draft.reason,
        params={"beats": float(draft.beats), "start": draft.start, "end": draft.end},
    )


def _confidence(draft: _Draft, region: MusicEditRegion, coverage: float, downbeat_confidence: float | None) -> float:
    values = [region.confidence, coverage]
    if draft.reason in _DOWNBEAT_REASONS and downbeat_confidence is not None:
        values.append(downbeat_confidence)
    if draft.reason == "ACCENT_FLURRY":
        values.append(1.0 if draft.accent_at_start or draft.reason == "ACCENT_FLURRY" else 0.0)
    if draft.reason == "HIT_HOLD" and draft.accent_at_start:
        values.append(1.0)
    return float(min(1.0, max(0.0, min(values))))


def _pace(length: float) -> str:
    if length >= 2.5:
        return "hold"
    if length < 0.75:
        return "fast"
    return "medium"


def plan_shot_slots(document: MusicEditRegions) -> MusicEditRegions:
    """Fill shot slots from beats already stored on ``document``.

    No beats, or no tempo: the document is returned unchanged. Region times
    are never edited.
    """

    if not document.beats or not document.bpm:
        return document
    period = document.beat_grid.period_s if document.beat_grid is not None else 60.0 / document.bpm
    coverage = document.beat_grid.coverage if document.beat_grid is not None else 1.0
    beat_times = [beat.t for beat in document.beats]
    down_times = [beat.t for beat in document.beats if beat.is_downbeat]
    duration = _r3(document.duration_seconds)
    snapped = [0.0]
    rules = ["edge"]
    for index, region in enumerate(document.regions[:-1]):
        nxt = document.regions[index + 1]
        prefer = region.edit_role == "hook" or nxt.edit_role in {"settle_outro", "breath"}
        moment, rule = _snap(region.end, duration, down_times, beat_times, period, prefer)
        if moment <= snapped[-1] + 0.05 or moment >= nxt.end - 0.05:
            moment, rule = _r3(region.end), "offbeat_boundary"
        snapped.append(moment)
        rules.append(rule)
    snapped.append(duration)
    rules.append("edge")
    for index in range(1, len(snapped)):
        if snapped[index] <= snapped[index - 1]:
            snapped[index] = _r3(min(duration, snapped[index - 1] + 0.05))
            rules[index] = "offbeat_boundary"
    snapped[-1] = duration

    anchors: list[RegionCutAnchor] = []
    drafts: list[_Draft] = []
    for index, region in enumerate(document.regions):
        anchors.append(
            RegionCutAnchor(
                region_id=region.region_id,
                boundary_s=_r3(region.start),
                snapped_s=snapped[index],
                offset_s=_r3(snapped[index] - region.start),
                rule=rules[index],  # type: ignore[arg-type]
            )
        )
        nxt = document.regions[index + 1] if index + 1 < len(document.regions) else None
        span = _beats_in(document.beats, snapped[index], snapped[index + 1])
        pieces = _pattern(region.edit_role, span, period, region, nxt)
        region_drafts = _materialize(region, snapped[index], snapped[index + 1], document.beats, pieces)
        region_drafts = _absorb_short_tail(region_drafts, region, nxt, period)
        for draft in region_drafts:
            draft.budget_exception = _exception(draft, region, nxt, period)
        _mark_regular(region_drafts, region.edit_role)
        drafts.extend(region_drafts)
    if anchors:
        last = document.regions[-1]
        anchors.append(
            RegionCutAnchor(
                region_id=last.region_id,
                boundary_s=_r3(last.end),
                snapped_s=duration,
                offset_s=_r3(duration - last.end),
                rule="edge",
            )
        )
    if drafts:
        drafts[0].start = 0.0
        drafts[-1].end = duration

    marks: list[float] = []
    for index, region in enumerate(document.regions):
        nxt = document.regions[index + 1] if index + 1 < len(document.regions) else None
        if region.edit_role == "peak_cut" and (nxt is None or nxt.edit_role != "peak_cut"):
            marks.append(snapped[index + 1])
        if region.edit_role == "breath":
            marks.append(snapped[index])
        inside = [beat for beat in document.beats if region.start - 0.02 <= beat.t < region.end]
        quiet = [beat for beat in inside if beat.energy < region.mean_energy * 0.6]
        run: list[BeatEvent] = []
        for beat in inside:
            if beat in quiet:
                run.append(beat)
            else:
                if len(run) >= 2:
                    marks.append(run[0].t)
                run = []
        if len(run) >= 2:
            marks.append(run[0].t)
    deduped: list[float] = []
    for moment in marks:
        if all(abs(moment - kept) > 0.05 for kept in deduped):
            deduped.append(_r3(moment))
    for draft in drafts:
        if any(abs(draft.end - moment) <= 0.05 for moment in deduped):
            draft.breath_after = True

    energy_times = [point.time_seconds for point in document.energy_curve]
    slots: list[ShotSlot] = []
    per_region: dict[str, list[_Draft]] = {region.region_id: [] for region in document.regions}
    for draft in drafts:
        per_region.setdefault(draft.region_id, []).append(draft)
    for region in document.regions:
        for index, draft in enumerate(per_region.get(region.region_id, []), start=1):
            length = draft.end - draft.start
            evidence = _evidence(draft, document.beats, document.onsets, document.phrases, energy_times)
            if draft.reason == "HIT_HOLD" and draft.accent_at_start and draft.start_beat not in evidence.beat_ids:
                evidence.beat_ids.insert(0, draft.start_beat)  # type: ignore[arg-type]
            slots.append(
                ShotSlot(
                    slot_id=f"{region.region_id}-s{index:02d}",
                    region_id=region.region_id,
                    start=draft.start,
                    end=draft.end,
                    beats=draft.beats,
                    pace=_pace(length),  # type: ignore[arg-type]
                    shot_type=draft.shot_type,  # type: ignore[arg-type]
                    reason_code=draft.reason,  # type: ignore[arg-type]
                    reason_zh=_text(draft.reason, draft.beats),
                    accent_at_start=draft.accent_at_start,
                    breath_after=draft.breath_after,
                    budget_exception=draft.budget_exception,  # type: ignore[arg-type]
                    confidence=_confidence(draft, region, coverage, document.downbeat_confidence),
                    evidence=evidence,
                )
            )
    counts = {region.region_id: 0 for region in document.regions}
    codes: dict[str, set[str]] = {region.region_id: set() for region in document.regions}
    for slot in slots:
        counts[slot.region_id] = counts.get(slot.region_id, 0) + 1
        codes.setdefault(slot.region_id, set()).add(slot.reason_code)
    regions = [
        region.model_copy(
            update={
                "cut_summary_zh": _summary(region.edit_role, codes.get(region.region_id, set())),
                "slot_count": counts.get(region.region_id, 0),
            }
        )
        for region in document.regions
    ]
    warnings = [item for item in document.warnings if item not in _MANAGED_WARNINGS]
    warnings.append("meter_assumed_4_4")
    if document.downbeat_detector == "every_fourth_beat":
        warnings.append("downbeat_phase_heuristic")
    if document.beat_grid is not None and document.beat_grid.gaps:
        warnings.append("beat_grid_gaps")
    if any(abs(anchor.offset_s) >= 0.001 and anchor.rule != "edge" for anchor in anchors):
        warnings.append("boundary_snapped")
    if any(slot.budget_exception for slot in slots):
        warnings.append("slot_budget_exception")
    return document.model_copy(
        update={
            "regions": regions,
            "shot_slots": slots,
            "region_cut_anchors": anchors,
            "breath_marks": deduped,
            "warnings": warnings,
            "meter_assumed": 4,
        }
    )
