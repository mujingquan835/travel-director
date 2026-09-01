from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from scanner.cli import app
from scanner.metadata import MetadataError, build_manifest, discover_videos, probe_video


def test_probe_video_reads_duration_dimensions_fps_and_orientation(sample_video: Path) -> None:
    meta = probe_video(sample_video)

    assert meta.duration == pytest.approx(1.2, abs=0.08)
    assert (meta.width, meta.height) == (320, 240)
    assert meta.fps == pytest.approx(25.0, abs=0.01)
    assert meta.orientation == "landscape"
    assert meta.codec == "h264"


def test_discovery_is_case_insensitive_sorted_and_recursive(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "b.MOV").touch()
    (nested / "a.mp4").touch()
    (tmp_path / "ignored.txt").touch()

    assert [path.relative_to(tmp_path).as_posix() for path in discover_videos(tmp_path)] == [
        "b.MOV",
        "nested/a.mp4",
    ]


def test_probe_video_reports_corrupt_input_without_guessing(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mov"
    broken.write_bytes(b"not a video")

    with pytest.raises(MetadataError) as error:
        probe_video(broken)

    assert error.value.code == "ffprobe_failed"


def test_build_manifest_uses_relative_paths_and_totals(sample_video: Path) -> None:
    manifest = build_manifest(sample_video.parent, [sample_video])

    assert manifest.entries[0].file == "fixture.mp4"
    assert manifest.entries[0].source.relative_path == "fixture.mp4"
    assert manifest.total_duration_seconds == pytest.approx(1.2, abs=0.08)
    assert manifest.total_size_bytes == sample_video.stat().st_size


def test_inspect_accepts_input_option(sample_video: Path) -> None:
    result = CliRunner().invoke(app, ["inspect", "--input", str(sample_video.parent)])

    assert result.exit_code == 0
    assert '"file": "fixture.mp4"' in result.stdout


def test_inspect_writes_the_validated_manifest_when_output_is_given(
    sample_video: Path, tmp_path: Path
) -> None:
    output = tmp_path / "manifest.json"

    result = CliRunner().invoke(
        app, ["inspect", "--input", str(sample_video.parent), "--output", str(output)]
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == str(output)
    written = build_manifest(sample_video.parent, [sample_video])
    assert output.read_text(encoding="utf-8") == written.model_dump_json(indent=2)
