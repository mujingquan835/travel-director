from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _beat_this_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep beat analysis on librosa, as on CI.

    A machine with the ``beat`` extra and a cached checkpoint would otherwise
    switch ``auto`` to beat_this and change the expected beats. A test that
    needs beat_this can patch ``beat_this_module`` again.
    """

    def _missing():
        raise ImportError("beat_this is disabled in tests")

    monkeypatch.setattr("director.beat_grid.beat_this_module", _missing)


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

