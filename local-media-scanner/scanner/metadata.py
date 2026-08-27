"""Read-only discovery and ffprobe metadata extraction."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

from scanner.schema import ManifestEntry, SourceRecord, TechnicalMetadata, TestManifest


VIDEO_EXTENSIONS = frozenset({".mov", ".mp4", ".m4v", ".avi", ".mkv"})


class MetadataError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def discover_videos(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise MetadataError("input_not_directory", f"Not a directory: {input_dir}")
    return sorted(
        (path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS),
        key=lambda path: path.relative_to(input_dir).as_posix().casefold(),
    )


def _parse_fps(raw: str | None) -> float:
    if not raw or raw == "0/0":
        return 0.0
    try:
        return float(Fraction(raw))
    except (ValueError, ZeroDivisionError) as exc:
        raise MetadataError("invalid_metadata", f"Invalid frame rate: {raw}") from exc


def _rotation(stream: dict[str, Any]) -> int | None:
    raw = stream.get("tags", {}).get("rotate")
    if raw is None:
        for item in stream.get("side_data_list", []):
            if item.get("rotation") is not None:
                raw = item["rotation"]
                break
    if raw is None:
        return None
    try:
        return int(round(float(raw))) % 360
    except (TypeError, ValueError) as exc:
        raise MetadataError("invalid_metadata", f"Invalid rotation: {raw}") from exc


def parse_ffprobe_payload(payload: dict[str, Any]) -> TechnicalMetadata:
    streams = payload.get("streams") or []
    if not streams:
        raise MetadataError("no_video_stream", "ffprobe returned no video stream")
    stream = streams[0]
    file_format = payload.get("format") or {}
    try:
        width = int(stream["width"])
        height = int(stream["height"])
        duration = float(file_format.get("duration", stream.get("duration", 0.0)))
    except (KeyError, TypeError, ValueError) as exc:
        raise MetadataError("invalid_metadata", "Missing or invalid dimensions/duration") from exc

    rotation = _rotation(stream)
    display_width, display_height = (height, width) if rotation in {90, 270} else (width, height)
    if display_width > display_height:
        orientation = "landscape"
    elif display_height > display_width:
        orientation = "portrait"
    else:
        orientation = "square"

    tags = stream.get("tags") or {}
    return TechnicalMetadata(
        duration=duration,
        width=width,
        height=height,
        fps=_parse_fps(stream.get("avg_frame_rate")),
        orientation=orientation,
        codec=str(stream.get("codec_name") or "unknown"),
        creation_time=tags.get("creation_time"),
        rotation=rotation,
    )


def probe_video(path: Path, ffprobe_bin: str = "ffprobe") -> TechnicalMetadata:
    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "format=duration,size:stream=codec_name,width,height,avg_frame_rate,duration:"
        "stream_tags=creation_time,rotate:stream_side_data=rotation",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise MetadataError("ffprobe_missing", f"ffprobe not found: {ffprobe_bin}") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or "ffprobe failed without stderr"
        raise MetadataError("ffprobe_failed", message)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MetadataError("invalid_metadata", "ffprobe returned invalid JSON") from exc
    return parse_ffprobe_payload(payload)


def build_manifest(input_dir: Path, paths: Sequence[Path]) -> TestManifest:
    root = input_dir.resolve()
    entries: list[ManifestEntry] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise MetadataError("outside_input_root", f"Path is outside input root: {path}") from exc
        stat = resolved.stat()
        technical = probe_video(resolved)
        entries.append(
            ManifestEntry(
                file=path.name,
                source=SourceRecord(
                    relative_path=relative,
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                ),
                technical=technical,
            )
        )
    return TestManifest(
        input_root=str(root),
        entries=entries,
        total_duration_seconds=sum(entry.technical.duration for entry in entries),
        total_size_bytes=sum(entry.source.size_bytes for entry in entries),
    )

