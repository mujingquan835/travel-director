"""Offline, evidence-bound music generation prompt recommendations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from director.search_planner import prompt_bpm_anchors
from director.visual_schema import (
    BriefConfirmation,
    DirectorTreatment,
    EvidenceRef,
    MusicGenerationPromptRecommendation,
    MusicGenerationPromptRecommendationBatch,
    MusicPromptParameters,
    ProjectCoverage,
)


GENRES_BY_TRAVEL_TYPE = {
    "城市漫游": ("轻电子旅行器乐", "原声城市民谣器乐", "电影感氛围电子"),
    "自然旅行": ("自然氛围器乐", "原声旅行器乐", "电影感环境电子"),
    "美食旅行": ("轻快原声器乐", "温暖爵士旅行器乐", "律动轻电子"),
    "人文旅行": ("人文原声器乐", "克制室内乐", "电影感氛围器乐"),
}

ALL_DIFFERENCE_AXES = [
    "genre",
    "mood",
    "rhythm",
    "instrumentation",
    "drum_density",
    "energy_structure",
]


def _unique(values: Iterable[str], limit: int = 4) -> list[str]:
    output: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in output:
            output.append(cleaned)
        if len(output) == limit:
            break
    return output


def _compact_phrase(value: str, limit: int = 16) -> str:
    cleaned = " ".join(value.split())
    return cleaned if len(cleaned) <= limit else cleaned[:limit]


def _labels(*values: str) -> str:
    return "、".join(_unique(values, limit=len(values)))


def _evidence_key(ref: EvidenceRef) -> tuple[Any, ...]:
    return (
        ref.material_id,
        ref.artifact_path,
        ref.field_path,
        ref.source_kind,
        ref.status,
        ref.sha256,
    )


def _compact_evidence(
    treatment: DirectorTreatment, coverage: ProjectCoverage
) -> list[EvidenceRef]:
    candidates = [
        *treatment.pacing_evidence_refs,
        *(ref for row in treatment.emotional_arc for ref in row.evidence_refs),
        *treatment.evidence_refs,
        *coverage.evidence_refs,
    ]
    output: list[EvidenceRef] = []
    seen: set[tuple[Any, ...]] = set()
    for ref in candidates:
        if _evidence_key(ref) not in seen:
            output.append(ref)
            seen.add(_evidence_key(ref))
        if len(output) == 6:
            break
    return output


def _vocal_instruction(vocals: str) -> str:
    return {
        "instrumental_only": "纯器乐，无人声",
        "instrumental_preferred": "器乐为主，无清晰歌词",
        "allowed": "可用轻量无语义哼唱",
    }[vocals]


def _prompt(parameters: MusicPromptParameters) -> str:
    density = {"low": "低密度鼓点", "medium": "中密度鼓点", "high": "高密度鼓点"}[
        parameters.drum_density
    ]
    instruments = "、".join(parameters.instruments)
    return (
        f"生成{parameters.duration_seconds}秒{parameters.genre}，情绪{parameters.mood}，"
        f"{parameters.bpm} BPM；使用{instruments}，{density}；"
        f"结构：{parameters.energy_structure}；{_vocal_instruction(parameters.vocals)}。"
        "原创，不模仿具体歌曲或艺人。"
    )


def _genres(travel_type: str) -> tuple[str, str, str]:
    if travel_type in GENRES_BY_TRAVEL_TYPE:
        return GENRES_BY_TRAVEL_TYPE[travel_type]
    return "轻电子旅行器乐", "原声旅行器乐", "电影感氛围器乐"


def recommend_music_prompts(
    treatment: DirectorTreatment,
    brief: BriefConfirmation,
    coverage: ProjectCoverage,
) -> MusicGenerationPromptRecommendationBatch:
    """Return exactly three ready-to-use prompts without network or model calls."""

    if any(
        artifact.status != "completed" for artifact in (treatment, brief, coverage)
    ):
        raise ValueError("completed treatment, brief, and coverage are required")
    if treatment.unsupported_inferences:
        raise ValueError("treatment contains unsupported inferences")
    fields = brief.normalized_fields
    assert fields.travel_type and fields.style and fields.mood and fields.rhythm
    assert fields.target_duration_seconds
    vocals = fields.vocals or "instrumental_preferred"
    low_bpm, middle_bpm, high_bpm = prompt_bpm_anchors(fields.rhythm)
    genres = _genres(fields.travel_type)
    preferred = [
        instrument
        for instrument in fields.instrument_preferences
        if len(instrument.strip()) <= 12
    ]
    compact_style = _compact_phrase(fields.style, limit=12)
    compact_mood = _compact_phrase(fields.mood)
    instruments = (
        _unique([*preferred[:2], "合成器", "木吉他"]),
        _unique([*preferred[:1], "木吉他", "钢琴", "轻弦乐"]),
        _unique(["合成器", "弦乐", "低频打击"]),
    )
    ending_gap = "ending" in coverage.missing_director_functions or any(
        "ending" in gap for gap in treatment.coverage_gaps
    )
    energy_structures = (
        "低能开场—中段推进—尾段留白" if ending_gap else "低能开场—中段推进—尾段收束",
        "留白开场—平稳展开—柔和停驻" if ending_gap else "留白开场—平稳展开—柔和收束",
        "克制开场—层层抬升—高潮后短收",
    )
    specs = (
        ("balanced-pulse", "平衡推进", genres[0], _labels("清晰", compact_style, compact_mood), middle_bpm, instruments[0], "medium", energy_structures[0]),
        ("organic-breath", "原声呼吸", genres[1], _labels("温暖", "克制", compact_style, compact_mood), low_bpm, instruments[1], "low", energy_structures[1]),
        ("cinematic-rise", "电影渐进", genres[2], _labels("开阔", "渐进", compact_style, compact_mood), high_bpm, instruments[2], "high", energy_structures[2]),
    )
    evidence = _compact_evidence(treatment, coverage)
    recommendations: list[MusicGenerationPromptRecommendation] = []
    for direction_id, title, genre, mood, bpm, selected_instruments, drums, energy in specs:
        parameters = MusicPromptParameters(
            duration_seconds=fields.target_duration_seconds,
            genre=genre,
            mood=mood,
            bpm=bpm,
            instruments=selected_instruments,
            drum_density=drums,
            vocals=vocals,
            energy_structure=energy,
        )
        recommendations.append(
            MusicGenerationPromptRecommendation(
                direction_id=direction_id,
                title=title,
                generation_prompt=_prompt(parameters),
                parameters=parameters,
                difference_axes=ALL_DIFFERENCE_AXES,
                fit_reason=(
                    f"依据导演节奏“{treatment.pacing_strategy}”和"
                    f"{len(coverage.available_director_functions)}项已覆盖职责生成。"
                    + (
                        "Brief未指定人声，采用器乐优先默认。"
                        if fields.vocals is None
                        else ""
                    )
                ),
                director_evidence_refs=evidence,
            )
        )
    return MusicGenerationPromptRecommendationBatch(
        status="completed",
        items=recommendations,
        external_call_count=0,
    )
