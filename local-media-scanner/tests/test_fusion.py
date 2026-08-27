from __future__ import annotations

from scanner.detector import Detection, summarize_detections
from scanner.fusion import fuse_people, fuse_shot_scale, fuse_single_label
from scanner.vision import FramePrediction, LabelScore


def _prediction(field: str, winner: str, runner_up: str, margin: float) -> FramePrediction:
    return FramePrediction(
        field=field,
        scores=[LabelScore(winner, 0.7), LabelScore(runner_up, 0.7 - margin)],
        top_margin=margin,
        source="fixture",
    )


def test_conflicting_scene_frames_abstain() -> None:
    predictions = [
        _prediction("scene", "nature", "city", 0.03),
        _prediction("scene", "city", "building", 0.02),
        _prediction("scene", "building", "nature", 0.01),
    ]

    fused = fuse_single_label(predictions, min_margin=0.08, min_agreement=0.6)

    assert fused.value is None
    assert fused.status == "abstained"


def test_consistent_scene_is_retained_with_evidence() -> None:
    predictions = [
        _prediction("scene", "building", "city", 0.12),
        _prediction("scene", "building", "indoor", 0.10),
        _prediction("scene", "building", "city", 0.14),
    ]

    fused = fuse_single_label(predictions, min_margin=0.08, min_agreement=0.6)

    assert fused.value == "building"
    assert fused.status == "predicted"
    assert fused.agreement == 1.0
    assert fused.margin == 0.12


def test_people_fusion_uses_detector_as_lower_bound() -> None:
    summary = summarize_detections(
        [
            [Detection("person", 0.9, (0, 0, 10, 40))],
            [Detection("person", 0.8, (0, 0, 10, 40)), Detection("person", 0.7, (15, 0, 25, 40))],
        ]
    )

    fused = fuse_people(summary)

    assert fused.present.value is True
    assert fused.count.value == 2
    assert fused.count.evidence_source == "detector_lower_bound"


def test_people_geometry_can_support_medium_but_not_aerial() -> None:
    predictions = [
        _prediction("shot_scale", "wide", "medium", 0.02),
        _prediction("shot_scale", "wide", "medium", 0.03),
        _prediction("shot_scale", "wide", "medium", 0.02),
    ]
    detections = [
        [Detection("person", 0.9, (0, 0, 20, 55))],
        [Detection("person", 0.9, (0, 0, 20, 50))],
        [Detection("person", 0.9, (0, 0, 20, 58))],
    ]

    fused = fuse_shot_scale(predictions, detections, image_sizes=[(100, 100)] * 3)

    assert fused.value == "medium"
    assert fused.evidence_source == "geometry_fusion"
