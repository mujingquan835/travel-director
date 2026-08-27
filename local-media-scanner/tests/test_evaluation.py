from __future__ import annotations

import pytest

from scanner.evaluation import evaluate_detector
from scanner.schema import GroundTruthDataset, GroundTruthItem


def _truth(file: str, present: bool | None, count: int | None, objects: list[str]) -> GroundTruthItem:
    return GroundTruthItem(
        file=file,
        people_present=present,
        people_count_estimate=count,
        motion_level="unknown",
        exposure_status="unknown",
        quality_label="usable",
        main_objects=objects,
        annotation_confidence=0.9,
    )


def test_detector_evaluation_reports_field_specific_metrics_and_coverage() -> None:
    ground_truth = GroundTruthDataset(
        items=[
            _truth("a.mov", True, 2, ["person", "car"]),
            _truth("b.mov", False, 0, ["building"]),
            _truth("unknown.mov", None, None, []),
        ]
    )
    detector_payload = {
        "items": [
            {"file": "a.mov", "summary": {"people_present": True, "people_count_max": 1, "main_objects": ["person", "car"]}},
            {"file": "b.mov", "summary": {"people_present": True, "people_count_max": 1, "main_objects": ["person"]}},
            {"file": "unknown.mov", "summary": {"people_present": False, "people_count_max": 0, "main_objects": []}},
        ]
    }

    result = evaluate_detector(ground_truth, detector_payload)

    assert result["people_present"]["evaluated"] == 2
    assert result["people_present"]["ground_truth_coverage"] == pytest.approx(2 / 3)
    assert result["people_present"]["accuracy"] == 0.5
    assert result["people_present"]["precision"] == 0.5
    assert result["people_present"]["recall"] == 1.0
    assert result["people_count"]["mae"] == 1.0
    assert result["main_objects"]["micro_precision"] == pytest.approx(2 / 3)
    assert result["main_objects"]["micro_recall"] == pytest.approx(2 / 3)


def test_detector_evaluation_rejects_missing_files() -> None:
    ground_truth = GroundTruthDataset(items=[_truth("a.mov", True, 1, ["person"])])

    with pytest.raises(ValueError, match="missing detector result"):
        evaluate_detector(ground_truth, {"items": []})
