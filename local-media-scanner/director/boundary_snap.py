"""Choose one cut time for a region boundary.

Nearest kept downbeat wins when it is inside half a bar. Low downbeat
confidence and a downbeat farther than half a bar falls back to the nearest
beat, and only when that beat is inside one bar. Farther than one bar, the
boundary stays put and the desk explains why. Downbeats closer than half a
bar are dropped (the earlier one stays) so a stray extra downbeat is not a
bar line.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


LOW_CONFIDENCE = 0.10
PENDING_OFFSET = 0.02
COLLISION_GAP = 0.05


@dataclass(frozen=True)
class BoundaryChoice:
    time: float
    rule: str
    offset_s: float
    explanation_zh: str
    warning: str | None
    pending: bool


def _r3(value: float) -> float:
    return round(float(value), 3)


def _f2(value: float) -> str:
    rounded = Decimal(str(round(float(value), 6))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:.2f}"


def _signed(value: float) -> str:
    text = _f2(abs(value))
    if value < 0:
        return f"-{text}"
    return f"+{text}"


def filter_downbeat_times(times: list[float], period: float) -> tuple[list[float], list[float]]:
    """Keep the earlier downbeat when the next one is closer than half a bar."""

    half = 2.0 * float(period)
    kept: list[float] = []
    dropped: list[float] = []
    for moment in sorted(float(item) for item in times):
        if kept and moment - kept[-1] < half - 1e-6:
            dropped.append(moment)
            continue
        kept.append(moment)
    return kept, dropped


def _nearest(times: list[float], moment: float) -> float | None:
    if not times:
        return None
    return min(times, key=lambda item: (abs(item - moment), item))


def _cluster_note(moment: float, chosen: float | None, ignored: list[float]) -> str:
    if chosen is None or not ignored:
        return ""
    chosen_distance = abs(chosen - moment)
    nearer = [item for item in ignored if abs(item - moment) + 1e-9 < chosen_distance]
    if not nearer:
        return ""
    picked = min(nearer, key=lambda item: (abs(item - moment), item))
    return f"相距不足半小节的强拍 {_f2(picked)} 已忽略。"


def choose_boundary(
    moment: float,
    duration: float,
    downbeats: list[float],
    beats: list[float],
    period: float,
    confidence: float | None,
    ignored: list[float] | None = None,
) -> BoundaryChoice:
    """Recommend a cut for ``moment``. ``offset`` is recommended minus current."""

    moment = float(moment)
    duration = float(duration)
    period = float(period) if period and period > 0 else 0.5
    half = 2.0 * period
    bar = 4.0 * period
    if moment <= 0.0005 or abs(moment - duration) <= 0.0005:
        edge = 0.0 if moment <= 0.0005 else duration
        return BoundaryChoice(_r3(edge), "edge", _r3(edge - moment), "", None, False)

    kept, dropped = filter_downbeat_times(list(downbeats), period)
    ignored_times = list(dropped)
    for item in ignored or []:
        if all(abs(float(item) - kept_item) > 1e-3 for kept_item in ignored_times):
            ignored_times.append(float(item))
    low = confidence is None or float(confidence) < LOW_CONFIDENCE
    down = _nearest(kept, moment)
    beat = _nearest([float(item) for item in beats], moment)
    down_dist = abs(down - moment) if down is not None else None
    beat_dist = abs(beat - moment) if beat is not None else None
    shown = "未知" if confidence is None else f"{float(confidence):.3f}"

    def finish(
        target: float,
        rule: str,
        text: str,
        warning: str | None,
        *,
        force_pending: bool = False,
    ) -> BoundaryChoice:
        offset = target - moment
        pending = force_pending or abs(offset) >= PENDING_OFFSET
        return BoundaryChoice(_r3(target), rule, _r3(offset), text, warning, pending)

    if down is not None and down_dist is not None and down_dist <= half + 1e-6:
        text = (
            f"建议吸到 {_f2(down)}s（强拍），偏移 {_signed(down - moment)}s。"
            f"距离 {_f2(down_dist)}s，在半小节（{_f2(half)}s）以内。"
        )
        if low:
            text += f"强拍置信度 {shown} 偏低，但这条距离没有超过半小节，所以仍吸强拍。"
        text += _cluster_note(moment, down, ignored_times)
        return finish(down, "downbeat", text, None)

    beat_in_bar = beat is not None and beat_dist is not None and beat_dist <= bar + 1e-6
    down_far = down is None or (down_dist is not None and down_dist > half + 1e-6)
    if low and down_far and beat_in_bar and beat is not None and beat_dist is not None:
        far = "没有强拍" if down is None or down_dist is None else f"最近强拍 {_f2(down)}s 离边界 {_f2(down_dist)}s"
        text = (
            f"强拍置信度 {shown}，{far}，超过半小节（{_f2(half)}s）。"
            f"建议改吸最近拍点 {_f2(beat)}s，偏移 {_signed(beat - moment)}s。"
        )
        text += _cluster_note(moment, down, ignored_times)
        return finish(beat, "beat", text, "boundary_snap_beat_low_confidence")

    if down is not None and down_dist is not None and down_dist <= bar + 1e-6:
        text = (
            f"建议吸到 {_f2(down)}s（强拍），偏移 {_signed(down - moment)}s。"
            f"距离 {_f2(down_dist)}s，超过半小节（{_f2(half)}s），但没有超过 1 小节（{_f2(bar)}s），所以仍吸强拍。"
        )
        if low:
            text += f"强拍置信度 {shown} 偏低，最近拍点也不在 1 小节以内，所以不改吸拍点。"
        text += _cluster_note(moment, down, ignored_times)
        return finish(down, "downbeat", text, None)

    candidates: list[tuple[str, float, float]] = []
    if down is not None and down_dist is not None:
        candidates.append(("强拍", down, down_dist))
    if beat is not None and beat_dist is not None:
        candidates.append(("拍点", beat, beat_dist))
    if candidates:
        kind, target, dist = min(candidates, key=lambda item: (item[2], item[1]))
        text = (
            f"最近的格点离边界 {_f2(dist)}s，超过 1 小节（{_f2(bar)}s），这条边界不移动。"
            f"最近的{kind}在 {_f2(target)}s。"
        )
    else:
        text = f"没有可吸的格点。超过 1 小节（{_f2(bar)}s）的范围就不移动。"
    text += _cluster_note(moment, down, ignored_times)
    return finish(moment, "beyond_bar", text, "boundary_snap_beyond_bar", force_pending=True)


def snap_bound_list(
    bounds: list[float],
    duration: float,
    downbeats: list[float],
    beats: list[float],
    period: float,
    confidence: float | None,
) -> list[float]:
    """Snap interior bounds. Endpoints stay. A snap that would collapse a region is refused."""

    if len(bounds) < 2:
        return list(bounds)
    result = [_r3(bounds[0])]
    for index in range(1, len(bounds) - 1):
        choice = choose_boundary(
            bounds[index], duration, downbeats, beats, period, confidence
        )
        target = bounds[index] if choice.rule == "beyond_bar" else choice.time
        nxt = bounds[index + 1]
        if target <= result[-1] + COLLISION_GAP or target >= nxt - COLLISION_GAP:
            target = bounds[index]
        result.append(_r3(target))
    result.append(_r3(bounds[-1]))
    for index in range(1, len(result) - 1):
        if result[index] <= result[index - 1] + COLLISION_GAP or result[index] >= result[index + 1] - COLLISION_GAP:
            result[index] = _r3(bounds[index])
    result[0] = _r3(bounds[0])
    result[-1] = _r3(duration if duration else bounds[-1])
    return result
