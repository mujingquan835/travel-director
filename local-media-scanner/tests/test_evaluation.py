from __future__ import annotations

import pytest

from scanner.evaluation import (
    decide_reliability,
    evaluate_ablation,
    evaluate_binary,
    evaluate_count,
    evaluate_detector,
    evaluate_multilabel,
    evaluate_ordered_quality,
    evaluate_run,
)
from scanner.schema import (
    ContentAnalysis,
    GroundTruthDataset,
    GroundTruthItem,
    ManifestEntry,
    MotionMetrics,
    QualityMetrics,
    ScannerCard,
    ScannerResult,
    SourceRecord,
    TechnicalMetadata,
)


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


def test_binary_metrics_match_hand_calculation_and_count_abstentions() -> None:
    metrics = evaluate_binary(
        [True, True, False, False, True],
        [True, False, True, False, None],
    )

    assert metrics.precision == pytest.approx(0.5)
    assert metrics.recall == pytest.approx(0.5)
    assert metrics.f1 == pytest.approx(0.5)
    assert metrics.accuracy == pytest.approx(0.5)
    assert metrics.scored_coverage == pytest.approx(0.8)
    assert metrics.end_to_end_accuracy == pytest.approx(0.4)


def test_count_metrics_include_exact_plus_minus_one_and_mae() -> None:
    metrics = evaluate_count([1, 2, 4], [1, 3, 2])

    assert metrics.exact_accuracy == pytest.approx(1 / 3)
    assert metrics.within_one_accuracy == pytest.approx(2 / 3)
    assert metrics.mae == pytest.approx(1.0)


def test_multilabel_reports_micro_macro_jaccard_and_coverage() -> None:
    metrics = evaluate_multilabel(
        [{"person", "car"}, {"building"}, {"food"}],
        [{"person", "car"}, {"person"}, None],
    )

    assert metrics.scored_coverage == pytest.approx(2 / 3)
    assert metrics.micro_precision == pytest.approx(2 / 3)
    assert metrics.micro_recall == pytest.approx(2 / 3)
    assert metrics.mean_jaccard == pytest.approx(0.5)


def test_insufficient_support_and_systematic_failure_gate_reliability() -> None:
    insufficient = evaluate_binary([True, True, False], [True, True, False])
    assert decide_reliability(insufficient).status == "insufficient_coverage"

    supported = evaluate_binary(
        [True] * 5 + [False] * 5,
        [True] * 5 + [False] * 5,
    )
    assert decide_reliability(supported).status == "reliable"
    assert decide_reliability(supported, systematic_failure=True).status == "candidate"


def test_ordered_quality_reports_rank_and_threshold_accuracy() -> None:
    metrics = evaluate_ordered_quality(
        ["unusable", "marginal", "usable"],
        [0.1, 0.5, 0.9],
    )

    assert metrics.rank_correlation == pytest.approx(1.0)
    assert metrics.accuracy == 1.0


def test_ablation_is_limited_and_missing_evidence_abstains(tmp_path) -> None:
    truth = GroundTruthDataset(items=[_truth("a.mov", True, 2, ["person"])])

    summary = evaluate_ablation(truth, tmp_path, ["people_count_estimate"])

    assert set(summary.fields["people_count_estimate"]) == {"max", "median", "high_confidence"}
    assert all(
        method.metrics.scored_coverage == 0.0
        for method in summary.fields["people_count_estimate"].values()
    )
    with pytest.raises(ValueError, match="unsupported ablation fields"):
        evaluate_ablation(truth, tmp_path, ["scene_type"])


def test_run_evaluation_uses_only_overlap_and_has_no_overall_accuracy() -> None:
    metadata = TechnicalMetadata(
        duration=1.0,
        width=320,
        height=240,
        fps=25,
        orientation="landscape",
        codec="h264",
    )
    source = SourceRecord(relative_path="a.mov", size_bytes=1, mtime_ns=1)
    entry = ManifestEntry(file="a.mov", source=source, technical=metadata)
    result = ScannerResult(
        run_id="smoke",
        requested_device="mps",
        actual_device="mps",
        items=[
            ScannerCard(
                file=entry.file,
                source=entry.source,
                analysis_status="complete",
                technical=entry.technical,
                quality=QualityMetrics(),
                motion=MotionMetrics(),
                content=ContentAnalysis(people_present=True, people_count_estimate=1),
                field_status={
                    "content.people_present": "candidate",
                    "content.people_count_estimate": "candidate",
                },
            )
        ],
    )
    truth = GroundTruthDataset(
        items=[
            _truth("a.mov", True, 1, ["person"]),
            _truth("not-in-run.mov", False, 0, []),
        ]
    )

    summary = evaluate_run(truth, result)

    assert summary.overlapping_items == 1
    assert summary.fields["people_present"].metrics.end_to_end_accuracy == 1.0
    assert all(field.reliability.status == "insufficient_coverage" for field in summary.fields.values())
    assert "overall_accuracy" not in summary.model_dump()
