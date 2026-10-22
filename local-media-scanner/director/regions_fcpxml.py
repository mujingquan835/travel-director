"""Minimal FCPXML plus a readable edit sheet for one confirmed regions snapshot.

The frame rate is 30 fps. ``MusicEditRegions`` does not store a frame rate,
and the shot planner's frame constant is also 30. Times are rounded to the
nearest frame. This writer does not call ``plan_shot_slots``.

Jianying's importer was checked on macOS Jianying 11.4.0 on 2026-09-09 for
video and audio clips only. Markers, gap names, and gap placeholders in this
file are not part of that check.
"""

from __future__ import annotations

import os
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from director.music_edit_regions_schema import MusicEditRegions, ShotSlot


EXPORT_FPS = 30
JIANYING_FCPXML_NOTICE = (
    "剪映能否导入 marker、占位名和 gap 还没在这台机器上验证。"
    "已知 macOS 剪映 11.4.0（2026-09-09）能导入 FCPXML 的视频和音频片段。"
    "不要把这份导出当成已经兼容剪映。"
)
EXPORT_PAGE_NOTE = (
    "镜头轨只是建议，不能拖动。导出读取已确认快照里的镜头槽和分区边界，"
    "写成 30fps 的 FCPXML 占位和一份剪辑单。"
    + JIANYING_FCPXML_NOTICE
    + "分析或采纳之后，分区和刀口是同一条时间。"
)
_FRAME_RATE_NOTE = (
    "这份导出按 30fps 对齐。分区文档里没有单独的帧率，镜头规划用的也是 30fps。"
)
_TRANSITION_ZH = {
    "whip": "甩",
    "match": "匹配",
    "zoom": "推拉",
    "mask": "遮罩",
    "mask_optional": "遮罩可选",
    "fade": "叠化",
    "cut": "硬切",
    "end": "收",
}


@dataclass(frozen=True)
class FrozenAudio:
    path: Path
    duration_seconds: float
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class RegionsFcpxmlExport:
    fcpxml_path: Path
    sheet_path: Path
    frame_rate: int
    version_id: str
    notice: str


def align_seconds(seconds: float, fps: int = EXPORT_FPS) -> float:
    """Nearest frame. The error is at most half a frame."""

    return frame_index(seconds, fps) / fps


def frame_index(seconds: float, fps: int = EXPORT_FPS) -> int:
    frames = int(round(float(seconds) * fps))
    return frames if frames > 0 else 0


def _fcpx_time(frames: int, fps: int) -> str:
    if frames <= 0:
        return "0s"
    return f"{frames}/{fps}s"


def _timecode(frames: int, fps: int) -> str:
    seconds, frame = divmod(max(0, frames), fps)
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:02d}:{minute:02d}:{second:02d}:{frame:02d}"


def _gap_name(slot: ShotSlot) -> str:
    hint = (slot.content_hint or "画面待定").replace("\n", " ").strip()
    return f"{slot.slot_id} · {hint}"[:180]


def _transition_zh(slot: ShotSlot) -> str:
    parts: list[str] = []
    if slot.transition_in:
        parts.append("入" + _TRANSITION_ZH.get(slot.transition_in, slot.transition_in))
    if slot.transition_out:
        parts.append("出" + _TRANSITION_ZH.get(slot.transition_out, slot.transition_out))
    if not parts and slot.transition:
        parts.append(_TRANSITION_ZH.get(slot.transition, slot.transition))
    return " · ".join(parts) if parts else "硬切"


def _sound_zh(slot: ShotSlot) -> str:
    cues = list(slot.sound_cues)
    if slot.sound_cue and slot.sound_cue not in cues:
        cues.insert(0, slot.sound_cue)
    return "、".join(cues) if cues else "—"


def _slot_spans(regions: MusicEditRegions, fps: int) -> list[tuple[int, int, ShotSlot | None]]:
    slots = list(regions.shot_slots)
    if not slots:
        end = frame_index(regions.duration_seconds, fps)
        return [(0, max(1, end), None)]
    spans: list[tuple[int, int, ShotSlot | None]] = []
    for slot in slots:
        start = frame_index(slot.start, fps)
        end = frame_index(slot.end, fps)
        if end <= start:
            end = start + 1
        if spans and start < spans[-1][1]:
            start = spans[-1][1]
            if end <= start:
                end = start + 1
        if spans and start > spans[-1][1]:
            spans.append((spans[-1][1], start, None))
        spans.append((start, end, slot))
    if spans and spans[0][0] > 0:
        spans.insert(0, (0, spans[0][0], None))
    return spans


def _markers(regions: MusicEditRegions, fps: int) -> list[tuple[int, str]]:
    marks: list[tuple[int, str]] = []
    for region in regions.regions:
        marks.append((frame_index(region.start, fps), f"分区 {region.region_id} {region.edit_role}"))
    for region in regions.regions:
        if region.edit_role == "peak_cut":
            marks.append((frame_index(region.start, fps), f"落点 {region.region_id}"))
            break
    return marks


