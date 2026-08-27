from __future__ import annotations

from scanner.detector import Detection, filter_detections, summarize_detections


def test_people_summary_keeps_per_frame_counts() -> None:
    rows = [
        [Detection("person", 0.9, (0, 0, 20, 80))],
        [
            Detection("person", 0.8, (0, 0, 20, 80)),
            Detection("person", 0.7, (30, 0, 50, 80)),
        ],
    ]

    summary = summarize_detections(rows)

    assert summary.people_present is True
    assert summary.people_counts == [1, 2]
    assert summary.people_count_max == 2
    assert summary.main_objects == ["person"]


def test_low_score_detections_are_excluded() -> None:
    rows = [
        Detection("person", 0.2, (0, 0, 1, 1)),
        Detection("car", 0.8, (0, 0, 10, 10)),
    ]

    assert filter_detections(rows, 0.5) == [Detection("car", 0.8, (0, 0, 10, 10))]


def test_summary_orders_objects_by_frame_support_then_score() -> None:
    rows = [
        [Detection("car", 0.8, (0, 0, 10, 10)), Detection("dog", 0.95, (0, 0, 5, 5))],
        [Detection("car", 0.7, (0, 0, 10, 10))],
    ]

    summary = summarize_detections(rows)

    assert summary.main_objects == ["car", "dog"]
    assert summary.object_frame_support == {"car": 2, "dog": 1}


def test_empty_frames_are_valid_negative_evidence() -> None:
    summary = summarize_detections([[], []])

    assert summary.people_present is False
    assert summary.people_counts == [0, 0]
    assert summary.people_count_max == 0
    assert summary.main_objects == []
