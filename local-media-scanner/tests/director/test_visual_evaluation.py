from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError
from typer.testing import CliRunner

from director.cli import app
from director.evaluation import (
    DirectorVisualGroundTruth,
    build_evaluation_split,
    build_ground_truth_template,
    evaluate_duplicate_fixture,
    validate_ground_truth,
)
from scanner.schema import (
    ManifestEntry,
    SourceRecord,
    TechnicalMetadata,
    TestManifest as ManifestModel,
)


def entry(index: int) -> ManifestEntry:
    orientation = "portrait" if index % 7 == 0 else "landscape"
    duration = [2.0, 5.0, 12.0, 35.0][index % 4]
    return ManifestEntry(
        file=f"clip-{index:02d}.mov",
        source=SourceRecord(
            relative_path=f"clip-{index:02d}.mov",
            size_bytes=1000 + index,
            mtime_ns=100 + index,
        ),
        technical=TechnicalMetadata(
            duration=duration,
            width=1080 if orientation == "portrait" else 1920,
            height=1920 if orientation == "portrait" else 1080,
            fps=25.0 + index % 2 * 5,
            orientation=orientation,
            codec="h264",
            creation_time=f"2026-02-{1 + index // 6:02d}T{index % 24:02d}:00:00Z",
        ),
    )


def manifest() -> ManifestModel:
    return ManifestModel(input_root="/videos", entries=[entry(i) for i in range(30)])


def cv_rows() -> list[dict]:
    return [
        {
            "file": f"clip-{i:02d}.mov",
            "brightness_score": i / 30,
            "laplacian_variance_raw": 100 + i * 50,
            "motion_intensity_raw": (i % 10) / 10,
        }
        for i in range(30)
    ]


def test_split_is_deterministic_disjoint_and_exact_12_12_6() -> None:
    first = build_evaluation_split(
        manifest(), cv_rows(), source_manifest_sha256="a" * 64
    )
    second = build_evaluation_split(
        manifest(), cv_rows(), source_manifest_sha256="a" * 64
    )

    assert first.model_dump() == second.model_dump()
    assert len(first.dev.entries) == 12
    assert len(first.blind.entries) == 12
    assert len(first.reserve.entries) == 6
    groups = [
        {row.source.relative_path for row in split.entries}
        for split in (first.dev, first.blind, first.reserve)
    ]
    assert groups[0].isdisjoint(groups[1])
    assert groups[0].isdisjoint(groups[2])
    assert groups[1].isdisjoint(groups[2])
    assert set.union(*groups) == {
        row.source.relative_path for row in manifest().entries
    }
    assert first.dev_membership_sha256 != first.blind_membership_sha256


def test_ground_truth_template_covers_membership_without_fake_labels() -> None:
    split = build_evaluation_split(
        manifest(), cv_rows(), source_manifest_sha256="a" * 64
    )
    source_hashes = {
        row.source.relative_path: f"{index + 1:064x}"
        for index, row in enumerate(split.dev.entries + split.blind.entries)
    }
    template = build_ground_truth_template(split, source_hashes)

    assert len(template.records) == 24
    assert all(not record.completed for record in template.records)
    assert all(record.content_families == ["unknown"] for record in template.records)
    validate_ground_truth(template, split, require_completed=False)
    with pytest.raises(ValueError, match="incomplete"):
        validate_ground_truth(template, split, require_completed=True)


def test_ground_truth_rejects_unknown_or_duplicate_material() -> None:
    split = build_evaluation_split(
        manifest(), cv_rows(), source_manifest_sha256="a" * 64
    )
    source_hashes = {
        row.source.relative_path: f"{index + 1:064x}"
        for index, row in enumerate(split.dev.entries + split.blind.entries)
    }
    template = build_ground_truth_template(split, source_hashes)
    duplicate = template.model_copy(
        update={"records": [template.records[0], *template.records]}
    )

    with pytest.raises(ValueError, match="duplicate"):
        validate_ground_truth(duplicate, split, require_completed=False)
    with pytest.raises(ValidationError):
        DirectorVisualGroundTruth.model_validate(
            template.model_dump() | {"silently_use_model_predictions": True}
        )


def _pattern(path: Path, *, vertical: bool) -> None:
    image = Image.new("L", (64, 64), 255)
    draw = ImageDraw.Draw(image)
    if vertical:
        draw.rectangle((8, 0, 20, 63), fill=0)
        draw.rectangle((38, 0, 50, 63), fill=80)
    else:
        draw.rectangle((0, 8, 63, 20), fill=0)
        draw.rectangle((0, 38, 63, 50), fill=80)
    image.save(path)


def test_duplicate_fixture_separates_exact_near_and_distinct(tmp_path: Path) -> None:
    original = tmp_path / "original.png"
    exact = tmp_path / "exact.png"
    near = tmp_path / "near.jpg"
    distinct = tmp_path / "distinct.png"
    _pattern(original, vertical=True)
    exact.write_bytes(original.read_bytes())
    Image.open(original).resize((60, 60)).save(near, quality=82)
    _pattern(distinct, vertical=False)

    result = evaluate_duplicate_fixture(original, exact, near, distinct)

    assert result.exact_match is True
    assert result.near_match is True
    assert result.distinct_match is False
    assert result.real_pair_status == "not_evaluated_real_pair"


def test_ground_truth_cli_allows_blank_template_only_when_explicit(tmp_path: Path) -> None:
    split = build_evaluation_split(
        manifest(), cv_rows(), source_manifest_sha256="a" * 64
    )
    source_hashes = {
        row.source.relative_path: f"{index + 1:064x}"
        for index, row in enumerate(split.dev.entries + split.blind.entries)
    }
    template = build_ground_truth_template(split, source_hashes)
    split_path = tmp_path / "split.json"
    template_path = tmp_path / "template.json"
    split_path.write_text(split.model_dump_json(), encoding="utf-8")
    template_path.write_text(template.model_dump_json(), encoding="utf-8")
    runner = CliRunner()

    strict = runner.invoke(
        app,
        [
            "validate-visual-ground-truth",
            "--split",
            str(split_path),
            "--ground-truth",
            str(template_path),
        ],
    )
    template_only = runner.invoke(
        app,
        [
            "validate-visual-ground-truth",
            "--split",
            str(split_path),
            "--ground-truth",
            str(template_path),
            "--allow-incomplete",
        ],
    )

    assert strict.exit_code != 0
    assert template_only.exit_code == 0, template_only.output
    assert "valid" in template_only.stdout