def _sheet(version_id: str, regions: MusicEditRegions, spans, fps: int) -> str:
    lines = [
        f"# 剪辑单 {version_id}",
        "",
        _FRAME_RATE_NOTE,
        "",
        JIANYING_FCPXML_NOTICE,
        "",
        "| 序号 | 起点 | 终点 | 景别 | 转场 | 声音 | 画面建议 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    index = 0
    for start, end, slot in spans:
        if slot is None:
            continue
        index += 1
        size = slot.shot_size or slot.shot_type
        hint = (slot.content_hint or "画面待定").replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {index} | {_timecode(start, fps)} | {_timecode(end, fps)} | {size} | "
            f"{_transition_zh(slot)} | {_sound_zh(slot)} | {hint} |"
        )
    if index == 0:
        lines.append("|  |  |  |  |  |  | 没有镜头槽 |")
    lines.append("")
    return "\n".join(lines)


def _link_audio(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def write_regions_fcpxml(document, audio: FrozenAudio, output_dir: Path) -> RegionsFcpxmlExport:
    """Write ``project.fcpxml``, the edit sheet, and a linked music file.

    ``document`` is a confirmed regions version. ``output_dir`` must not exist.
    """

    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise ValueError("导出目录已经存在，没有覆盖。")
    if not audio.path.is_file():
        raise ValueError("冻结的配乐文件不在了，不能导出。")
    regions: MusicEditRegions = document.regions
    fps = EXPORT_FPS
    spans = _slot_spans(regions, fps)
    sequence_frames = spans[-1][1]
    audio_frames = max(1, frame_index(audio.duration_seconds, fps))
    music_frames = min(sequence_frames, audio_frames)
    safe_name = audio.path.name.replace("/", "_")
    asset_path = output_dir / "asset" / safe_name

    fcpxml = ET.Element("fcpxml", version="1.9")
    fcpxml.append(ET.Comment(" " + JIANYING_FCPXML_NOTICE + " " + _FRAME_RATE_NOTE + " "))
    resources = ET.SubElement(fcpxml, "resources")
    ET.SubElement(
        resources,
        "format",
        id="project-format",
        name=f"FFVideoFormat1080p{fps}",
        frameDuration=f"1/{fps}s",
        width="1920",
        height="1080",
        colorSpace="1-1-1 (Rec. 709)",
    )
    ET.SubElement(
        resources,
        "asset",
        id="music-asset",
        name=safe_name,
        src=asset_path.as_uri(),
        start="0s",
        duration=_fcpx_time(audio_frames, fps),
        hasAudio="1",
        audioSources="1",
        audioChannels=str(audio.channels),
        audioRate=str(audio.sample_rate),
    )
    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name="Travel Director")
    project = ET.SubElement(event, "project", name=f"regions-{document.version_id}")
    sequence = ET.SubElement(
        project,
        "sequence",
        format="project-format",
        duration=_fcpx_time(sequence_frames, fps),
        tcStart="0s",
        tcFormat="NDF",
        audioLayout="stereo",
        audioRate="48k",
    )
    spine = ET.SubElement(sequence, "spine")
    marks = _markers(regions, fps)
    first_gap = None
    for start, end, slot in spans:
        name = _gap_name(slot) if slot is not None else "空隙"
        gap = ET.SubElement(
            spine,
            "gap",
            name=name,
            offset=_fcpx_time(start, fps),
            start="0s",
            duration=_fcpx_time(end - start, fps),
        )
        if first_gap is None:
            first_gap = gap
        for mark_at, label in marks:
            if start <= mark_at < end:
                ET.SubElement(
                    gap,
                    "marker",
                    start=_fcpx_time(mark_at - start, fps),
                    duration=f"1/{fps}s",
                    value=label,
                )
    if first_gap is None:
        raise ValueError("没有可导出的时间线。")
    ET.SubElement(
        first_gap,
        "asset-clip",
        ref="music-asset",
        name=safe_name,
        lane="-1",
        offset="0s",
        start="0s",
        duration=_fcpx_time(music_frames, fps),
        audioRole="music",
    )
    ET.indent(fcpxml, space="  ")
    payload = ET.tostring(fcpxml, encoding="utf-8", xml_declaration=True)
    output_dir.mkdir(parents=True)
    _link_audio(audio.path, asset_path)
    fcpxml_path = output_dir / "project.fcpxml"
    sheet_path = output_dir / "edit-sheet.md"
    fcpxml_path.write_bytes(payload)
    sheet_path.write_text(_sheet(document.version_id, regions, spans, fps), encoding="utf-8")
    return RegionsFcpxmlExport(
        fcpxml_path=fcpxml_path,
        sheet_path=sheet_path,
        frame_rate=fps,
        version_id=document.version_id,
        notice=JIANYING_FCPXML_NOTICE,
    )
