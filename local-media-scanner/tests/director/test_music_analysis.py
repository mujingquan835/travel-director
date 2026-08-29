from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from director.cli import app
from director.music_analysis import AudioAnalysisConfig, analyze_music


def test_audio_analysis_measures_actual_structure(click_track: Path) -> None:
    result = analyze_music(click_track, AudioAnalysisConfig())

    assert 116 <= result.bpm <= 124
    assert len(result.beats_seconds) >= 100
    assert any(
        section.role == "breath" and 20 <= section.start <= 30
        for section in result.sections
    )
    assert result.ending.last_onset_seconds is not None
    assert result.ending.last_onset_seconds >= 59
    assert result.energy_curve
    assert result.confidence > 0


def test_audio_analysis_hashes_the_actual_source(click_track: Path) -> None:
    result = analyze_music(click_track, AudioAnalysisConfig())
    expected = hashlib.sha256(click_track.read_bytes()).hexdigest()

    assert result.source_sha256 == expected


def test_analyze_music_cli_writes_measured_json(
    click_track: Path, tmp_path: Path
) -> None:
    output = tmp_path / "music-structure.json"

    result = CliRunner().invoke(
        app,
        ["analyze-music", "--audio", str(click_track), "--output", str(output)],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert 116 <= payload["bpm"] <= 124
    assert payload["duration_seconds"] == 60.0
