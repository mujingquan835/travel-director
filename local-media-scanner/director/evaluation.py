"""Frozen evaluation packs and manual-label contracts for the V0.2 workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import ConfigDict, Field, model_validator

from director.visual_schema import (
    BriefConfirmation,
    Bucket,
    ClipObservation,
    ClipObservationBatch,
    DirectorFunction,
    IntentDecisionBatch,
    MaterialRef,
    RawCreativeBrief,
    VisualStrictModel,
    derive_material_id,
)
from scanner.schema import TestManifest
from scanner.selection import propose_stratified_set


ContentFamily = Literal[
    "urban",
    "nature",
    "culture_architecture",
    "food",
    "transport",
    "lodging",
    "attraction_activity",
    "performance_event",
    "people",
    "detail",
    "other",
    "unknown",
]

CONTENT_FAMILY_EVALUATION_LABELS: tuple[str, ...] = (
    "urban",
    "nature",
    "culture_architecture",
    "food",
    "transport",
    "lodging",
    "attraction_activity",
    "performance_event",
    "people",
    "detail",
    "other",
)
ENUM_VISUAL_EVALUATION_FIELDS: tuple[str, ...] = (
    "technical_usability",
    "setting",
    "lighting",
    "people_presence",
    "people_count_band",
)
BUCKET_EVALUATION_LABELS: tuple[Bucket, ...] = (
    "core",
    "candidate",
    "redundant",
    "reject_suggestion",
    "review_required",
)
DIRECTOR_FUNCTION_EVALUATION_LABELS: tuple[DirectorFunction, ...] = (
    "opening",
    "context",
    "progression",
    "emotion",
    "contrast",
    "breathing",
    "climax",
    "ending",
)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def membership_hash(manifest: TestManifest) -> str:
    paths = sorted(row.source.relative_path for row in manifest.entries)
    return hashlib.sha256(_canonical_bytes(paths)).hexdigest()


def _subset_manifest(inventory: TestManifest, paths: set[str]) -> TestManifest:
    entries = [
        row for row in inventory.entries if row.source.relative_path in paths
    ]
    return TestManifest(
        input_root=inventory.input_root,
        entries=entries,
        total_duration_seconds=sum(row.technical.duration for row in entries),
        total_size_bytes=sum(row.source.size_bytes for row in entries),
    )


class DirectorVisualSplit(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dev_seed: int
    blind_seed: int
    dev_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    blind_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reserve_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dev: TestManifest
    blind: TestManifest
    reserve: TestManifest

    @model_validator(mode="after")
    def partitions_are_exact_and_disjoint(self) -> "DirectorVisualSplit":
        groups = [
            {row.source.relative_path for row in manifest.entries}
            for manifest in (self.dev, self.blind, self.reserve)
        ]
        if [len(group) for group in groups] != [12, 12, 6]:
            raise ValueError("evaluation split must contain exactly 12/12/6 files")
        if not (
            groups[0].isdisjoint(groups[1])
            and groups[0].isdisjoint(groups[2])
            and groups[1].isdisjoint(groups[2])
        ):
            raise ValueError("evaluation split memberships must be disjoint")
        expected_hashes = (
            self.dev_membership_sha256,
            self.blind_membership_sha256,
            self.reserve_membership_sha256,
        )
        actual_hashes = tuple(
            membership_hash(manifest)
            for manifest in (self.dev, self.blind, self.reserve)
        )
        if expected_hashes != actual_hashes:
            raise ValueError("evaluation membership hash mismatch")
        return self


def build_evaluation_split(
    inventory: TestManifest,
    cv_rows: list[dict[str, Any]],
    *,
    source_manifest_sha256: str,
    dev_seed: int = 20260831,
    blind_seed: int = 20260901,
) -> DirectorVisualSplit:
    """Create deterministic, non-overlapping development/blind/reserve sets."""

    if len(inventory.entries) != 30:
        raise ValueError("director visual inventory must contain exactly 30 files")
    dev = propose_stratified_set(inventory, cv_rows, count=12, seed=dev_seed)
    dev_paths = {row.source.relative_path for row in dev.entries}
    eligible_paths = {
        row.source.relative_path
        for row in inventory.entries
        if row.source.relative_path not in dev_paths
    }
    eligible = _subset_manifest(inventory, eligible_paths)
    eligible_cv = [row for row in cv_rows if row.get("file") in eligible_paths]
    blind = propose_stratified_set(
        eligible, eligible_cv, count=12, seed=blind_seed
    )
    used = dev_paths | {row.source.relative_path for row in blind.entries}
    reserve = _subset_manifest(
        inventory,
        {
            row.source.relative_path
            for row in inventory.entries
            if row.source.relative_path not in used
        },
    )
    return DirectorVisualSplit(
        source_manifest_sha256=source_manifest_sha256,
        dev_seed=dev_seed,
        blind_seed=blind_seed,
        dev_membership_sha256=membership_hash(dev),
        blind_membership_sha256=membership_hash(blind),
        reserve_membership_sha256=membership_hash(reserve),
        dev=dev,
        blind=blind,
        reserve=reserve,
    )


class GroundTruthRecord(VisualStrictModel):
    material_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file: str = Field(min_length=1)
    split: Literal["dev", "blind"]
    frame_paths: list[str] = Field(default_factory=list)
    technical_usability: Literal[
        "unreviewed", "usable", "unusable", "review_required"
    ] = "unreviewed"
    content_families: list[ContentFamily] = Field(default_factory=lambda: ["unknown"])
    setting: Literal["indoor", "outdoor", "mixed", "unknown"] = "unknown"
    lighting: Literal["daylight", "night", "artificial", "mixed", "unknown"] = (
        "unknown"
    )
    people_presence: Literal["present", "absent", "unknown"] = "unknown"
    people_count_band: Literal["none", "single", "few", "crowd", "unknown"] = (
        "unknown"
    )
    subject_candidates: list[str] = Field(default_factory=list)
    activity_candidates: list[str] = Field(default_factory=list)
    reviewer_note: str = ""
    completed: bool = False

    @model_validator(mode="after")
    def identity_and_people_fields_are_consistent(self) -> "GroundTruthRecord":
        if self.material_id != derive_material_id(self.source_sha256):
            raise ValueError("ground truth material_id does not match source_sha256")
        if len(self.content_families) != len(set(self.content_families)):
            raise ValueError("ground truth content families must be unique")
        if "unknown" in self.content_families and len(self.content_families) > 1:
            raise ValueError("unknown content family cannot accompany concrete labels")
        if self.people_presence == "absent" and self.people_count_band not in {
            "none",
            "unknown",
        }:
            raise ValueError("absent people cannot have a positive count band")
        if self.people_presence == "present" and self.people_count_band == "none":
            raise ValueError("present people cannot have none count band")
        if self.completed and self.technical_usability == "unreviewed":
            raise ValueError("completed ground truth must review technical usability")
        return self


class DirectorVisualGroundTruth(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dev_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    blind_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    records: list[GroundTruthRecord]


class DirectorGroundTruthRecord(VisualStrictModel):
    material_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    file: str = Field(min_length=1)
    bucket: Bucket
    director_functions: list[DirectorFunction] = Field(default_factory=list)
    reviewer_note: str = ""
    completed: bool = False

    @model_validator(mode="after")
    def director_functions_are_unique(self) -> "DirectorGroundTruthRecord":
        if len(self.director_functions) != len(set(self.director_functions)):
            raise ValueError("director functions must be unique")
        return self


class BlindAnnotationBundle(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    split: Literal["blind"] = "blind"
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    blind_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    brief_confirmation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1)
    status: Literal["completed"] = "completed"
    visual_ground_truth: DirectorVisualGroundTruth
    director_records: list[DirectorGroundTruthRecord]


def build_ground_truth_template(
    split: DirectorVisualSplit,
    source_hashes: dict[str, str],
    frame_paths: dict[str, list[str]] | None = None,
) -> DirectorVisualGroundTruth:
    frames = frame_paths or {}
    records: list[GroundTruthRecord] = []
    for split_name, manifest in (("dev", split.dev), ("blind", split.blind)):
        for entry in manifest.entries:
            relative_path = entry.source.relative_path
            try:
                source_sha256 = source_hashes[relative_path]
            except KeyError as exc:
                raise ValueError(f"missing source SHA-256 for {relative_path}") from exc
            records.append(
                GroundTruthRecord(
                    material_id=derive_material_id(source_sha256),
                    source_sha256=source_sha256,
                    file=relative_path,
                    split=split_name,
                    frame_paths=frames.get(relative_path, []),
                )
            )
    return DirectorVisualGroundTruth(
        source_manifest_sha256=split.source_manifest_sha256,
        dev_membership_sha256=split.dev_membership_sha256,
        blind_membership_sha256=split.blind_membership_sha256,
        records=records,
    )


def validate_ground_truth(
    ground_truth: DirectorVisualGroundTruth,
    split: DirectorVisualSplit,
    *,
    require_completed: bool,
) -> None:
    expected = {
        (split_name, entry.source.relative_path)
        for split_name, manifest in (("dev", split.dev), ("blind", split.blind))
        for entry in manifest.entries
    }
    observed = [(row.split, row.file) for row in ground_truth.records]
    if len(observed) != len(set(observed)):
        raise ValueError("duplicate material in ground truth")
    if set(observed) != expected:
        raise ValueError("ground truth membership differs from frozen split")
    if ground_truth.source_manifest_sha256 != split.source_manifest_sha256:
        raise ValueError("ground truth source manifest hash mismatch")
    if ground_truth.dev_membership_sha256 != split.dev_membership_sha256:
        raise ValueError("ground truth development membership hash mismatch")
    if ground_truth.blind_membership_sha256 != split.blind_membership_sha256:
        raise ValueError("ground truth blind membership hash mismatch")
    if require_completed:
        incomplete = [row.file for row in ground_truth.records if not row.completed]
        if incomplete:
            raise ValueError(f"ground truth has incomplete records: {len(incomplete)}")


def validate_blind_annotation_bundle(
    bundle: BlindAnnotationBundle,
    split: DirectorVisualSplit,
    *,
    brief_confirmation_sha256: str,
) -> None:
    """Validate one independent blind-label export without exposing predictions."""

    validate_ground_truth(bundle.visual_ground_truth, split, require_completed=False)
    if bundle.source_manifest_sha256 != split.source_manifest_sha256:
        raise ValueError("blind annotation source manifest hash mismatch")
    if bundle.blind_membership_sha256 != split.blind_membership_sha256:
        raise ValueError("blind annotation membership hash mismatch")
    if bundle.brief_confirmation_sha256 != brief_confirmation_sha256:
        raise ValueError("blind annotation brief confirmation hash mismatch")

    blind_rows = [
        row for row in bundle.visual_ground_truth.records if row.split == "blind"
    ]
    if any(not row.completed for row in blind_rows):
        raise ValueError("blind visual ground truth has incomplete records")
    expected = {(row.material_id, row.file) for row in blind_rows}
    observed = [(row.material_id, row.file) for row in bundle.director_records]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        raise ValueError("director labels differ from blind split")
    if any(not row.completed for row in bundle.director_records):
        raise ValueError("blind director ground truth has incomplete records")


class EvaluationItemRef(VisualStrictModel):
    material_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    file: str = Field(min_length=1)


class EvaluationInputSha256(VisualStrictModel):
    split: str = Field(pattern=r"^[0-9a-f]{64}$")
    brief_confirmation: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_observations: str = Field(pattern=r"^[0-9a-f]{64}$")
    assisted_observations: str = Field(pattern=r"^[0-9a-f]{64}$")
    intent_decisions: str = Field(pattern=r"^[0-9a-f]{64}$")


class EnumFieldEvaluation(VisualStrictModel):
    total: int = Field(ge=0)
    covered: int = Field(ge=0)
    uncovered: int = Field(ge=0)
    correct_covered: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    covered_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    end_to_end_accuracy: float = Field(ge=0.0, le=1.0)
    uncovered_items: list[EvaluationItemRef] = Field(default_factory=list)
    mismatched_items: list[EvaluationItemRef] = Field(default_factory=list)


class LabelEvaluation(VisualStrictModel):
    support: int = Field(ge=0)
    predicted: int = Field(ge=0)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)


class MultiLabelEvaluation(VisualStrictModel):
    total: int = Field(ge=0)
    covered: int = Field(ge=0)
    uncovered: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    label_universe: list[str]
    zero_division: Literal[0] = 0
    micro_precision: float = Field(ge=0.0, le=1.0)
    micro_recall: float = Field(ge=0.0, le=1.0)
    micro_f1: float = Field(ge=0.0, le=1.0)
    macro_f1: float = Field(ge=0.0, le=1.0)
    exact_set_accuracy: float = Field(ge=0.0, le=1.0)
    covered_exact_set_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    per_label: dict[str, LabelEvaluation]
    uncovered_items: list[EvaluationItemRef] = Field(default_factory=list)


class VisualTrackEvaluation(VisualStrictModel):
    source_status: Literal["partial", "completed"]
    source_mode: Literal["automatic", "assisted", "scanner_only"]
    sample_count: int = Field(ge=0)
    coverage_rule: Literal[
        "supported assertion with non-null value; explicit unknown is a prediction"
    ] = "supported assertion with non-null value; explicit unknown is a prediction"
    enum_fields: dict[str, EnumFieldEvaluation]
    content_families: MultiLabelEvaluation


class DirectorEvaluation(VisualStrictModel):
    bucket_labels: list[Bucket]
    bucket_accuracy: float = Field(ge=0.0, le=1.0)
    bucket_confusion_matrix: dict[str, dict[str, int]]
    function_labels: list[DirectorFunction]
    function_zero_division: Literal[0] = 0
    function_metrics: dict[str, LabelEvaluation]
    function_micro_precision: float = Field(ge=0.0, le=1.0)
    function_micro_recall: float = Field(ge=0.0, le=1.0)
    function_micro_f1: float = Field(ge=0.0, le=1.0)
    function_exact_set_accuracy: float = Field(ge=0.0, le=1.0)


class BlindAnnotationEvaluationReport(VisualStrictModel):
    schema_version: Literal["0.3.0"] = "0.3.0"
    evaluation_mode: Literal["frozen_blind_baseline"] = "frozen_blind_baseline"
    dataset_id: Literal["travel-director-skill-blind-v1"] = (
        "travel-director-skill-blind-v1"
    )
    split: Literal["blind"] = "blind"
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    blind_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_sha256: EvaluationInputSha256
    brief: dict[str, Any]
    sample_count: int = Field(ge=0)
    visual_results: dict[str, VisualTrackEvaluation]
    director_results: DirectorEvaluation
    external_call_count: Literal[0] = 0


_SUPPORTED_PREDICTION_STATUSES = {"measured", "candidate", "confirmed"}


def _safe_divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _evaluation_ref(row: GroundTruthRecord) -> EvaluationItemRef:
    return EvaluationItemRef(material_id=row.material_id, file=row.file)


def _assertion_map(item: ClipObservation) -> dict[str, Any]:
    fields = [assertion.field for assertion in item.assertions]
    if len(fields) != len(set(fields)):
        raise ValueError(
            f"observation has duplicate assertion fields: {item.material.material_id}"
        )
    return {assertion.field: assertion for assertion in item.assertions}


def _prediction(assertions: dict[str, Any], field: str) -> tuple[bool, Any]:
    assertion = assertions.get(field)
    if (
        assertion is None
        or assertion.status not in _SUPPORTED_PREDICTION_STATUSES
        or assertion.value is None
    ):
        return False, None
    return True, assertion.value


def _validate_observation_membership(
    observations: ClipObservationBatch,
    expected: set[tuple[str, str]],
    *,
    label: str,
) -> None:
    observed = [
        (item.material.material_id, item.material.relative_path)
        for item in observations.items
    ]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        raise ValueError(f"{label} observation membership differs from blind split")
    for item in observations.items:
        _assertion_map(item)


def _evaluate_enum_fields(
    ground_truth: list[GroundTruthRecord],
    predictions: dict[str, dict[str, Any]],
) -> dict[str, EnumFieldEvaluation]:
    results: dict[str, EnumFieldEvaluation] = {}
    total = len(ground_truth)
    for field in ENUM_VISUAL_EVALUATION_FIELDS:
        covered = 0
        correct = 0
        uncovered_items: list[EvaluationItemRef] = []
        mismatched_items: list[EvaluationItemRef] = []
        for row in ground_truth:
            supported, predicted = _prediction(predictions[row.material_id], field)
            if not supported:
                uncovered_items.append(_evaluation_ref(row))
                continue
            if not isinstance(predicted, str):
                raise ValueError(f"{field} prediction must be a string")
            covered += 1
            if predicted == getattr(row, field):
                correct += 1
            else:
                mismatched_items.append(_evaluation_ref(row))
        results[field] = EnumFieldEvaluation(
            total=total,
            covered=covered,
            uncovered=total - covered,
            correct_covered=correct,
            coverage=_safe_divide(covered, total),
            covered_accuracy=(correct / covered if covered else None),
            end_to_end_accuracy=_safe_divide(correct, total),
            uncovered_items=uncovered_items,
            mismatched_items=mismatched_items,
        )
    return results


def _label_evaluation(tp: int, fp: int, fn: int) -> LabelEvaluation:
    precision = _safe_divide(tp, tp + fp)
    recall = _safe_divide(tp, tp + fn)
    return LabelEvaluation(
        support=tp + fn,
        predicted=tp + fp,
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        precision=precision,
        recall=recall,
        f1=_safe_divide(2 * tp, 2 * tp + fp + fn),
    )


def _content_set(value: Any) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("content_families prediction must be a list of strings")
    invalid = set(value) - set(CONTENT_FAMILY_EVALUATION_LABELS) - {"unknown"}
    if invalid:
        raise ValueError(f"unsupported content_families predictions: {sorted(invalid)}")
    return set(value) - {"unknown"}


def _evaluate_content_families(
    ground_truth: list[GroundTruthRecord],
    predictions: dict[str, dict[str, Any]],
) -> MultiLabelEvaluation:
    total = len(ground_truth)
    covered = 0
    exact = 0
    covered_exact = 0
    uncovered_items: list[EvaluationItemRef] = []
    pairs: list[tuple[set[str], set[str], bool]] = []
    for row in ground_truth:
        supported, predicted = _prediction(
            predictions[row.material_id], "content_families"
        )
        expected = set(row.content_families) - {"unknown"}
        if supported:
            predicted_set = _content_set(predicted)
            covered += 1
            covered_exact += int(predicted_set == expected)
        else:
            predicted_set = set()
            uncovered_items.append(_evaluation_ref(row))
        exact += int(predicted_set == expected)
        pairs.append((predicted_set, expected, supported))

    per_label: dict[str, LabelEvaluation] = {}
    total_tp = total_fp = total_fn = 0
    for label in CONTENT_FAMILY_EVALUATION_LABELS:
        tp = sum(label in predicted and label in expected for predicted, expected, _ in pairs)
        fp = sum(label in predicted and label not in expected for predicted, expected, _ in pairs)
        fn = sum(label not in predicted and label in expected for predicted, expected, _ in pairs)
        per_label[label] = _label_evaluation(tp, fp, fn)
        total_tp += tp
        total_fp += fp
        total_fn += fn
    return MultiLabelEvaluation(
        total=total,
        covered=covered,
        uncovered=total - covered,
        coverage=_safe_divide(covered, total),
        label_universe=list(CONTENT_FAMILY_EVALUATION_LABELS),
        micro_precision=_safe_divide(total_tp, total_tp + total_fp),
        micro_recall=_safe_divide(total_tp, total_tp + total_fn),
        micro_f1=_safe_divide(2 * total_tp, 2 * total_tp + total_fp + total_fn),
        macro_f1=_safe_divide(
            sum(metric.f1 for metric in per_label.values()), len(per_label)
        ),
        exact_set_accuracy=_safe_divide(exact, total),
        covered_exact_set_accuracy=(covered_exact / covered if covered else None),
        per_label=per_label,
        uncovered_items=uncovered_items,
    )


def _evaluate_visual_track(
    observations: ClipObservationBatch,
    ground_truth: list[GroundTruthRecord],
) -> VisualTrackEvaluation:
    predictions = {
        item.material.material_id: _assertion_map(item)
        for item in observations.items
    }
    return VisualTrackEvaluation(
        source_status=observations.status,
        source_mode=observations.mode,
        sample_count=len(ground_truth),
        enum_fields=_evaluate_enum_fields(ground_truth, predictions),
        content_families=_evaluate_content_families(ground_truth, predictions),
    )


def _evaluate_director(
    ground_truth: list[DirectorGroundTruthRecord],
    decisions: IntentDecisionBatch,
) -> DirectorEvaluation:
    expected = {row.material_id: row for row in ground_truth}
    predicted = {row.material_id: row for row in decisions.items}
    total = len(ground_truth)
    confusion = {
        actual: {prediction: 0 for prediction in BUCKET_EVALUATION_LABELS}
        for actual in BUCKET_EVALUATION_LABELS
    }
    correct_buckets = 0
    exact_functions = 0
    function_pairs: list[tuple[set[str], set[str]]] = []
    for material_id, truth in expected.items():
        decision = predicted[material_id]
        confusion[truth.bucket][decision.bucket] += 1
        correct_buckets += int(truth.bucket == decision.bucket)
        predicted_functions = set(decision.director_function_candidates)
        expected_functions = set(truth.director_functions)
        exact_functions += int(predicted_functions == expected_functions)
        function_pairs.append((predicted_functions, expected_functions))

    function_metrics: dict[str, LabelEvaluation] = {}
    total_tp = total_fp = total_fn = 0
    for label in DIRECTOR_FUNCTION_EVALUATION_LABELS:
        tp = sum(label in prediction and label in truth for prediction, truth in function_pairs)
        fp = sum(label in prediction and label not in truth for prediction, truth in function_pairs)
        fn = sum(label not in prediction and label in truth for prediction, truth in function_pairs)
        function_metrics[label] = _label_evaluation(tp, fp, fn)
        total_tp += tp
        total_fp += fp
        total_fn += fn
    return DirectorEvaluation(
        bucket_labels=list(BUCKET_EVALUATION_LABELS),
        bucket_accuracy=_safe_divide(correct_buckets, total),
        bucket_confusion_matrix=confusion,
        function_labels=list(DIRECTOR_FUNCTION_EVALUATION_LABELS),
        function_metrics=function_metrics,
        function_micro_precision=_safe_divide(total_tp, total_tp + total_fp),
        function_micro_recall=_safe_divide(total_tp, total_tp + total_fn),
        function_micro_f1=_safe_divide(
            2 * total_tp, 2 * total_tp + total_fp + total_fn
        ),
        function_exact_set_accuracy=_safe_divide(exact_functions, total),
    )


def evaluate_blind_annotation_files(
    *,
    split_path: Path,
    brief_confirmation_path: Path,
    annotation_path: Path,
    raw_observations_path: Path,
    assisted_observations_path: Path,
    intent_decisions_path: Path,
) -> BlindAnnotationEvaluationReport:
    """Validate frozen inputs and evaluate V0.2 predictions without modifying rules."""

    split = DirectorVisualSplit.model_validate_json(
        split_path.read_text(encoding="utf-8")
    )
    brief = BriefConfirmation.model_validate_json(
        brief_confirmation_path.read_text(encoding="utf-8")
    )
    annotation = BlindAnnotationBundle.model_validate_json(
        annotation_path.read_text(encoding="utf-8")
    )
    raw = ClipObservationBatch.model_validate_json(
        raw_observations_path.read_text(encoding="utf-8")
    )
    assisted = ClipObservationBatch.model_validate_json(
        assisted_observations_path.read_text(encoding="utf-8")
    )
    decisions = IntentDecisionBatch.model_validate_json(
        intent_decisions_path.read_text(encoding="utf-8")
    )
    brief_hash = sha256_file(brief_confirmation_path)
    validate_blind_annotation_bundle(
        annotation,
        split,
        brief_confirmation_sha256=brief_hash,
    )
    if brief.status != "completed":
        raise ValueError("completed brief confirmation is required")
    if raw.status not in {"partial", "completed"}:
        raise ValueError("raw observations must be partial or completed")
    if assisted.status != "completed" or any(
        item.review_required_fields for item in assisted.items
    ):
        raise ValueError("completed assisted observations are required")
    if decisions.status != "completed":
        raise ValueError("completed intent decisions are required")

    visual_ground_truth = [
        row for row in annotation.visual_ground_truth.records if row.split == "blind"
    ]
    expected_membership = {
        (row.material_id, row.file) for row in visual_ground_truth
    }
    _validate_observation_membership(raw, expected_membership, label="raw")
    _validate_observation_membership(
        assisted, expected_membership, label="assisted"
    )
    expected_ids = {row.material_id for row in visual_ground_truth}
    decision_ids = [row.material_id for row in decisions.items]
    if len(decision_ids) != len(set(decision_ids)) or set(decision_ids) != expected_ids:
        raise ValueError("intent decision membership differs from blind split")

    return BlindAnnotationEvaluationReport(
        source_manifest_sha256=split.source_manifest_sha256,
        blind_membership_sha256=split.blind_membership_sha256,
        input_sha256=EvaluationInputSha256(
            split=sha256_file(split_path),
            brief_confirmation=brief_hash,
            annotation=sha256_file(annotation_path),
            raw_observations=sha256_file(raw_observations_path),
            assisted_observations=sha256_file(assisted_observations_path),
            intent_decisions=sha256_file(intent_decisions_path),
        ),
        brief=brief.normalized_fields.model_dump(mode="json"),
        sample_count=len(visual_ground_truth),
        visual_results={
            "raw": _evaluate_visual_track(raw, visual_ground_truth),
            "assisted": _evaluate_visual_track(assisted, visual_ground_truth),
        },
        director_results=_evaluate_director(annotation.director_records, decisions),
    )


def write_blind_annotation_evaluation(
    report: BlindAnnotationEvaluationReport,
    output: Path,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical_bytes(report.model_dump(mode="json")))
    return output


class FieldConfirmation(VisualStrictModel):
    material_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    field: str = Field(min_length=1)
    original_value: Any = None
    original_status: Literal["measured", "candidate", "confirmed", "abstained", "unavailable"]
    confirmed_value: Any = None
    confirmed_status: Literal["confirmed", "abstained"]
    reviewer_note: str = ""
    changed_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def abstention_has_no_value(self) -> "FieldConfirmation":
        if self.confirmed_status == "abstained" and self.confirmed_value is not None:
            raise ValueError("abstained confirmation must not carry a value")
        return self


class VisualConfirmation(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    source_observations_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["completed", "partial"]
    reviewer: str = Field(min_length=1)
    items: list[FieldConfirmation]

    @model_validator(mode="after")
    def fields_are_unique_per_material(self) -> "VisualConfirmation":
        keys = [(item.material_id, item.field) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate field confirmation")
        return self


class DirectorVisualBrief(VisualStrictModel):
    brief_id: str = Field(min_length=1)
    purpose: Literal["development_anchor", "blind_project"]
    brief: RawCreativeBrief


class DirectorVisualBriefSet(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    briefs: list[DirectorVisualBrief]


class DuplicateFixtureResult(VisualStrictModel):
    exact_match: bool
    near_match: bool
    distinct_match: bool
    exact_distance: int
    near_distance: int
    distinct_distance: int
    threshold: int
    real_pair_status: Literal["not_evaluated_real_pair"] = "not_evaluated_real_pair"


def _dhash(path: Path) -> int:
    with Image.open(path) as image:
        gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(gray.get_flattened_data())
    value = 0
    for row in range(8):
        for column in range(8):
            left = pixels[row * 9 + column]
            right = pixels[row * 9 + column + 1]
            value = (value << 1) | int(left > right)
    return value


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def evaluate_duplicate_fixture(
    original: Path,
    exact: Path,
    near: Path,
    distinct: Path,
    *,
    threshold: int = 8,
) -> DuplicateFixtureResult:
    original_hash = _dhash(original)
    exact_distance = _hamming(original_hash, _dhash(exact))
    near_distance = _hamming(original_hash, _dhash(near))
    distinct_distance = _hamming(original_hash, _dhash(distinct))
    return DuplicateFixtureResult(
        exact_match=original.read_bytes() == exact.read_bytes(),
        near_match=near_distance <= threshold,
        distinct_match=distinct_distance <= threshold,
        exact_distance=exact_distance,
        near_distance=near_distance,
        distinct_distance=distinct_distance,
        threshold=threshold,
    )


def load_cv_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in payload["items"]:
        rows.append(
            {
                "file": item["file"],
                "brightness_score": item.get("quality", {}).get("brightness_score"),
                "laplacian_variance_raw": item.get("quality", {}).get(
                    "laplacian_variance_raw"
                ),
                "motion_intensity_raw": item.get("motion", {}).get(
                    "motion_intensity_raw"
                ),
            }
        )
    return rows


def _selected_probe_paths(probe_dir: Path, count: int = 4) -> list[Path]:
    files = sorted(probe_dir.glob("*.jpg"))
    if not files:
        raise FileNotFoundError(f"no saved probe frames: {probe_dir}")
    if len(files) <= count:
        return files
    indices = sorted({round(index * (len(files) - 1) / (count - 1)) for index in range(count)})
    return [files[index] for index in indices]


def build_blank_observations(
    split: DirectorVisualSplit,
    source_hashes: dict[str, str],
) -> ClipObservationBatch:
    items: list[ClipObservation] = []
    for manifest in (split.dev, split.blind):
        for entry in manifest.entries:
            source_hash = source_hashes[entry.source.relative_path]
            items.append(
                ClipObservation(
                    material=MaterialRef(
                        material_id=derive_material_id(source_hash),
                        relative_path=entry.source.relative_path,
                        source_sha256=source_hash,
                        size_bytes=entry.source.size_bytes,
                        mtime_ns=entry.source.mtime_ns,
                        duration_seconds=entry.technical.duration,
                        fps=entry.technical.fps,
                        orientation=entry.technical.orientation,
                        rotation=entry.technical.rotation,
                    ),
                    provider="annotation_template",
                    observation_status="abstained",
                    unknown_fields=[
                        "technical_usability",
                        "content_families",
                        "setting",
                        "lighting",
                        "people_presence",
                        "people_count_band",
                        "subject_candidates",
                        "activity_candidates",
                    ],
                    review_required_fields=[
                        "technical_usability",
                        "content_families",
                        "setting",
                        "lighting",
                        "people_presence",
                        "people_count_band",
                    ],
                )
            )
    return ClipObservationBatch(status="partial", mode="scanner_only", items=items)


def default_brief_set() -> DirectorVisualBriefSet:
    return DirectorVisualBriefSet(
        briefs=[
            DirectorVisualBrief(
                brief_id="bright-city-exploration",
                purpose="development_anchor",
                brief=RawCreativeBrief(
                    raw_description="制作一条明亮、有推进感的城市探索旅行短片，重视空间变化和行动感。"
                ),
            ),
            DirectorVisualBrief(
                brief_id="warm-people-memory",
                purpose="development_anchor",
                brief=RawCreativeBrief(
                    raw_description="制作一条温暖、重人物关系和真实互动的旅行回忆短片。"
                ),
            ),
            DirectorVisualBrief(
                brief_id="quiet-cultural-texture",
                purpose="development_anchor",
                brief=RawCreativeBrief(
                    raw_description="制作一条安静、重空间层次与文化质感的旅行短片，节奏克制。"
                ),
            ),
            DirectorVisualBrief(
                brief_id="blind-primary",
                purpose="blind_project",
                brief=RawCreativeBrief(
                    raw_description="制作一条有进入、探索和收束结构的开封旅行短片，兼顾城市氛围与同行体验。"
                ),
            ),
        ]
    )


def freeze_evaluation_pack(
    source_manifest_path: Path,
    cv_profile_path: Path,
    probe_root: Path,
    output_dir: Path,
) -> dict[str, Path]:
    """Freeze metadata-only splits and templates while reusing saved probe frames."""

    inventory = TestManifest.model_validate_json(
        source_manifest_path.read_text(encoding="utf-8")
    )
    split = build_evaluation_split(
        inventory,
        load_cv_rows(cv_profile_path),
        source_manifest_sha256=sha256_file(source_manifest_path),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_entries = split.dev.entries + split.blind.entries
    source_hashes: dict[str, str] = {}
    frame_paths: dict[str, list[str]] = {}
    index_by_path = {
        entry.source.relative_path: index
        for index, entry in enumerate(inventory.entries)
    }
    for entry in selected_entries:
        relative_path = entry.source.relative_path
        source_path = Path(inventory.input_root) / relative_path
        source_hashes[relative_path] = sha256_file(source_path)
        index = index_by_path[relative_path]
        probes = _selected_probe_paths(probe_root / f"{index:04d}")
        frame_paths[relative_path] = [
            path.relative_to(output_dir).as_posix() for path in probes
        ]

    ground_truth = build_ground_truth_template(split, source_hashes, frame_paths)
    observations = build_blank_observations(split, source_hashes)
    paths = {
        "split": output_dir / "director_visual_split.json",
        "dev": output_dir / "director_visual_dev_manifest.json",
        "blind": output_dir / "director_visual_blind_manifest.json",
        "briefs": output_dir / "director_visual_briefs.json",
        "ground_truth": output_dir / "director_visual_ground_truth.template.json",
        "observations": output_dir / "director_visual_observations.template.json",
    }
    payloads = {
        "split": split.model_dump(mode="json"),
        "dev": split.dev.model_dump(mode="json"),
        "blind": split.blind.model_dump(mode="json"),
        "briefs": default_brief_set().model_dump(mode="json"),
        "ground_truth": ground_truth.model_dump(mode="json"),
        "observations": observations.model_dump(mode="json"),
    }
    for name, path in paths.items():
        path.write_bytes(_canonical_bytes(payloads[name]))
    return paths
