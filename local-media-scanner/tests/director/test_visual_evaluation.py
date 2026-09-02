from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError
from typer.testing import CliRunner

from director.cli import app
from director.evaluation import (
    BlindAnnotationBundle,
    DirectorGroundTruthRecord,
    DirectorVisualGroundTruth,
    GroundTruthRecord,
    build_evaluation_split,
    build_ground_truth_template,
    evaluate_duplicate_fixture,
    sha256_file,
    validate_blind_annotation_bundle,
    validate_ground_truth,
)
from director.visual_schema import BriefConfirmation, NormalizedBriefFields
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


def test_ground_truth_rejects_ambiguous_unknown_and_people_labels() -> None:
    base = {
        "material_id": f"sha256:{'1' * 64}",
        "source_sha256": "1" * 64,
        "file": "blind.mov",
        "split": "blind",
    }

    with pytest.raises(ValidationError, match="unknown content family"):
        GroundTruthRecord.model_validate(
            base | {"content_families": ["unknown", "urban"]}
        )
    with pytest.raises(ValidationError, match="present people cannot have none"):
        GroundTruthRecord.model_validate(
            base | {"people_presence": "present", "people_count_band": "none"}
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


def test_blind_annotation_bundle_requires_complete_independent_labels() -> None:
    split = build_evaluation_split(
        manifest(), cv_rows(), source_manifest_sha256="a" * 64
    )
    source_hashes = {
        row.source.relative_path: f"{index + 1:064x}"
        for index, row in enumerate(split.dev.entries + split.blind.entries)
    }
    template = build_ground_truth_template(split, source_hashes)
    completed_blind = [
        row.model_copy(
            update={
                "technical_usability": "usable",
                "content_families": ["culture_architecture"],
                "setting": "outdoor",
                "lighting": "daylight",
                "people_presence": "absent",
                "people_count_band": "none",
                "completed": True,
            }
        )
        if row.split == "blind"
        else row
        for row in template.records
    ]
    visual_ground_truth = template.model_copy(update={"records": completed_blind})
    director_records = [
        DirectorGroundTruthRecord(
            material_id=row.material_id,
            file=row.file,
            bucket="candidate",
            director_functions=["context"],
            completed=True,
        )
        for row in completed_blind
        if row.split == "blind"
    ]
    bundle = BlindAnnotationBundle(
        source_manifest_sha256=split.source_manifest_sha256,
        blind_membership_sha256=split.blind_membership_sha256,
        brief_confirmation_sha256="b" * 64,
        reviewer="independent-reviewer",
        status="completed",
        visual_ground_truth=visual_ground_truth,
        director_records=director_records,
    )

    validate_blind_annotation_bundle(
        bundle,
        split,
        brief_confirmation_sha256="b" * 64,
    )

    incomplete = bundle.model_copy(
        update={"director_records": director_records[:-1]}
    )
    with pytest.raises(ValueError, match="director labels differ from blind split"):
        validate_blind_annotation_bundle(
            incomplete,
            split,
            brief_confirmation_sha256="b" * 64,
        )


def test_validate_blind_annotation_cli_accepts_hash_bound_bundle(
    tmp_path: Path,
) -> None:
    split = build_evaluation_split(
        manifest(), cv_rows(), source_manifest_sha256="a" * 64
    )
    source_hashes = {
        row.source.relative_path: f"{index + 1:064x}"
        for index, row in enumerate(split.dev.entries + split.blind.entries)
    }
    template = build_ground_truth_template(split, source_hashes)
    visual_ground_truth = template.model_copy(
        update={
            "records": [
                row.model_copy(
                    update={
                        "technical_usability": "usable",
                        "content_families": ["urban"],
                        "setting": "outdoor",
                        "lighting": "daylight",
                        "people_presence": "unknown",
                        "people_count_band": "unknown",
                        "completed": True,
                    }
                )
                if row.split == "blind"
                else row
                for row in template.records
            ]
        }
    )
    brief = BriefConfirmation(
        status="completed",
        draft_sha256="d" * 64,
        normalized_fields=NormalizedBriefFields(
            location="开封",
            travel_type="城市漫游",
            target_duration_seconds=60,
            orientation="landscape",
            style="纪实探索",
            mood="探索",
            rhythm="medium",
        ),
        changed_fields=[],
        confirmed_at="2026-09-02T12:00:00+08:00",
    )
    split_path = tmp_path / "split.json"
    brief_path = tmp_path / "brief.json"
    split_path.write_text(split.model_dump_json(), encoding="utf-8")
    brief_path.write_text(brief.model_dump_json(), encoding="utf-8")
    bundle = BlindAnnotationBundle(
        source_manifest_sha256=split.source_manifest_sha256,
        blind_membership_sha256=split.blind_membership_sha256,
        brief_confirmation_sha256=sha256_file(brief_path),
        reviewer="independent-reviewer",
        status="completed",
        visual_ground_truth=visual_ground_truth,
        director_records=[
            DirectorGroundTruthRecord(
                material_id=row.material_id,
                file=row.file,
                bucket="candidate",
                director_functions=["context"],
                completed=True,
            )
            for row in visual_ground_truth.records
            if row.split == "blind"
        ],
    )
    annotation_path = tmp_path / "blind_annotation.json"
    annotation_path.write_text(bundle.model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "validate-blind-annotation",
            "--split",
            str(split_path),
            "--brief-confirmation",
            str(brief_path),
            "--annotation",
            str(annotation_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "valid" in result.stdout
