from __future__ import annotations

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from scanner.cli import app
from scanner.schema import ScannerCard


def minimal_card() -> dict:
    return {
        "schema_version": "0.1.0",
        "file": "clip.MOV",
        "source": {
            "relative_path": "clip.MOV",
            "size_bytes": 10,
            "mtime_ns": 20,
        },
        "analysis_status": "complete",
        "technical": {
            "duration": 1.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "orientation": "landscape",
            "codec": "hevc",
        },
        "quality": {
            "brightness_score": 0.5,
            "exposure_status": "normal",
        },
        "motion": {
            "motion_level": "low",
            "static_or_dynamic": "static",
        },
        "content": {
            "people_present": False,
            "people_type": [],
            "main_objects": [],
        },
        "material_role_candidates": [],
        "material_role_evidence": {},
        "representative_frames": [],
        "confidence": {},
        "field_status": {},
        "timings_ms": {},
        "errors": [],
    }


def test_scanner_card_accepts_null_uncertain_fields() -> None:
    card = ScannerCard.model_validate(minimal_card())

    assert card.quality.blur_score is None
    assert card.content.scene_type is None
    assert card.shot_scale is None


def test_scanner_card_rejects_editorial_role() -> None:
    payload = minimal_card()
    payload["editorial_role"] = "opening"

    with pytest.raises(ValidationError):
        ScannerCard.model_validate(payload)


def test_scanner_card_rejects_unknown_scene_type() -> None:
    payload = minimal_card()
    payload["content"]["scene_type"] = "castle"

    with pytest.raises(ValidationError):
        ScannerCard.model_validate(payload)


def test_version_is_available_as_a_subcommand() -> None:
    result = CliRunner().invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"
