from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from typer.testing import CliRunner

from scanner.cli import app
from scanner.schema import (
    GroundTruthDataset,
    GroundTruthItem,
    ManifestEntry,
    PeopleValidationDataset,
    PeopleValidationItem,
    SourceRecord,
    TechnicalMetadata,
    TestManifest as ScannerManifest,
)


def test_ground_truth_accepts_abstention_and_reject_quality() -> None:
    item = GroundTruthItem(
        file="dark.mov",
        people_present=None,
        people_count_estimate=None,
        people_type=[],
        scene_type=None,
        shot_scale=None,
        motion_level="unknown",
        exposure_status="underexposed",
        quality_label="unusable",
        main_objects=[],
        simple_action=None,
        material_role_candidates=[],
        annotation_confidence=0.35,
        notes="Too dark to label content reliably.",
    )

    assert GroundTruthItem.model_validate(item.model_dump()).quality_label == "unusable"


def test_ground_truth_dataset_rejects_duplicate_files() -> None:
    item = GroundTruthItem(
        file="a.mov",
        people_present=False,
        motion_level="low",
        exposure_status="normal",
        quality_label="usable",
        annotation_confidence=0.9,
    )

    try:
        GroundTruthDataset(items=[item, item])
    except ValueError as error:
        assert "duplicate" in str(error).lower()
    else:
        raise AssertionError("duplicate Ground Truth files must be rejected")


def test_validate_ground_truth_cli_reports_count(tmp_path: Path) -> None:
    path = tmp_path / "ground_truth.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "items": [
                    {
                        "file": "a.mov",
                        "people_present": False,
                        "motion_level": "low",
                        "exposure_status": "normal",
                        "quality_label": "usable",
                        "annotation_confidence": 0.9,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["validate-ground-truth", "--input", str(path)])

    assert result.exit_code == 0
    assert "1 item" in result.stdout


def test_people_validation_enforces_presence_count_consistency() -> None:
    valid = PeopleValidationItem(
        file="crowd.mov",
        people_present=True,
        people_count_band="crowd",
        visibility="mixed",
        annotation_confidence=0.9,
    )
    dataset = PeopleValidationDataset(manifest_sha256="a" * 64, items=[valid])

    assert dataset.items[0].people_count_band == "crowd"
    for payload in (
        {
            "file": "bad-none.mov",
            "people_present": False,
            "people_count_band": "few",
            "visibility": "clear",
            "annotation_confidence": 1.0,
        },
        {
            "file": "bad-abstain.mov",
            "people_present": None,
            "people_count_band": None,
            "visibility": "partial",
            "annotation_confidence": 0.3,
        },
    ):
        try:
            PeopleValidationItem.model_validate(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("inconsistent people validation labels must be rejected")


def test_validate_people_ground_truth_requires_exact_frozen_manifest(tmp_path: Path) -> None:
    manifest = ScannerManifest(
        input_root="/videos",
        entries=[
            ManifestEntry(
                file="a.mov",
                source=SourceRecord(relative_path="a.mov", size_bytes=1, mtime_ns=1),
                technical=TechnicalMetadata(
                    duration=1,
                    width=320,
                    height=240,
                    fps=30,
                    orientation="landscape",
                    codec="h264",
                ),
            )
        ],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    labels = PeopleValidationDataset(
        manifest_sha256=sha256(manifest_path.read_bytes()).hexdigest(),
        items=[
            PeopleValidationItem(
                file="a.mov",
                people_present=False,
                people_count_band="none",
                visibility="clear",
                annotation_confidence=1.0,
            )
        ],
    )
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(labels.model_dump_json(indent=2), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "validate-people-ground-truth",
            "--manifest",
            str(manifest_path),
            "--input",
            str(labels_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "1 people validation items" in result.stdout
