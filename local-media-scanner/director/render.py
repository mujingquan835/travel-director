"""Build and execute bounded local FFmpeg preview renders."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import Field

from director.schema import ClipPlacement, ProviderError, SfxPlan, StageStatus, StrictModel


class RenderResult(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    status: StageStatus
    output_path: str
    sha256: str | None = None
    duration_seconds: float | None = Field(default=None, gt=0.0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    video_codec: str | None = None
    audio_codec: str | None = None
    errors: list[ProviderError] = Field(default_factory=list)


def _dimensions(orientation: str) -> tuple[int, int]:
    if orientation == "portrait":
        return 720, 1280
    if orientation == "landscape":
        return 1280, 720
    raise ValueError("orientation must be portrait or landscape")


def _number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def build_ffmpeg_command(
    placements: list[ClipPlacement],
    music: Path,
    sfx_plan: SfxPlan,
    output: Path,
    orientation: str,
) -> list[str]:
    """Return a shell-free FFmpeg argv list for one bounded preview."""

    if not placements:
        raise ValueError("at least one placement is required")
    width, height = _dimensions(orientation)
    source_paths = [Path(item.file).resolve() for item in placements]
    music_path = music.resolve()
    output_path = output.resolve()
    if output_path == music_path or output_path in source_paths:
        raise ValueError("render output must not overwrite an input")

    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for source in source_paths:
        command.extend(["-i", str(source)])
    command.extend(["-i", str(music_path)])

    filters: list[str] = []
    video_labels: list[str] = []
    for index, placement in enumerate(placements):
        label = f"v{index}"
        filters.append(
            f"[{index}:v]trim=start={_number(placement.source_in)}:"
            f"end={_number(placement.source_out)},setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps=24,format=yuv420p[{label}]"
        )
        video_labels.append(f"[{label}]")
    filters.append(
        f"{''.join(video_labels)}concat=n={len(placements)}:v=1:a=0[vout]"
    )

    total_duration = sum(item.source_out - item.source_in for item in placements)
    music_index = len(placements)
    filters.append(
        f"[{music_index}:a]atrim=start=0:end={_number(total_duration)},"
        "asetpts=PTS-STARTPTS,volume=1[musicbed]"
    )
    planned_original_files = {
        item.file
        for item in sfx_plan.items
        if item.decision in {"keep_original", "enhance_original"}
    }
    original_labels: list[str] = []
    timeline_cursor = 0.0
    for index, placement in enumerate(placements):
        if placement.file in planned_original_files:
            label = f"orig{index}"
            delay_ms = round(timeline_cursor * 1000)
            filters.append(
                f"[{index}:a]atrim=start={_number(placement.source_in)}:"
                f"end={_number(placement.source_out)},asetpts=PTS-STARTPTS,"
                f"adelay={delay_ms}|{delay_ms},volume=0.45[{label}]"
            )
            original_labels.append(f"[{label}]")
        timeline_cursor += placement.source_out - placement.source_in
    if original_labels:
        filters.append(
            f"[musicbed]{''.join(original_labels)}"
            f"amix=inputs={1 + len(original_labels)}:duration=first:"
            "dropout_transition=0[aout]"
        )
    else:
        filters.append("[musicbed]anull[aout]")

    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-r",
            "24",
            "-t",
            _number(total_duration),
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return command


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_render_result(result: RenderResult) -> bool:
    """Verify that a recorded render still points to the same local bytes."""

    output = Path(result.output_path)
    return (
        result.status == "completed"
        and result.sha256 is not None
        and output.is_file()
        and _sha256_file(output) == result.sha256
    )


def _probe(output: Path) -> tuple[float, int, int, str, str]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(output),
        ],
        shell=False,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    video = next(row for row in payload["streams"] if row["codec_type"] == "video")
    audio = next(row for row in payload["streams"] if row["codec_type"] == "audio")
    return (
        float(payload["format"]["duration"]),
        int(video["width"]),
        int(video["height"]),
        str(video["codec_name"]),
        str(audio["codec_name"]),
    )


def render_preview(
    placements: list[ClipPlacement],
    music: Path,
    sfx_plan: SfxPlan,
    output: Path,
    orientation: str,
    music_duration_seconds: float | None = None,
) -> RenderResult:
    """Render to a new file and verify codecs, dimensions, hash, and duration."""

    output_path = output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_command(
        placements,
        music,
        sfx_plan,
        output_path,
        orientation,
    )
    placement_duration = sum(
        item.source_out - item.source_in for item in placements
    )
    if (
        music_duration_seconds is not None
        and abs(placement_duration - music_duration_seconds) > 1 / 24
    ):
        return RenderResult(
            status="failed",
            output_path=str(output_path),
            errors=[
                ProviderError(
                    stage="render",
                    code="duration_contract_mismatch",
                    message="Placement duration does not match requested music duration.",
                )
            ],
        )

    try:
        subprocess.run(
            command,
            shell=False,
            check=True,
            capture_output=True,
            text=True,
        )
        duration, width, height, video_codec, audio_codec = _probe(output_path)
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as exc:
        stderr = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else None
        message = (stderr or str(exc))[-4000:]
        return RenderResult(
            status="failed",
            output_path=str(output_path),
            errors=[
                ProviderError(
                    stage="render",
                    code="ffmpeg_failed",
                    message=message,
                )
            ],
        )

    return RenderResult(
        status="completed",
        output_path=str(output_path),
        sha256=_sha256_file(output_path),
        duration_seconds=duration,
        width=width,
        height=height,
        video_codec=video_codec,
        audio_codec=audio_codec,
    )
