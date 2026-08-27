from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch
from typer.testing import CliRunner

from scanner.cli import app
from scanner.metadata import build_manifest
from scanner.vision import (
    ACTION_PROMPTS,
    OBJECT_PROMPTS,
    PEOPLE_TYPE_PROMPTS,
    PROMPT_SET_VERSION,
    SCENE_PROMPTS,
    SHOT_SCALE_PROMPTS,
    DeviceResolution,
    FramePrediction,
    LabelScore,
    resolve_device,
    top_margin,
)


def test_prompt_groups_cover_fixed_taxonomies() -> None:
    assert PROMPT_SET_VERSION == "0.1.0"
    assert set(SCENE_PROMPTS) == {
        "nature",
        "city",
        "building",
        "indoor",
        "theme_park",
        "food_dining",
        "transportation",
        "night_scene",
        "other",
    }
    assert set(SHOT_SCALE_PROMPTS) == {"wide", "medium", "close", "close_up", "aerial"}
    assert set(PEOPLE_TYPE_PROMPTS) == {"child", "adult"}
    assert set(ACTION_PROMPTS) == {
        "walking",
        "running",
        "eating",
        "riding",
        "entering",
        "watching",
        "interacting",
        "other",
    }
    assert "building" in OBJECT_PROMPTS
    assert "food" in OBJECT_PROMPTS
    for group in (SCENE_PROMPTS, SHOT_SCALE_PROMPTS, PEOPLE_TYPE_PROMPTS, ACTION_PROMPTS, OBJECT_PROMPTS):
        assert all(len(prompts) >= 3 for prompts in group.values())


def test_margin_uses_top_two_scores() -> None:
    scores = [LabelScore("wide", 0.8), LabelScore("medium", 0.6)]

    assert top_margin(scores) == pytest.approx(0.2)


def test_margin_is_zero_when_fewer_than_two_scores() -> None:
    assert top_margin([LabelScore("wide", 0.8)]) == 0.0


def test_unavailable_mps_returns_explicit_cpu_fallback(monkeypatch) -> None:
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    resolved = resolve_device("auto")

    assert resolved.actual == "cpu"
    assert resolved.fallback_reason == "mps_unavailable"


def test_explicit_unavailable_mps_does_not_silently_fallback(monkeypatch) -> None:
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)

    with pytest.raises(RuntimeError, match="MPS"):
        resolve_device("mps")


def test_vision_smoke_cli_serializes_versioned_frame_evidence(
    sample_video: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = build_manifest(sample_video.parent, [sample_video])
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    class FakeEncoder:
        model_id = "fake/siglip2"
        resolved_revision = "abc123"
        device = DeviceResolution("cpu", "cpu")

        def classify_many(self, images, field_groups):
            result = {}
            for field, prompt_groups in field_groups.items():
                labels = list(prompt_groups)
                scores = [LabelScore(labels[0], 0.8), LabelScore(labels[1], 0.6)]
                result[field] = [FramePrediction(field, scores, 0.2, "fake-source") for _ in images]
            return result

    monkeypatch.setattr(
        "scanner.cli.SiglipEvidenceEncoder.load",
        lambda **kwargs: FakeEncoder(),
    )
    output = tmp_path / "vision-smoke"

    result = CliRunner().invoke(
        app,
        [
            "vision-smoke",
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
    payload = json.loads((output / "vision_result.json").read_text(encoding="utf-8"))
    assert payload["model_id"] == "fake/siglip2"
    assert payload["prompt_set_version"] == "0.1.0"
    assert payload["actual_device"] == "cpu"
    assert payload["items"][0]["frames"][0]["predictions"]["scene"]["top_margin"] == 0.2
