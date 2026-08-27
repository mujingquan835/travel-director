"""Field-specific evaluation against frozen human Ground Truth."""

from __future__ import annotations

from typing import Any

from scanner.schema import GroundTruthDataset


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evaluate_detector(
    ground_truth: GroundTruthDataset,
    detector_payload: dict[str, Any],
) -> dict[str, Any]:
    predictions = {item["file"]: item["summary"] for item in detector_payload["items"]}
    missing = [item.file for item in ground_truth.items if item.file not in predictions]
    if missing:
        raise ValueError(f"missing detector result for: {', '.join(missing)}")

    known_presence = [item for item in ground_truth.items if item.people_present is not None]
    tp = fp = tn = fn = 0
    presence_failures: list[dict[str, Any]] = []
    for item in known_presence:
        predicted = bool(predictions[item.file]["people_present"])
        actual = bool(item.people_present)
        if actual and predicted:
            tp += 1
        elif not actual and predicted:
            fp += 1
        elif not actual and not predicted:
            tn += 1
        else:
            fn += 1
        if predicted != actual:
            presence_failures.append({"file": item.file, "expected": actual, "predicted": predicted})

    known_counts = [item for item in ground_truth.items if item.people_count_estimate is not None]
    count_errors = [
        abs(int(predictions[item.file]["people_count_max"]) - int(item.people_count_estimate))
        for item in known_counts
    ]
    undercounts = sum(
        int(predictions[item.file]["people_count_max"]) < int(item.people_count_estimate)
        for item in known_counts
    )

    predicted_labels = 0
    expected_labels = 0
    true_positive_labels = 0
    exact_matches = 0
    object_failures: list[dict[str, Any]] = []
    for item in ground_truth.items:
        expected = set(item.main_objects)
        predicted = set(predictions[item.file]["main_objects"])
        expected_labels += len(expected)
        predicted_labels += len(predicted)
        true_positive_labels += len(expected & predicted)
        exact_matches += expected == predicted
        if expected != predicted:
            object_failures.append(
                {
                    "file": item.file,
                    "expected": sorted(expected),
                    "predicted": sorted(predicted),
                    "false_positive": sorted(predicted - expected),
                    "missed": sorted(expected - predicted),
                }
            )

    evaluated_presence = len(known_presence)
    return {
        "people_present": {
            "evaluated": evaluated_presence,
            "ground_truth_coverage": evaluated_presence / len(ground_truth.items),
            "accuracy": _safe_ratio(tp + tn, evaluated_presence),
            "precision": _safe_ratio(tp, tp + fp),
            "recall": _safe_ratio(tp, tp + fn),
            "f1": _safe_ratio(2 * tp, 2 * tp + fp + fn),
            "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
            "failures": presence_failures,
        },
        "people_count": {
            "evaluated": len(known_counts),
            "ground_truth_coverage": len(known_counts) / len(ground_truth.items),
            "mae": sum(count_errors) / len(count_errors) if count_errors else None,
            "undercount_rate": undercounts / len(known_counts) if known_counts else None,
        },
        "main_objects": {
            "evaluated": len(ground_truth.items),
            "exact_match": exact_matches / len(ground_truth.items),
            "micro_precision": _safe_ratio(true_positive_labels, predicted_labels),
            "micro_recall": _safe_ratio(true_positive_labels, expected_labels),
            "failures": object_failures,
            "note": "Exact string comparison between compact human object labels and COCO detector labels.",
        },
    }
