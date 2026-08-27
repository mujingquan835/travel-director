"""Conservative video-level fusion with explicit abstention."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Generic, Sequence, TypeVar

from scanner.detector import Detection, DetectionSummary
from scanner.vision import FramePrediction


ValueT = TypeVar("ValueT")


@dataclass(frozen=True)
class FusedField(Generic[ValueT]):
    value: ValueT | None
    status: str
    evidence_source: str
    agreement: float | None = None
    margin: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PeopleFusion:
    present: FusedField[bool]
    count: FusedField[int]


def fuse_people(summary: DetectionSummary) -> PeopleFusion:
    return PeopleFusion(
        present=FusedField(
            value=summary.people_present,
            status="predicted",
            evidence_source="detector",
            agreement=None,
            notes=("Negative evidence is limited by detector recall.",),
        ),
        count=FusedField(
            value=summary.people_count_max,
            status="candidate",
            evidence_source="detector_lower_bound",
            notes=("Maximum detected count is a lower bound, not an exact crowd count.",),
        ),
    )


def fuse_single_label(
    predictions: Sequence[FramePrediction],
    min_margin: float,
    min_agreement: float,
) -> FusedField[str]:
    if not predictions:
        return FusedField(None, "unavailable", "vision_model")
    winners = [prediction.scores[0].label for prediction in predictions if prediction.scores]
    if not winners:
        return FusedField(None, "unavailable", "vision_model")
    winner, count = Counter(winners).most_common(1)[0]
    agreement = count / len(predictions)
    winning_margins = [
        prediction.top_margin
        for prediction in predictions
        if prediction.scores and prediction.scores[0].label == winner
    ]
    margin = float(median(winning_margins)) if winning_margins else 0.0
    if agreement < min_agreement or margin < min_margin:
        return FusedField(
            None,
            "abstained",
            "vision_model",
            agreement=agreement,
            margin=margin,
            notes=("Frame agreement or top margin is below the configured gate.",),
        )
    return FusedField(
        winner,
        "predicted",
        "vision_model",
        agreement=agreement,
        margin=margin,
    )


def _person_height_ratios(
    detections: Sequence[Sequence[Detection]],
    image_sizes: Sequence[tuple[int, int]],
) -> list[float]:
    ratios: list[float] = []
    for frame, (height, _width) in zip(detections, image_sizes, strict=True):
        if height <= 0:
            continue
        people = [row for row in frame if row.label == "person"]
        if not people:
            continue
        ratios.append(max(max(0.0, row.box_xyxy[3] - row.box_xyxy[1]) / height for row in people))
    return ratios


def fuse_shot_scale(
    predictions: Sequence[FramePrediction],
    detections: Sequence[Sequence[Detection]],
    image_sizes: Sequence[tuple[int, int]],
) -> FusedField[str]:
    vision = fuse_single_label(predictions, min_margin=0.08, min_agreement=0.6)
    ratios = _person_height_ratios(detections, image_sizes)
    if ratios:
        height_ratio = float(median(ratios))
        if height_ratio <= 0.35:
            geometry = "wide"
        elif height_ratio <= 0.70:
            geometry = "medium"
        else:
            geometry = "close"
        if vision.value == "aerial":
            if vision.margin is not None and vision.margin >= 0.12:
                return vision
        if vision.value == "close_up":
            return vision
        if vision.value is None or vision.value == geometry:
            return FusedField(
                geometry,
                "predicted",
                "geometry_fusion",
                agreement=vision.agreement,
                margin=vision.margin,
                notes=(f"Median maximum person-height ratio: {height_ratio:.3f}",),
            )
    return vision


def compare_shot_scale_methods(
    predictions: Sequence[FramePrediction],
    detections: Sequence[Sequence[Detection]],
    image_sizes: Sequence[tuple[int, int]],
) -> dict[str, FusedField[str]]:
    vision = fuse_single_label(predictions, min_margin=0.08, min_agreement=0.6)
    ratios = _person_height_ratios(detections, image_sizes)
    geometry: FusedField[str]
    if not ratios:
        geometry = FusedField(None, "unavailable", "person_geometry")
    else:
        ratio = float(median(ratios))
        value = "wide" if ratio <= 0.35 else "medium" if ratio <= 0.70 else "close"
        geometry = FusedField(value, "candidate", "person_geometry", notes=(f"ratio={ratio:.3f}",))
    return {
        "siglip": vision,
        "geometry": geometry,
        "fusion": fuse_shot_scale(predictions, detections, image_sizes),
    }
