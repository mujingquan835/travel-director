"""Transparent local baseline for music catalog search briefs."""

from __future__ import annotations

from director.schema import (
    MaterialLibraryProfile,
    MusicSearchBrief,
    MusicSearchEvidence,
    UserCreativeBrief,
)


BPM_BY_RHYTHM = {
    "low": (80, 105),
    "medium": (105, 125),
    "high": (125, 150),
}
GENRES_BY_RHYTHM = {
    "low": ["氛围器乐", "轻音乐"],
    "medium": ["轻电子", "流行器乐"],
    "high": ["电子", "流行器乐"],
}
SCENE_KEYWORDS = {
    "nature": "自然",
    "city": "城市",
    "building": "建筑",
    "indoor": "室内",
    "theme_park": "游乐",
    "food_dining": "美食",
    "transportation": "交通",
    "night_scene": "夜景",
}


def _unique(values: list[str], limit: int) -> list[str]:
    output: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in output:
            output.append(cleaned)
        if len(output) == limit:
            break
    return output


def build_music_search_brief(
    profile: MaterialLibraryProfile,
    brief: UserCreativeBrief,
) -> MusicSearchBrief:
    bpm_min, bpm_max = BPM_BY_RHYTHM[brief.rhythm]
    ranked_scenes = sorted(
        profile.scene_distribution.items(), key=lambda item: (-item[1], item[0])
    )
    scene_keywords = [
        SCENE_KEYWORDS[scene]
        for scene, _count in ranked_scenes
        if scene in SCENE_KEYWORDS
    ][:2]
    keywords = _unique(
        [brief.location, brief.travel_type, brief.mood, brief.style, *scene_keywords],
        limit=8,
    )
    rules = [
        f"rhythm:{brief.rhythm}->bpm:{bpm_min}-{bpm_max}",
        f"rhythm:{brief.rhythm}->genres:{','.join(GENRES_BY_RHYTHM[brief.rhythm])}",
        "user location, travel type, mood, and style copied as search keywords",
    ]
    if scene_keywords:
        rules.append(
            "top scanner scene candidates mapped to keywords: "
            + ",".join(scene_keywords)
        )
    return MusicSearchBrief(
        keywords=keywords,
        genres=GENRES_BY_RHYTHM[brief.rhythm],
        moods=_unique([brief.mood, brief.style], limit=2),
        bpm_min=bpm_min,
        bpm_max=bpm_max,
        instrument_preferences=list(brief.instrument_preferences),
        vocals=brief.vocals,
        target_duration_seconds=brief.target_duration_seconds,
        evidence=MusicSearchEvidence(
            source_scanner_run_id=profile.source_scanner_run_id,
            rules=rules,
        ),
    )
