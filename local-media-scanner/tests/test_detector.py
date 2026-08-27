from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from scanner.cli import app
from scanner.detector import Detection, filter_detections, summarize_detections
from scanner.metadata import build_manifest


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


def test_detector_smoke_cli_writes_per_frame_evidence(
    sample_video: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = build_manifest(sample_video.parent, [sample_video])
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    class FakeDetector:
        model_id = "fake/ssdlite"
        weights_id = "fake-default"
        device = "cpu"
        score_threshold = 0.5

        def detect(self, images):
            return [[Detection("person", 0.9, (0, 0, 10, 20))] for _ in images]

    monkeypatch.setattr(
        "scanner.cli.TorchvisionSSDLiteDetector.load",
        lambda **kwargs: FakeDetector(),
    )
    output = tmp_path / "detector-smoke"

    result = CliRunner().invoke(
        app,
        [
            "detector-smoke",
            "--manifest",
            str(manifest_path),
            "--limit",
            "1",
            "--output",
            str(output),
            "--device",
            "cpu",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads((output / "detector_result.json").read_text(encoding="utf-8"))
    assert payload["model_id"] == "fake/ssdlite"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["summary"]["people_present"] is True
    assert payload["items"][0]["frames"][0]["detections"][0]["label"] == "person"
