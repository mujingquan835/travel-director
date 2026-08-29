"""Reference-safe conversion from a selected direction to original-music intent."""

from __future__ import annotations

from director.schema import (
    MusicBlueprint,
    MusicBlueprintSection,
    MusicDirection,
    UserCreativeBrief,
)


SECTION_LAYOUT = [
    ("intro", 0.0, 0.12, 0.25),
    ("rise", 0.12, 0.40, 0.55),
    ("breath", 0.40, 0.52, 0.20),
    ("climax", 0.52, 0.90, 0.90),
    ("outro", 0.90, 1.00, 0.35),
]


def build_blueprint(
    direction: MusicDirection,
    brief: UserCreativeBrief,
) -> MusicBlueprint:
    duration = brief.target_duration_seconds
    boundaries = [
        0.0,
        round(duration * 0.12, 3),
        round(duration * 0.40, 3),
        round(duration * 0.52, 3),
        round(duration * 0.90, 3),
        float(duration),
    ]
    sections = [
        MusicBlueprintSection(
            start=boundaries[index],
            end=boundaries[index + 1],
            role=role,
            energy=energy,
        )
        for index, (role, _start_ratio, _end_ratio, energy) in enumerate(
            SECTION_LAYOUT
        )
    ]
    bpm = direction.bpm or {"low": 92, "medium": 116, "high": 138}[brief.rhythm]
    genre = direction.genres[0] if direction.genres else f"{brief.style}旅行器乐"
    instruments = (
        direction.instruments
        or brief.instrument_preferences
        or ["轻合成器", "电子鼓"]
    )
    return MusicBlueprint(
        duration_seconds=duration,
        bpm=bpm,
        meter="4/4",
        genre=genre,
        instrumentation=list(instruments),
        vocals="allowed" if brief.vocals == "allowed" else "none",
        sections=sections,
        ending="明确落点，不淡出",
    )


def build_generation_prompt(blueprint: MusicBlueprint) -> str:
    section_text = "；".join(
        f"{section.start:g}-{section.end:g}秒 {section.role} 能量{section.energy:.2f}"
        for section in blueprint.sections
    )
    vocals = "无人声" if blueprint.vocals == "none" else "可使用非辨识性人声质感"
    return (
        f"创作一首{blueprint.duration_seconds}秒原创配乐，"
        f"{blueprint.bpm} BPM，{blueprint.meter}拍，风格为{blueprint.genre}；"
        f"乐器：{'、'.join(blueprint.instrumentation)}；{vocals}。"
        f"结构：{section_text}。结尾：{blueprint.ending}。"
        "原创配乐；明确落点；不得复刻任何现有旋律、歌词或具体编曲。"
    )
