from __future__ import annotations

from pathlib import Path

import pytest

import director.audio_import as audio_import
from director.project import create_visual_project
from director.visual_schema import RawCreativeBrief


def test_music_longer_than_ten_minutes_is_rejected_before_project_write(
    tmp_path: Path, monkeypatch
) -> None:
    paths = create_visual_project(
        tmp_path / "runs",
        "demo",
        RawCreativeBrief(raw_description="60秒旅行视频"),
    )
    music = tmp_path / "too-long.wav"
    music.write_bytes(b"placeholder")
    before = paths.project_state.read_bytes()
    monkeypatch.setattr(
        audio_import,
        "_probe_audio",
        lambda _path: (600.1, 44_100, 2, "wav"),
    )

    with pytest.raises(ValueError, match="10 minutes"):
        audio_import.freeze_and_analyze_music(paths, music)

    assert paths.project_state.read_bytes() == before
    assert not paths.generated_music.exists()
    assert not paths.music_structure.exists()
    assert not (paths.generation_dir / "assets").exists()


def test_extension_must_match_the_ffprobe_container(
    tmp_path: Path, click_track: Path
) -> None:
    paths = create_visual_project(
        tmp_path / "runs",
        "demo",
        RawCreativeBrief(raw_description="60秒旅行视频"),
    )
    disguised = tmp_path / "disguised.mp3"
    disguised.write_bytes(click_track.read_bytes())
    before = paths.project_state.read_bytes()

    with pytest.raises(ValueError, match="container does not match"):
        audio_import.freeze_and_analyze_music(paths, disguised)

    assert paths.project_state.read_bytes() == before
    assert not paths.generated_music.exists()
    assert not paths.music_structure.exists()
    assert not (paths.generation_dir / "assets").exists()
