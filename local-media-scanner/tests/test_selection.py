from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from scanner.cli import app
from scanner.schema import ManifestEntry, SourceRecord, TechnicalMetadata, TestManifest as ManifestModel
from scanner.selection import propose_stratified_set, render_manual_review_sheet


def _entry(index: int, *, duration: float, orientation: str, day: int) -> ManifestEntry:
    return ManifestEntry(
        file=f"clip-{index}.mov",
        source=SourceRecord(relative_path=f"clip-{index}.mov", size_bytes=100 + index, mtime_ns=index),
        technical=TechnicalMetadata(
            duration=duration,
            width=1080 if orientation == "portrait" else 1920,
            height=1920 if orientation == "portrait" else 1080,
            fps=30,
            orientation=orientation,
            codec="h264",
            creation_time=f"2026-02-{day:02d}T0{index % 9}:00:00Z",
        ),
    )


def _manifest() -> ManifestModel:
    entries = [
        _entry(0, duration=1.0, orientation="portrait", day=6),
        _entry(1, duration=45.0, orientation="landscape", day=6),
        _entry(2, duration=5.0, orientation="landscape", day=7),
        _entry(3, duration=7.0, orientation="landscape", day=7),
        _entry(4, duration=12.0, orientation="landscape", day=8),
        _entry(5, duration=15.0, orientation="landscape", day=8),
        _entry(6, duration=8.0, orientation="landscape", day=9),
        _entry(7, duration=9.0, orientation="landscape", day=9),
    ]
    return ManifestModel(input_root="/videos", entries=entries)


def test_selection_is_deterministic_and_preserves_rare_strata() -> None:
    first = propose_stratified_set(_manifest(), [], count=6, seed=20260827)
    second = propose_stratified_set(_manifest(), [], count=6, seed=20260827)

    assert first.model_dump() == second.model_dump()
    assert {row.technical.orientation for row in first.entries} == {"landscape", "portrait"}
    assert any(row.technical.duration < 3 for row in first.entries)
    assert any(row.technical.duration > 30 for row in first.entries)


def test_selection_recomputes_manifest_totals() -> None:
    selected = propose_stratified_set(_manifest(), [], count=3, seed=1)

    assert len(selected.entries) == 3
    assert selected.total_duration_seconds == sum(row.technical.duration for row in selected.entries)
    assert selected.total_size_bytes == sum(row.source.size_bytes for row in selected.entries)


def test_select_testset_command_writes_manifest_and_unpredicted_contact_sheet(
    sample_video: Path,
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "selected.json"
    contact_sheet = tmp_path / "selection.html"

    result = CliRunner().invoke(
        app,
        [
            "select-testset",
            "--input",
            str(sample_video.parent),
            "--count",
            "1",
            "--seed",
            "20260827",
            "--manifest",
            str(manifest),
            "--contact-sheet",
            str(contact_sheet),
        ],
    )

    assert result.exit_code == 0
    assert ManifestModel.model_validate_json(manifest.read_text()).entries[0].file == "fixture.mp4"
    html = contact_sheet.read_text(encoding="utf-8")
    assert "fixture.mp4" in html
    assert "no model predictions" in html.lower()
    assert "scene_type" not in html
    assert "shot_scale" not in html


def test_manual_review_sheet_renders_all_sparse_frames_without_predictions(tmp_path: Path) -> None:
    sampling_result = tmp_path / "sampling_result.json"
    sampling_result.write_text(
        """{
          "items": [{
            "file": "clip-1.mov",
            "representative_frames": [
              {"timestamp": 1.25, "reasons": ["temporal"], "thumbnail_relpath": "frames/a.jpg"},
              {"timestamp": 4.5, "reasons": ["motion"], "thumbnail_relpath": "frames/b.jpg"}
            ]
          }]
        }""",
        encoding="utf-8",
    )
    output = tmp_path / "manual_review.html"

    render_manual_review_sheet(sampling_result, output)

    html = output.read_text(encoding="utf-8")
    assert "clip-1.mov" in html
    assert "frames/a.jpg" in html
    assert "frames/b.jpg" in html
    assert "1.250s" in html
    assert "motion" in html
    assert "no model predictions" in html.lower()
    assert "scene_type" not in html
