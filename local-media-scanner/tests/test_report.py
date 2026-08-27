from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scanner.report import publish_run, render_validation_report
from scanner.schema import (
    ContentAnalysis,
    EvaluationSummary,
    FieldEvaluation,
    FieldMetrics,
    FrameRecord,
    GroundTruthDataset,
    GroundTruthItem,
    MotionMetrics,
    QualityMetrics,
    ReliabilityDecision,
    ScannerCard,
    ScannerResult,
    SourceRecord,
    TechnicalMetadata,
)


def _result(filename: str = "<clip>.MOV") -> ScannerResult:
    technical = TechnicalMetadata(
        duration=2.0,
        width=320,
        height=240,
        fps=25,
        orientation="landscape",
        codec="h264",
    )
    return ScannerResult(
        run_id="report-smoke",
        requested_device="mps",
        actual_device="mps",
        model_revisions={"siglip": "pinned"},
        items=[
            ScannerCard(
                file=filename,
                source=SourceRecord(relative_path=filename, size_bytes=10, mtime_ns=20),
                analysis_status="complete",
                technical=technical,
                quality=QualityMetrics(),
                motion=MotionMetrics(),
                content=ContentAnalysis(people_present=False),
                field_status={"content.people_present": "predicted"},
            )
        ],
    )


def _evaluation(filename: str = "<clip>.MOV") -> EvaluationSummary:
    metrics = FieldMetrics(
        total_ground_truth=1,
        evaluated=1,
        abstentions=0,
        scored_coverage=1.0,
        end_to_end_accuracy=0.0,
        accuracy=0.0,
        min_class_support=1,
    )
    return EvaluationSummary(
        run_id="report-smoke",
        ground_truth_items=1,
        overlapping_items=1,
        overlap_files=[filename],
        fields={
            "people_present": FieldEvaluation(
                metrics=metrics,
                reliability=ReliabilityDecision(
                    status="not_reliable_for_v0_1",
                    score_used=0.0,
                    min_class_support=1,
                    reason="fixture mismatch",
                ),
            )
        },
    )


def _truth(filename: str = "<clip>.MOV") -> GroundTruthDataset:
    return GroundTruthDataset(
        items=[
            GroundTruthItem(
                file=filename,
                people_present=True,
                people_count_estimate=1,
                motion_level="unknown",
                exposure_status="unknown",
                quality_label="usable",
                main_objects=["person"],
                annotation_confidence=0.9,
            )
        ]
    )


def test_report_contains_escaped_cards_metrics_and_mismatch_state(tmp_path: Path) -> None:
    output = render_validation_report(
        result=_result(),
        evaluation=_evaluation(),
        environment={"machine": "arm64"},
        output=tmp_path / "validation_report.html",
        ground_truth=_truth(),
    )

    html = output.read_text(encoding="utf-8")
    assert "&lt;clip&gt;.MOV" in html
    assert "field-mismatch" in html
    assert "people_present" in html
    assert "not_reliable_for_v0_1" in html
    assert "data:image" not in html
    assert "<script" not in html


def test_report_rejects_embedded_data_images(tmp_path: Path) -> None:
    result = _result("clip.mov")
    result.items[0].representative_frames = [
        FrameRecord(timestamp=0.5, reasons=["temporal"], thumbnail_relpath="data:image/png;base64,abc")
    ]

    with pytest.raises(ValueError, match="data-image"):
        render_validation_report(result, _evaluation("clip.mov"), {}, tmp_path / "report.html", _truth("clip.mov"))


def test_publish_rewrites_thumbnail_paths_relative_to_output(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    frame = run_dir / "frames" / "clip.mov" / "00.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"jpeg fixture")
    result = _result("clip.mov")
    result.items[0].representative_frames = [
        FrameRecord(timestamp=0.5, reasons=["temporal"], thumbnail_relpath="frames/clip.mov/00.jpg")
    ]
    (run_dir / "scanner_result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "evaluation.json").write_text(_evaluation("clip.mov").model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "environment.json").write_text(json.dumps({"machine": "arm64"}), encoding="utf-8")
    truth_path = tmp_path / "ground_truth.json"
    truth_path.write_text(_truth("clip.mov").model_dump_json(indent=2), encoding="utf-8")
    output_dir = tmp_path / "published"

    result_path, report_path = publish_run(run_dir, truth_path, output_dir)

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    expected = os.path.relpath(frame.resolve(), output_dir.resolve())
    assert payload["items"][0]["representative_frames"][0]["thumbnail_relpath"] == expected
    assert expected in report_path.read_text(encoding="utf-8")
