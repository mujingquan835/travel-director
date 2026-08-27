from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from scanner.cli import app
from scanner.schema import GroundTruthDataset, GroundTruthItem


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
