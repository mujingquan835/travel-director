"""Null-aware, field-specific evaluation against frozen human Ground Truth."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
import json
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
from PIL import Image

from scanner.detector import Detection
from scanner.fusion import compare_shot_scale_methods
from scanner.schema import (
    AblationSummary,
    EvaluationSummary,
    FieldEvaluation,
    FieldMetrics,
    GroundTruthDataset,
    ReliabilityDecision,
    ScannerCard,
    ScannerResult,
)
from scanner.vision import FramePrediction, LabelScore


def _safe_ratio(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _validate_lengths(expected: Sequence[Any], predicted: Sequence[Any]) -> None:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted must have the same length")


def _f1(tp: int, fp: int, fn: int) -> float | None:
    return _safe_ratio(2 * tp, 2 * tp + fp + fn)


def evaluate_binary(
    expected: Sequence[bool],
    predicted: Sequence[bool | None],
) -> FieldMetrics:
    _validate_lengths(expected, predicted)
    tp = fp = tn = fn = 0
    for actual, guess in zip(expected, predicted, strict=True):
        if guess is None:
            continue
        if actual and guess:
            tp += 1
        elif not actual and guess:
            fp += 1
        elif not actual and not guess:
            tn += 1
        else:
            fn += 1
    evaluated = sum(value is not None for value in predicted)
    total = len(expected)
    correct = tp + tn
    positive_f1 = _f1(tp, fp, fn)
    negative_f1 = _f1(tn, fn, fp)
    macro_values = [value for value in (positive_f1, negative_f1) if value is not None]
    support = {"false": sum(not value for value in expected), "true": sum(expected)}
    return FieldMetrics(
        total_ground_truth=total,
        evaluated=evaluated,
        abstentions=total - evaluated,
        scored_coverage=_safe_ratio(evaluated, total) or 0.0,
        end_to_end_accuracy=_safe_ratio(correct, total),
        accuracy=_safe_ratio(correct, evaluated),
        precision=_safe_ratio(tp, tp + fp),
        recall=_safe_ratio(tp, tp + fn),
        f1=positive_f1,
        macro_f1=sum(macro_values) / len(macro_values) if macro_values else None,
        min_class_support=min(support.values()) if support else 0,
        class_support=support,
        confusion={"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    )


def evaluate_count(
    expected: Sequence[int],
    predicted: Sequence[int | None],
) -> FieldMetrics:
    _validate_lengths(expected, predicted)
    errors = [
        abs(actual - guess)
        for actual, guess in zip(expected, predicted, strict=True)
        if guess is not None
    ]
    evaluated = len(errors)
    total = len(expected)
    exact = sum(error == 0 for error in errors)
    within_one = sum(error <= 1 for error in errors)
    support = {"samples": total}
    return FieldMetrics(
        total_ground_truth=total,
        evaluated=evaluated,
        abstentions=total - evaluated,
        scored_coverage=_safe_ratio(evaluated, total) or 0.0,
        end_to_end_accuracy=_safe_ratio(exact, total),
        exact_accuracy=_safe_ratio(exact, evaluated),
        within_one_accuracy=_safe_ratio(within_one, evaluated),
        mae=sum(errors) / evaluated if evaluated else None,
        min_class_support=total,
        class_support=support,
    )


def evaluate_single_label(
    expected: Sequence[str],
    predicted: Sequence[str | None],
) -> FieldMetrics:
    _validate_lengths(expected, predicted)
    classes = sorted(set(expected))
    confusion: dict[str, dict[str, int]] = {label: {} for label in classes}
    evaluated = correct = 0
    f1_values: list[float] = []
    support = Counter(expected)
    for actual, guess in zip(expected, predicted, strict=True):
        if guess is None:
            continue
        evaluated += 1
        correct += actual == guess
        confusion[actual][guess] = confusion[actual].get(guess, 0) + 1
    for label in classes:
        tp = sum(actual == label and guess == label for actual, guess in zip(expected, predicted, strict=True))
        fp = sum(actual != label and guess == label for actual, guess in zip(expected, predicted, strict=True))
        fn = sum(actual == label and guess not in {label, None} for actual, guess in zip(expected, predicted, strict=True))
        value = _f1(tp, fp, fn)
        if value is not None:
            f1_values.append(value)
    total = len(expected)
    return FieldMetrics(
        total_ground_truth=total,
        evaluated=evaluated,
        abstentions=total - evaluated,
        scored_coverage=_safe_ratio(evaluated, total) or 0.0,
        end_to_end_accuracy=_safe_ratio(correct, total),
        accuracy=_safe_ratio(correct, evaluated),
        macro_f1=sum(f1_values) / len(f1_values) if f1_values else None,
        min_class_support=min(support.values()) if support else 0,
        class_support=dict(sorted(support.items())),
        confusion=confusion,
    )


def evaluate_multilabel(
    expected: Sequence[set[str]],
    predicted: Sequence[set[str] | None],
) -> FieldMetrics:
    _validate_lengths(expected, predicted)
    labels = sorted(set().union(*expected) if expected else set())
    support = {label: sum(label in row for row in expected) for label in labels}
    evaluated = exact = tp_total = fp_total = fn_total = 0
    per_label_f1: list[float] = []
    jaccards: list[float] = []
    for actual, guess in zip(expected, predicted, strict=True):
        if guess is None:
            continue
        evaluated += 1
        exact += actual == guess
        intersection = actual & guess
        union = actual | guess
        jaccards.append(len(intersection) / len(union) if union else 1.0)
        tp_total += len(intersection)
        fp_total += len(guess - actual)
        fn_total += len(actual - guess)
    for label in labels:
        tp = sum(label in actual and guess is not None and label in guess for actual, guess in zip(expected, predicted, strict=True))
        fp = sum(label not in actual and guess is not None and label in guess for actual, guess in zip(expected, predicted, strict=True))
        fn = sum(label in actual and guess is not None and label not in guess for actual, guess in zip(expected, predicted, strict=True))
        value = _f1(tp, fp, fn)
        if value is not None:
            per_label_f1.append(value)
    total = len(expected)
    return FieldMetrics(
        total_ground_truth=total,
        evaluated=evaluated,
        abstentions=total - evaluated,
        scored_coverage=_safe_ratio(evaluated, total) or 0.0,
        end_to_end_accuracy=_safe_ratio(exact, total),
        exact_accuracy=_safe_ratio(exact, evaluated),
        macro_f1=sum(per_label_f1) / len(per_label_f1) if per_label_f1 else None,
        micro_precision=_safe_ratio(tp_total, tp_total + fp_total),
        micro_recall=_safe_ratio(tp_total, tp_total + fn_total),
        micro_f1=_safe_ratio(2 * tp_total, 2 * tp_total + fp_total + fn_total),
        mean_jaccard=sum(jaccards) / len(jaccards) if jaccards else None,
        min_class_support=min(support.values()) if support else 0,
        class_support=support,
    )


def _average_ranks(values: Sequence[float]) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    order = np.argsort(array, kind="stable")
    ranks = np.empty(len(values), dtype=float)
    offset = 0
    while offset < len(order):
        end = offset + 1
        while end < len(order) and array[order[end]] == array[order[offset]]:
            end += 1
        ranks[order[offset:end]] = (offset + end - 1) / 2.0
        offset = end
    return ranks


def evaluate_ordered_quality(
    expected: Sequence[str],
    predicted_scores: Sequence[float | None],
) -> FieldMetrics:
    _validate_lengths(expected, predicted_scores)
    ranks = {"unusable": 0.0, "marginal": 1.0, "usable": 2.0}
    scored = [(ranks[actual], score) for actual, score in zip(expected, predicted_scores, strict=True) if score is not None]
    correlation = None
    if len(scored) >= 2:
        actual_rank = _average_ranks([row[0] for row in scored])
        predicted_rank = _average_ranks([float(row[1]) for row in scored])
        if np.std(actual_rank) > 0 and np.std(predicted_rank) > 0:
            correlation = float(np.corrcoef(actual_rank, predicted_rank)[0, 1])
    threshold_labels = [
        None if score is None else "unusable" if score < 1 / 3 else "marginal" if score < 2 / 3 else "usable"
        for score in predicted_scores
    ]
    metrics = evaluate_single_label(expected, threshold_labels)
    return metrics.model_copy(update={"rank_correlation": correlation})


def decide_reliability(
    metrics: FieldMetrics,
    min_class_support: int = 5,
    systematic_failure: bool = False,
) -> ReliabilityDecision:
    score = next(
        (
            value
            for value in (
                metrics.macro_f1,
                metrics.f1,
                metrics.accuracy,
                metrics.exact_accuracy,
                metrics.micro_f1,
            )
            if value is not None
        ),
        None,
    )
    if metrics.total_ground_truth == 0 or metrics.min_class_support < min_class_support:
        return ReliabilityDecision(
            status="insufficient_coverage",
            score_used=score,
            min_class_support=metrics.min_class_support,
            systematic_failure=systematic_failure,
            reason=f"minimum class support is below {min_class_support}",
        )
    if score is not None and score >= 0.80 and not systematic_failure:
        status = "reliable"
        reason = "score meets the V0.1 gate without a documented systematic failure"
    elif systematic_failure or (score is not None and score >= 0.65) or metrics.scored_coverage < 1.0:
        status = "candidate"
        reason = "coverage, score, or a systematic failure blocks reliable status"
    else:
        status = "not_reliable_for_v0_1"
        reason = "score is below the V0.1 retention threshold"
    return ReliabilityDecision(
        status=status,
        score_used=score,
        min_class_support=metrics.min_class_support,
        systematic_failure=systematic_failure,
        reason=reason,
    )


def _predicted(card: ScannerCard, key: str, value: Any) -> Any | None:
    if card.field_status.get(key) in {"abstained", "unavailable"}:
        return None
    if value in {"unknown", None}:
        return None
    return value


def evaluate_run(ground_truth: GroundTruthDataset, result: ScannerResult) -> EvaluationSummary:
    predictions = {item.file: item for item in result.items}
    overlap = [item for item in ground_truth.items if item.file in predictions]
    fields: dict[str, FieldMetrics] = {}

    known = [item for item in overlap if item.people_present is not None]
    fields["people_present"] = evaluate_binary(
        [bool(item.people_present) for item in known],
        [_predicted(predictions[item.file], "content.people_present", predictions[item.file].content.people_present) for item in known],
    )
    known = [item for item in overlap if item.people_count_estimate is not None]
    fields["people_count_estimate"] = evaluate_count(
        [int(item.people_count_estimate) for item in known],
        [_predicted(predictions[item.file], "content.people_count_estimate", predictions[item.file].content.people_count_estimate) for item in known],
    )
    known = [item for item in overlap if item.people_present is True and item.people_type]
    fields["people_type"] = evaluate_multilabel(
        [set(item.people_type) for item in known],
        [
            None
            if _predicted(predictions[item.file], "content.people_type", predictions[item.file].content.people_type) is None
            else set(predictions[item.file].content.people_type)
            for item in known
        ],
    )
    for name, truth_attr, card_key, value_getter in (
        ("scene_type", "scene_type", "content.scene_type", lambda card: card.content.scene_type),
        ("shot_scale", "shot_scale", "shot_scale", lambda card: card.shot_scale),
        ("simple_action", "simple_action", "content.simple_action", lambda card: card.content.simple_action),
    ):
        known = [item for item in overlap if getattr(item, truth_attr) is not None]
        fields[name] = evaluate_single_label(
            [str(getattr(item, truth_attr)) for item in known],
            [_predicted(predictions[item.file], card_key, value_getter(predictions[item.file])) for item in known],
        )
    for name, truth_attr, value_getter in (
        ("motion_level", "motion_level", lambda card: card.motion.motion_level),
        ("exposure_status", "exposure_status", lambda card: card.quality.exposure_status),
    ):
        known = [item for item in overlap if getattr(item, truth_attr) != "unknown"]
        fields[name] = evaluate_single_label(
            [str(getattr(item, truth_attr)) for item in known],
            [None if value_getter(predictions[item.file]) == "unknown" else value_getter(predictions[item.file]) for item in known],
        )
    fields["quality"] = evaluate_ordered_quality(
        [item.quality_label for item in overlap],
        [predictions[item.file].quality.quality_score for item in overlap],
    )
    for name, truth_getter, card_key, value_getter in (
        ("main_objects", lambda item: set(item.main_objects), "content.main_objects", lambda card: set(card.content.main_objects)),
        ("material_role_candidates", lambda item: set(item.material_role_candidates), "material_role_candidates", lambda card: set(card.material_role_candidates)),
    ):
        fields[name] = evaluate_multilabel(
            [truth_getter(item) for item in overlap],
            [
                None
                if predictions[item.file].field_status.get(card_key) in {"abstained", "unavailable"}
                else value_getter(predictions[item.file])
                for item in overlap
            ],
        )
    return EvaluationSummary(
        run_id=result.run_id,
        ground_truth_items=len(ground_truth.items),
        overlapping_items=len(overlap),
        overlap_files=[item.file for item in overlap],
        fields={
            name: FieldEvaluation(metrics=metrics, reliability=decide_reliability(metrics))
            for name, metrics in fields.items()
        },
    )


def _read_evidence(evidence_dir: Path, file: str) -> dict[str, Any] | None:
    path = evidence_dir / f"{file.replace('/', '_')}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_ablation(
    ground_truth: GroundTruthDataset,
    evidence_dir: Path,
    fields: Sequence[str],
) -> AblationSummary:
    allowed = {"people_count_estimate", "shot_scale"}
    unsupported = sorted(set(fields) - allowed)
    if unsupported:
        raise ValueError(f"unsupported ablation fields: {', '.join(unsupported)}")
    evidence_files = {
        payload["file"]
        for path in evidence_dir.glob("*.json")
        if (payload := json.loads(path.read_text(encoding="utf-8"))).get("file")
    }
    output: dict[str, dict[str, FieldEvaluation]] = {}
    if "people_count_estimate" in fields:
        known = [
            item
            for item in ground_truth.items
            if item.file in evidence_files and item.people_count_estimate is not None
        ]
        predictions: dict[str, list[int | None]] = {
            "max": [],
            "median": [],
            "high_confidence": [],
        }
        for item in known:
            evidence = _read_evidence(evidence_dir, item.file)
            if evidence is None:
                for values in predictions.values():
                    values.append(None)
                continue
            detector = evidence.get("detector", [])
            counts = [sum(row.get("label") == "person" for row in frame) for frame in detector]
            confident = [
                sum(row.get("label") == "person" and float(row.get("score", 0.0)) >= 0.75 for row in frame)
                for frame in detector
            ]
            predictions["max"].append(max(counts, default=0))
            predictions["median"].append(int(round(median(counts))) if counts else 0)
            predictions["high_confidence"].append(max(confident, default=0))
        expected = [int(item.people_count_estimate) for item in known]
        output["people_count_estimate"] = {
            method: FieldEvaluation(
                metrics=(metrics := evaluate_count(expected, values)),
                reliability=decide_reliability(metrics),
            )
            for method, values in predictions.items()
        }
    if "shot_scale" in fields:
        known = [
            item
            for item in ground_truth.items
            if item.file in evidence_files and item.shot_scale is not None
        ]
        predictions: dict[str, list[str | None]] = {"siglip": [], "geometry": [], "fusion": []}
        for item in known:
            evidence = _read_evidence(evidence_dir, item.file)
            if evidence is None:
                for values in predictions.values():
                    values.append(None)
                continue
            detector = [
                [Detection(row["label"], float(row["score"]), tuple(row["box_xyxy"])) for row in frame]
                for frame in evidence.get("detector", [])
            ]
            vision = [
                FramePrediction(
                    row["field"],
                    [LabelScore(score["label"], float(score["score"])) for score in row["scores"]],
                    float(row["top_margin"]),
                    row["source"],
                )
                for row in evidence.get("vision", {}).get("shot_scale", [])
            ]
            image_sizes: list[tuple[int, int]] = []
            for frame in evidence.get("representative_frames", []):
                with Image.open(evidence_dir.parent / frame["thumbnail_relpath"]) as image:
                    image_sizes.append((image.height, image.width))
            methods = compare_shot_scale_methods(vision, detector, image_sizes)
            for method, values in predictions.items():
                values.append(methods[method].value)
        expected = [str(item.shot_scale) for item in known]
        output["shot_scale"] = {
            method: FieldEvaluation(
                metrics=(metrics := evaluate_single_label(expected, values)),
                reliability=decide_reliability(metrics),
            )
            for method, values in predictions.items()
        }
    return AblationSummary(run_id=evidence_dir.parent.name, fields=output)


def evaluate_detector(
    ground_truth: GroundTruthDataset,
    detector_payload: dict[str, Any],
) -> dict[str, Any]:
    predictions = {item["file"]: item["summary"] for item in detector_payload["items"]}
    missing = [item.file for item in ground_truth.items if item.file not in predictions]
    if missing:
        raise ValueError(f"missing detector result for: {', '.join(missing)}")
    known_presence = [item for item in ground_truth.items if item.people_present is not None]
    presence = evaluate_binary(
        [bool(item.people_present) for item in known_presence],
        [bool(predictions[item.file]["people_present"]) for item in known_presence],
    )
    known_counts = [item for item in ground_truth.items if item.people_count_estimate is not None]
    counts = evaluate_count(
        [int(item.people_count_estimate) for item in known_counts],
        [int(predictions[item.file]["people_count_max"]) for item in known_counts],
    )
    objects = evaluate_multilabel(
        [set(item.main_objects) for item in ground_truth.items],
        [set(predictions[item.file]["main_objects"]) for item in ground_truth.items],
    )
    return {
        "people_present": {
            "evaluated": presence.evaluated,
            "ground_truth_coverage": len(known_presence) / len(ground_truth.items),
            "accuracy": presence.accuracy,
            "precision": presence.precision,
            "recall": presence.recall,
            "f1": presence.f1,
            "confusion": presence.confusion,
        },
        "people_count": {
            "evaluated": counts.evaluated,
            "ground_truth_coverage": len(known_counts) / len(ground_truth.items),
            "mae": counts.mae,
        },
        "main_objects": {
            "evaluated": objects.evaluated,
            "exact_match": objects.exact_accuracy,
            "micro_precision": objects.micro_precision,
            "micro_recall": objects.micro_recall,
        },
    }
