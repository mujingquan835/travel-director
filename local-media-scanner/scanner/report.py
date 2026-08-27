"""Static, local-only Scanner validation report rendering."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scanner.schema import (
    EvaluationSummary,
    GroundTruthDataset,
    GroundTruthItem,
    ScannerCard,
    ScannerResult,
)


FIELD_SPECS = (
    ("people_present", "People present", "content.people_present"),
    ("people_count_estimate", "People count", "content.people_count_estimate"),
    ("people_type", "People type", "content.people_type"),
    ("scene_type", "Scene", "content.scene_type"),
    ("shot_scale", "Shot scale", "shot_scale"),
    ("motion_level", "Motion", "motion.motion_level"),
    ("exposure_status", "Exposure", "quality.exposure_status"),
    ("quality", "Quality", "quality.quality_score"),
    ("main_objects", "Main objects", "content.main_objects"),
    ("simple_action", "Action", "content.simple_action"),
    ("material_role_candidates", "Material roles", "material_role_candidates"),
)


def _template_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _card_value(card: ScannerCard, field: str) -> Any:
    values = {
        "people_present": card.content.people_present,
        "people_count_estimate": card.content.people_count_estimate,
        "people_type": card.content.people_type,
        "scene_type": card.content.scene_type,
        "shot_scale": card.shot_scale,
        "motion_level": card.motion.motion_level,
        "exposure_status": card.quality.exposure_status,
        "quality": card.quality.quality_score,
        "main_objects": card.content.main_objects,
        "simple_action": card.content.simple_action,
        "material_role_candidates": card.material_role_candidates,
    }
    return values[field]


def _truth_value(item: GroundTruthItem | None, field: str) -> Any:
    if item is None:
        return None
    if field == "quality":
        return item.quality_label
    return getattr(item, field)


def _quality_label(score: float | None) -> str | None:
    if score is None:
        return None
    if score < 1 / 3:
        return "unusable"
    if score < 2 / 3:
        return "marginal"
    return "usable"


def _display(value: Any) -> str:
    if value is None or value == "unknown":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "[]"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _normal(value: Any) -> Any:
    if isinstance(value, list):
        return sorted(value)
    return value


def _comparison_state(field: str, predicted: Any, truth: Any, status: str | None) -> str:
    if truth is None or truth == "unknown":
        return "not-evaluated"
    if field == "people_type" and truth == []:
        return "not-evaluated"
    if status in {"abstained", "unavailable"} or predicted is None or predicted == "unknown":
        return "abstained"
    comparable = _quality_label(predicted) if field == "quality" else predicted
    return "match" if _normal(comparable) == _normal(truth) else "mismatch"


def _field_rows(
    card: ScannerCard,
    truth: GroundTruthItem | None,
    evaluation: EvaluationSummary,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, label, status_key in FIELD_SPECS:
        predicted = _card_value(card, field)
        expected = _truth_value(truth, field)
        status = card.field_status.get(status_key)
        confidence = card.confidence.get(status_key)
        field_evaluation = evaluation.fields.get(field)
        rows.append(
            {
                "field": field,
                "label": label,
                "predicted": _display(predicted),
                "truth": _display(expected),
                "status": status or ("abstained" if predicted is None or predicted == "unknown" else "predicted"),
                "state": _comparison_state(field, predicted, expected, status),
                "confidence": None if confidence is None else confidence.score,
                "confidence_source": None if confidence is None else confidence.source,
                "reliability": None if field_evaluation is None else field_evaluation.reliability.status,
            }
        )
    return rows


def _timing_summary(result: ScannerResult) -> list[dict[str, Any]]:
    stages = ("frame_scan", "cv", "detector", "vision_model", "fusion", "total")
    output: list[dict[str, Any]] = []
    for stage in stages:
        values = [getattr(card.timings_ms, stage) for card in result.items]
        known = [value for value in values if value is not None]
        output.append({"stage": stage, "total_ms": sum(known), "measured": len(known)})
    return output


def render_validation_report(
    result: ScannerResult,
    evaluation: EvaluationSummary,
    environment: Mapping[str, Any],
    output: Path,
    ground_truth: GroundTruthDataset | None = None,
) -> Path:
    """Render one self-contained HTML shell that references only local relative images."""

    if any(frame.thumbnail_relpath.startswith("data:") for card in result.items for frame in card.representative_frames):
        raise ValueError("embedded data-image thumbnails are not allowed")
    truth = {} if ground_truth is None else {item.file: item for item in ground_truth.items}
    cards = [
        {
            "card": card,
            "fields": _field_rows(card, truth.get(card.file), evaluation),
        }
        for card in result.items
    ]
    template = _template_environment().get_template("validation_report.html.j2")
    html = template.render(
        result=result,
        evaluation=evaluation,
        environment=dict(environment),
        cards=cards,
        timings=_timing_summary(result),
        error_count=sum(len(card.errors) for card in result.items),
        failed_count=sum(card.analysis_status == "failed" for card in result.items),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def rebase_thumbnail_paths(
    result: ScannerResult,
    source_dir: Path,
    output_dir: Path,
) -> ScannerResult:
    """Return a copy whose thumbnail paths resolve from the requested output directory."""

    rebased = result.model_copy(deep=True)
    for card in rebased.items:
        for frame in card.representative_frames:
            source = (source_dir / frame.thumbnail_relpath).resolve()
            frame.thumbnail_relpath = os.path.relpath(source, output_dir.resolve())
    return rebased


def publish_run(
    run_dir: Path,
    ground_truth: Path,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Publish small JSON/HTML artifacts while leaving private frames in their run directory."""

    result = ScannerResult.model_validate_json((run_dir / "scanner_result.json").read_text(encoding="utf-8"))
    evaluation = EvaluationSummary.model_validate_json((run_dir / "evaluation.json").read_text(encoding="utf-8"))
    truth = GroundTruthDataset.model_validate_json(ground_truth.read_text(encoding="utf-8"))
    environment = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    published = rebase_thumbnail_paths(result, run_dir, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "scanner_result.json"
    report_path = output_dir / "validation_report.html"
    result_path.write_text(published.model_dump_json(indent=2), encoding="utf-8")
    render_validation_report(published, evaluation, environment, report_path, truth)
    return result_path, report_path
