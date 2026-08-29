from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from director.render import build_ffmpeg_command, render_preview, verify_render_result
from director.schema import ClipPlacement, SfxPlan


def placement(path: Path, slot_id: str) -> ClipPlacement:
    return ClipPlacement(
        slot_id=slot_id,
        file=str(path),
        source_in=0,
        source_out=2,
        source_duration=4,
        section_role="rise",
    )


@pytest.fixture
def synthetic_project(tmp_path: Path) -> dict[str, object]:
    videos = []
    for index, color in enumerate(("red", "blue"), start=1):
        output = tmp_path / f"source-{index}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=360x640:d=4:r=24",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(output),
            ],
            check=True,
        )
        videos.append(output)
    sample_rate = 22_050
    times = np.arange(sample_rate * 4, dtype=np.float32) / sample_rate
    audio = (0.1 * np.sin(2 * np.pi * 440 * times)).astype(np.float32)
    music = tmp_path / "music.wav"
    sf.write(music, audio, sample_rate, subtype="PCM_16")
    return {
        "placements": [
            placement(videos[0], "slot-001"),
            placement(videos[1], "slot-002"),
        ],
        "music": music,
        "sfx_plan": SfxPlan(status="completed", items=[]),
        "output": tmp_path / "render" / "montage.mp4",
        "orientation": "portrait",
        "music_duration_seconds": 4.0,
    }


def test_ffmpeg_command_is_argument_list_without_shell(
    synthetic_project: dict[str, object],
) -> None:
    command = build_ffmpeg_command(
        synthetic_project["placements"],
        synthetic_project["music"],
        synthetic_project["sfx_plan"],
        synthetic_project["output"],
        synthetic_project["orientation"],
    )

    assert command[0] == "ffmpeg"
    assert "-filter_complex" in command
    assert all("; rm " not in argument for argument in command)


def test_rendered_duration_matches_music_within_frame(
    synthetic_project: dict[str, object],
) -> None:
    source_hashes = {
        item.file: hashlib.sha256(Path(item.file).read_bytes()).hexdigest()
        for item in synthetic_project["placements"]
    }

    result = render_preview(**synthetic_project)

    assert result.status == "completed"
    assert result.duration_seconds is not None
    assert abs(
        result.duration_seconds - synthetic_project["music_duration_seconds"]
    ) <= 1 / 24
    assert result.width == 720
    assert result.height == 1280
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == source_hash
        for path, source_hash in source_hashes.items()
    )
    assert verify_render_result(result) is True


def test_render_result_verification_detects_output_drift(
    synthetic_project: dict[str, object],
) -> None:
    result = render_preview(**synthetic_project)
    Path(result.output_path).write_bytes(b"drifted")

    assert verify_render_result(result) is False
