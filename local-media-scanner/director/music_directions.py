"""Explainable ranking from normalized catalog candidates to three directions."""

from __future__ import annotations

from director.schema import (
    CatalogSearchResult,
    MusicCandidate,
    MusicDirection,
    MusicSearchBrief,
)


def _bpm_fit(candidate: MusicCandidate, brief: MusicSearchBrief) -> float:
    if candidate.bpm is None:
        return 0.0
    if brief.bpm_min <= candidate.bpm <= brief.bpm_max:
        return 1.0
    distance = min(
        abs(candidate.bpm - brief.bpm_min), abs(candidate.bpm - brief.bpm_max)
    )
    return max(0.0, 1.0 - distance / 40.0)


def _duration_fit(candidate: MusicCandidate, brief: MusicSearchBrief) -> float:
    if candidate.duration_seconds is None:
        return 0.0
    difference = abs(candidate.duration_seconds - brief.target_duration_seconds)
    return max(0.0, 1.0 - difference / brief.target_duration_seconds)


def _overlap(values: list[str], expected: set[str]) -> float:
    if not expected:
        return 0.0
    return len(set(values) & expected) / len(expected)


def _direction(candidate: MusicCandidate, brief: MusicSearchBrief) -> MusicDirection:
    tags = set(brief.keywords + brief.genres + brief.moods)
    instruments = set(brief.instrument_preferences)
    reasons = {
        "bpm_fit": _bpm_fit(candidate, brief),
        "duration_fit": _duration_fit(candidate, brief),
        "tag_overlap": _overlap(candidate.visible_tags, tags),
        "instrument_overlap": _overlap(candidate.visible_tags, instruments),
    }
    score = (
        reasons["bpm_fit"] * 0.35
        + reasons["duration_fit"] * 0.25
        + reasons["tag_overlap"] * 0.25
        + reasons["instrument_overlap"] * 0.15
    )
    bpm_text = f"{candidate.bpm} BPM" if candidate.bpm is not None else "BPM 未显示"
    description = f"{bpm_text}，{ '、'.join(candidate.visible_tags[:3]) or '页面未显示标签' }。"
    return MusicDirection(
        candidate_id=candidate.candidate_id,
        title=candidate.title,
        author=candidate.author,
        plain_description=description,
        fit_reason=(
            f"节奏匹配 {reasons['bpm_fit']:.2f}，时长匹配 {reasons['duration_fit']:.2f}，"
            f"标签匹配 {reasons['tag_overlap']:.2f}。"
        ),
        preview_url=candidate.preview_url,
        bpm=candidate.bpm,
        moods=[tag for tag in candidate.visible_tags if tag in brief.moods],
        instruments=[
            tag for tag in candidate.visible_tags if tag in brief.instrument_preferences
        ],
        score=round(score, 6),
        reasons={key: round(value, 6) for key, value in reasons.items()},
    )


def rank_directions(
    result: CatalogSearchResult,
    brief: MusicSearchBrief,
    limit: int = 3,
) -> list[MusicDirection]:
    directions = [_direction(candidate, brief) for candidate in result.candidates]
    directions.sort(key=lambda item: (-item.score, item.candidate_id))
    return directions[: min(limit, 3)]
