"""FCPXML plus an edit sheet for one confirmed regions snapshot.

Each shot becomes a real 1080×1920 H.264 placeholder under
``asset/placeholders/``. The spine is those clips, abutted and frame-aligned.
Music is one connected clip (``lane="-1"``) on the first of them, for the
whole song. That is the shape macOS Jianying 11.4.0 imported on 2026-09-09
(spine video ``asset-clip``s, audio connected to the first). This writer does
not open Jianying.

Region name and role are burned into a top corner of each placeholder. A
second video lane is not used: the file that imported had no overlay lane, a
full-frame label would cover the card, and a small lane clip has not been
checked. Markers stay on the clips.

The frame rate is 30 fps. ``MusicEditRegions`` does not store a frame rate,
and the shot planner's frame constant is also 30. Times are rounded to the
nearest frame. This writer does not call ``plan_shot_slots``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from director.music_edit_regions_schema import MusicEditRegions, ShotSlot
from director.role_labels import ROLE_LABELS_ZH


EXPORT_FPS = 30
WIDTH = 1080
HEIGHT = 1920
_OVERLAY_REASON = (
    "分区名和角色烧在每个占位顶部角标，没有另开视频覆盖轨。"
    "2026-09-09 能导入的 FCPXML 只有主轨视频和挂在第一段上的音频；"
    "整幅标签会挡住画面，小尺寸覆盖也没在剪映里试过。"
)
JIANYING_FCPXML_NOTICE = (
    "主轨是真实占位视频，音乐挂在第一段下面，和 2026-09-09 "
    "macOS 剪映 11.4.0 能导入的视频加音频结构相同。"
    "竖屏占位、烧录的字和这一份文件还没在这台机器上验证。"
    "不要把这份导出当成已经兼容剪映。"
)
EXPORT_PAGE_NOTE = (
    "镜头轨只是建议，不能拖动。导出读取已确认快照，按 30fps 生成 1080×1920 占位视频，"
    "首尾相接写成 FCPXML，并写一份剪辑单。分区名烧在每个占位的顶部角标，不另开一条覆盖轨。"
    + JIANYING_FCPXML_NOTICE
    + "分析或采纳之后，分区和刀口是同一条时间。"
)
_FRAME_RATE_NOTE = (
    "这份导出按 30fps 对齐。分区文档里没有单独的帧率，镜头规划用的也是 30fps。"
    "占位是 1080×1920 竖屏。"
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
_TYPE_ZH = {
    "远": "远景",
    "细": "细节",
    "动": "运动",
    "脸": "人脸",
    "空": "空镜",
    "转": "转场",
    "?": "待定",
}
_ROLE_RGB = {
    "hook": (0xC2, 0x7A, 0x62),
    "establish": (0x7F, 0x9E, 0x9C),
    "narrative_hold": (0x5F, 0x8F, 0x86),
    "build": (0xC4, 0xA4, 0x5F),
    "peak_cut": (0xA6, 0x5B, 0x6B),
    "breath": (0x8D, 0x7E, 0xA3),
    "settle_outro": (0x6F, 0x7F, 0x9C),
    "unknown": (0xC9, 0xB4, 0x8A),
}
_HOMEBREW_FFMPEG = Path("/opt/homebrew/bin/ffmpeg")
_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/Supplemental/PingFang.ttc"),
    Path("/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
)
_FFMPEG_MISSING = "找不到 ffmpeg，不能生成占位视频。"
_FONT_MISSING = "找不到中文字体（优先 PingFang），不能烧录镜头占位。"


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


@dataclass(frozen=True)
class _Card:
    slot: ShotSlot
    role: str
    start: int
    end: int
    is_drop: bool
    filename: str


def align_seconds(seconds: float, fps: int = EXPORT_FPS) -> float:
    """Nearest frame. The error is at most half a frame."""

    return frame_index(seconds, fps) / fps


def frame_index(seconds: float, fps: int = EXPORT_FPS) -> int:
    frames = int(round(float(seconds) * fps))
    return frames if frames > 0 else 0


def ffmpeg_executable() -> str:
    """Same lookup as the waveform decoder, plus the Mac Homebrew path."""

    found = shutil.which("ffmpeg")
    if found:
        return found
    if _HOMEBREW_FFMPEG.is_file() and os.access(_HOMEBREW_FFMPEG, os.X_OK):
        return str(_HOMEBREW_FFMPEG)
    raise ValueError(_FFMPEG_MISSING)


def cjk_font_path() -> Path:
    for path in _FONT_CANDIDATES:
        if path.is_file():
            return path
    raise ValueError(_FONT_MISSING)


def placeholder_spans(regions: MusicEditRegions, fps: int = EXPORT_FPS) -> list[tuple[int, int, ShotSlot]]:
    """Frame-aligned shot spans that abut.

    Rounding overlaps are pushed forward so each clip keeps at least one
    frame. A hole left by rounding is closed by extending the previous clip,
    so the spine has no gap element and the file length matches the clip.
    When the planner already abuts, each span is the slot's own frame count.
    """

    slots = list(regions.shot_slots)
    if not slots:
        raise ValueError("没有镜头槽，不能导出。")
    spans: list[tuple[int, int, ShotSlot]] = []
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
            prev_start, _prev_end, prev = spans[-1]
            spans[-1] = (prev_start, start, prev)
        spans.append((start, end, slot))
    return spans


def _fcpx_time(frames: int, fps: int) -> str:
    if frames <= 0:
        return "0s"
    return f"{frames}/{fps}s"


def _timecode(frames: int, fps: int) -> str:
    seconds, frame = divmod(max(0, frames), fps)
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:02d}:{minute:02d}:{second:02d}:{frame:02d}"


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


def _size_zh(slot: ShotSlot) -> str:
    if slot.shot_size:
        return slot.shot_size
    return _TYPE_ZH.get(slot.shot_type, slot.shot_type)


def _safe_token(text: str, limit: int) -> str:
    cleaned: list[str] = []
    for char in text.replace("\n", " ").strip():
        if char in '/\\:*?"<>|' or ord(char) < 32:
            continue
        cleaned.append(char)
    token = "".join(cleaned).strip().strip(".")
    return (token[:limit] or "画面待定")


def _placeholder_filename(slot: ShotSlot) -> str:
    hint = _safe_token(slot.content_hint or "画面待定", 18)
    technique = _safe_token(slot.technique_name_zh, 8) + "-" if slot.technique_name_zh else ""
    return f"{technique}{_safe_token(slot.slot_id, 40)}-{hint}.mp4"


def _drop_ids(regions: MusicEditRegions) -> set[str]:
    grouped: dict[str, list[ShotSlot]] = {}
    for slot in regions.shot_slots:
        grouped.setdefault(slot.region_id, []).append(slot)
    chosen: set[str] = set()
    for region in regions.regions:
        if region.edit_role != "peak_cut":
            continue
        group = grouped.get(region.region_id, [])
        hits = [slot for slot in group if slot.pattern_role == "hit"]
        slot = hits[0] if hits else (group[0] if group else None)
        if slot is not None:
            chosen.add(slot.slot_id)
    return chosen


def _cards(regions: MusicEditRegions, fps: int) -> list[_Card]:
    drops = _drop_ids(regions)
    roles = {region.region_id: region.edit_role for region in regions.regions}
    cards: list[_Card] = []
    for start, end, slot in placeholder_spans(regions, fps):
        cards.append(
            _Card(
                slot=slot,
                role=roles.get(slot.region_id, "unknown"),
                start=start,
                end=end,
                is_drop=slot.slot_id in drops,
                filename=_placeholder_filename(slot),
            )
        )
    return cards


def _markers(regions: MusicEditRegions, fps: int) -> list[tuple[int, str]]:
    marks: list[tuple[int, str]] = []
    for region in regions.regions:
        role = ROLE_LABELS_ZH.get(region.edit_role, region.edit_role)
        marks.append((frame_index(region.start, fps), f"分区 {region.region_id} {role}"))
    for region in regions.regions:
        if region.edit_role == "peak_cut":
            marks.append((frame_index(region.start, fps), f"落点 {region.region_id}"))
            break
    for use in regions.technique_uses:
        marks.append((frame_index(use.anchor_s, fps), f"手法 {use.name_zh} {use.region_id}"))
    return marks


def _sheet(version_id: str, regions: MusicEditRegions, cards: list[_Card], fps: int) -> str:
    lines = [
        f"# 剪辑单 {version_id}",
        "",
        _FRAME_RATE_NOTE,
        "",
        _OVERLAY_REASON,
        "",
        JIANYING_FCPXML_NOTICE,
        "",
        "占位视频在 asset/placeholders/。重复导出会覆盖这些文件。",
        "",
        "| 序号 | 起点 | 终点 | 景别 | 转场 | 声音 | 画面建议 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, card in enumerate(cards, start=1):
        hint = (card.slot.content_hint or "画面待定").replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {index} | {_timecode(card.start, fps)} | {_timecode(card.end, fps)} | {_size_zh(card.slot)} | "
            f"{_transition_zh(card.slot)} | {_sound_zh(card.slot)} | {hint} |"
        )
    if not cards:
        lines.append("|  |  |  |  |  |  | 没有镜头槽 |")
    lines.append("")
    if regions.technique_summary_zh:
        seed = (regions.technique_seed or "")[:4]
        lines.extend(["", f"本版主题：{regions.technique_summary_zh}（种子 {seed}）", ""])
    for use in regions.technique_uses:
        lines.append(f"## {use.name_zh} · {use.region_id}")
        lines.append("")
        lines.append(f"为什么：{use.why_zh}")
        lines.append("")
        lines.append("剪映里怎么做（菜单名待核）：")
        for index, step in enumerate(use.steps_zh, start=1):
            lines.append(f"{index}. {step}")
        lines.append("")
        if use.footage_zh:
            lines.append(f"素材：{use.footage_zh}")
        if use.fallback_zh:
            lines.append(f"没有素材时：{use.fallback_zh}")
        if use.fcpxml_zh:
            lines.append(use.fcpxml_zh)
        lines.append("")
    return "\n".join(lines)


def _link_audio(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _font(path: Path, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(path), size=size, index=0)


def _wrap(draw, text: str, font, width: int, max_lines: int = 2) -> list[str]:
    text = " ".join((text or "").replace("\n", " ").split())
    if not text:
        return []
    lines: list[str] = []
    start = 0
    while start < len(text) and len(lines) < max_lines:
        end = start + 1
        while end <= len(text) and draw.textlength(text[start:end], font=font) <= width:
            end += 1
        end = max(start + 1, end - 1)
        chunk = text[start:end]
        if len(lines) == max_lines - 1 and end < len(text):
            while chunk and draw.textlength(chunk + "…", font=font) > width:
                chunk = chunk[:-1]
            chunk = f"{chunk}…" if chunk else "…"
            end = len(text)
        lines.append(chunk)
        start = end
    return lines


def render_placeholder_image(card: _Card, font_path: Path, fps: int = EXPORT_FPS):
    """Solid role color, burned-in slot card, region badge in the top corner."""

    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ValueError("找不到 Pillow，不能生成占位画面。") from exc

    rgb = _ROLE_RGB.get(card.role, _ROLE_RGB["unknown"])
    image = Image.new("RGB", (WIDTH, HEIGHT), rgb)
    plate = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    plate_draw = ImageDraw.Draw(plate)
    plate_draw.rectangle((0, 0, WIDTH, 220), fill=(0, 0, 0, 130))
    plate_draw.rectangle((48, 430, WIDTH - 48, 1240), fill=(0, 0, 0, 78))
    image = Image.alpha_composite(image.convert("RGBA"), plate).convert("RGB")
    draw = ImageDraw.Draw(image)
    if card.is_drop:
        draw.rectangle((18, 18, WIDTH - 19, HEIGHT - 19), outline=(240, 200, 74), width=16)
    title = _font(font_path, 108)
    mid = _font(font_path, 58)
    small = _font(font_path, 46)
    badge = _font(font_path, 54)
    ink = (255, 255, 255)
    gold = (255, 214, 90)
    role_zh = ROLE_LABELS_ZH.get(card.role, card.role)
    draw.text((56, 48), f"{card.slot.region_id}  {role_zh}", font=badge, fill=ink)
    if card.slot.flurry_group:
        label = "快闪"
        width = draw.textlength(label, font=badge)
        draw.text((WIDTH - 56 - width, 48), label, font=badge, fill=gold)
    if card.is_drop:
        draw.text((56, 130), "落点", font=badge, fill=gold)
    if card.slot.technique_name_zh:
        draw.text((56, 210), card.slot.technique_name_zh, font=badge, fill=gold)
    y = 500
    slot_line = card.slot.slot_id
    if card.slot.reserve_best:
        slot_line = f"★  {slot_line}"
    draw.text((80, y), slot_line, font=title, fill=gold if card.slot.reserve_best or card.is_drop else ink)
    y += 150
    if card.slot.reserve_best:
        draw.text((80, y), "最好一镜", font=mid, fill=gold)
        y += 90
    draw.text((80, y), f"景别  {_size_zh(card.slot)}", font=mid, fill=ink)
    y += 90
    draw.text((80, y), f"转场  {_transition_zh(card.slot)}", font=mid, fill=ink)
    y += 90
    seconds = (card.end - card.start) / fps
    draw.text((80, y), f"时长  {seconds:.2f} 秒", font=mid, fill=ink)
    hint_font = small
    hint_y = 1360
    for line in _wrap(draw, card.slot.content_hint or "画面待定", hint_font, WIDTH - 160, 2):
        draw.text((80, hint_y), line, font=hint_font, fill=ink)
        hint_y += 70
    if card.slot.flurry_group:
        tick = 64
        left = 80
        for _index in range(8):
            draw.rectangle((left, HEIGHT - 160, left + 28, HEIGHT - 70), fill=ink)
            left += tick
    return image


def _encode_still(ffmpeg: str, still: Path, frames: int, destination: Path) -> None:
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(EXPORT_FPS),
            "-i",
            str(still),
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            "-tune",
            "stillimage",
            "-an",
            str(destination),
        ],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not destination.is_file():
        detail = completed.stderr.decode("utf-8", "replace").strip().replace("\n", " ")
        raise ValueError(f"生成占位视频失败：{destination.name}。{detail[:180]}")


def _write_one(ffmpeg: str, font_path: Path, card: _Card, directory: Path) -> str:
    destination = directory / card.filename
    still = destination.with_suffix(".png")
    render_placeholder_image(card, font_path).save(still, format="PNG")
    try:
        _encode_still(ffmpeg, still, card.end - card.start, destination)
    finally:
        still.unlink(missing_ok=True)
    return card.filename


def _build_placeholders(cards: list[_Card], staging: Path) -> None:
    ffmpeg = ffmpeg_executable()
    font_path = cjk_font_path()
    staging.mkdir(parents=True, exist_ok=True)
    workers = min(8, len(cards))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_write_one, ffmpeg, font_path, card, staging) for card in cards]
        for future in futures:
            future.result()


def write_regions_fcpxml(document, audio: FrozenAudio, output_dir: Path) -> RegionsFcpxmlExport:
    """Write ``project.fcpxml``, the edit sheet, music, and one video per shot.

    An existing package is overwritten: placeholders, the FCPXML, the sheet,
    and the linked music file. A failed encode removes only the staging
    directory and leaves a previous package in place.
    """

    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError("导出位置已经有一个同名文件，没有覆盖。")
    if not audio.path.is_file():
        raise ValueError("冻结的配乐文件不在了，不能导出。")
    regions: MusicEditRegions = document.regions
    fps = EXPORT_FPS
    cards = _cards(regions, fps)
    ffmpeg_executable()
    cjk_font_path()
    picture_end = cards[-1].end
    audio_frames = max(1, frame_index(audio.duration_seconds, fps))
    sequence_frames = max(picture_end, audio_frames)
    safe_name = audio.path.name.replace("/", "_")
    asset_dir = output_dir / "asset"
    staging = asset_dir / ".placeholders-staging"
    final = asset_dir / "placeholders"
    if staging.exists():
        shutil.rmtree(staging)
    try:
        _build_placeholders(cards, staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if final.exists():
        shutil.rmtree(final)
    staging.rename(final)

    asset_path = asset_dir / safe_name
    _link_audio(audio.path, asset_path)
    fcpxml = ET.Element("fcpxml", version="1.9")
    fcpxml.append(
        ET.Comment(
            " " + JIANYING_FCPXML_NOTICE + " " + _OVERLAY_REASON + " " + _FRAME_RATE_NOTE + " "
        )
    )
    resources = ET.SubElement(fcpxml, "resources")
    ET.SubElement(
        resources,
        "format",
        id="project-format",
        name=f"FFVideoFormat{WIDTH}x{HEIGHT}p{fps}",
        frameDuration=f"1/{fps}s",
        width=str(WIDTH),
        height=str(HEIGHT),
        colorSpace="1-1-1 (Rec. 709)",
    )
    for index, card in enumerate(cards, start=1):
        path = final / card.filename
        ET.SubElement(
            resources,
            "asset",
            id=f"v{index}",
            name=card.filename,
            src=path.resolve().as_uri(),
            start="0s",
            duration=_fcpx_time(card.end - card.start, fps),
            hasVideo="1",
            format="project-format",
        )
    ET.SubElement(
        resources,
        "asset",
        id="music-asset",
        name=safe_name,
        src=asset_path.resolve().as_uri(),
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
    first_clip = None
    for index, card in enumerate(cards, start=1):
        clip = ET.SubElement(
            spine,
            "asset-clip",
            ref=f"v{index}",
            name=card.filename,
            offset=_fcpx_time(card.start, fps),
            start="0s",
            duration=_fcpx_time(card.end - card.start, fps),
        )
        if first_clip is None:
            first_clip = clip
        for mark_at, label in marks:
            if card.start <= mark_at < card.end:
                ET.SubElement(
                    clip,
                    "marker",
                    start=_fcpx_time(mark_at - card.start, fps),
                    duration=f"1/{fps}s",
                    value=label,
                )
    if first_clip is None:
        raise ValueError("没有可导出的时间线。")
    ET.SubElement(
        first_clip,
        "asset-clip",
        ref="music-asset",
        name=safe_name,
        lane="-1",
        offset=_fcpx_time(cards[0].start, fps),
        start="0s",
        duration=_fcpx_time(audio_frames, fps),
        audioRole="music",
    )
    ET.indent(fcpxml, space="  ")
    payload = ET.tostring(fcpxml, encoding="utf-8", xml_declaration=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    fcpxml_path = output_dir / "project.fcpxml"
    sheet_path = output_dir / "edit-sheet.md"
    temporary = fcpxml_path.with_suffix(".fcpxml.tmp")
    temporary.write_bytes(payload)
    temporary.replace(fcpxml_path)
    sheet_path.write_text(_sheet(document.version_id, regions, cards, fps), encoding="utf-8")
    return RegionsFcpxmlExport(
        fcpxml_path=fcpxml_path,
        sheet_path=sheet_path,
        frame_rate=fps,
        version_id=document.version_id,
        notice=JIANYING_FCPXML_NOTICE,
    )
