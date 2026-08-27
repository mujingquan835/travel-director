from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def sample_video(tmp_path: Path) -> Path:
    output = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:r=25",
            "-t",
            "1.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        check=True,
    )
    return output

