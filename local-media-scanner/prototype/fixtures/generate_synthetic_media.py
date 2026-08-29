"""Generate deterministic, non-private audio/video fixtures for prototype checks."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


SAMPLE_RATE = 22_050
DURATION_SECONDS = 60
VIDEO_COLORS = ["red", "orange", "green", "blue", "purple"]


def generate_click_track(output: Path) -> None:
    audio = np.zeros(SAMPLE_RATE * DURATION_SECONDS, dtype=np.float32)
    click_length = int(0.045 * SAMPLE_RATE)
    click_shape = np.exp(-np.linspace(0.0, 8.0, click_length)).astype(np.float32)

    for beat_time in np.arange(0.0, DURATION_SECONDS, 0.5):
        if beat_time < 7.0:
            amplitude = 0.35
        elif beat_time < 24.0:
            amplitude = 0.65
        elif beat_time < 31.0:
            amplitude = 0.08
        elif beat_time < 54.0:
            amplitude = 0.9
        else:
            amplitude = 0.45
        start = int(beat_time * SAMPLE_RATE)
        end = min(start + click_length, len(audio))
        audio[start:end] += amplitude * click_shape[: end - start]

    final_start = int(59.5 * SAMPLE_RATE)
    audio[final_start : final_start + click_length] += click_shape
    sf.write(output, audio, SAMPLE_RATE, subtype="PCM_16")


def generate_color_videos(output_dir: Path) -> None:
    for index, color in enumerate(VIDEO_COLORS, start=1):
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
                f"color=c={color}:s=720x1280:d=12:r=30",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(output_dir / f"color-{index:02d}-{color}.mp4"),
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate_click_track(args.output_dir / "click-track-120bpm.wav")
    generate_color_videos(args.output_dir)


if __name__ == "__main__":
    main()
