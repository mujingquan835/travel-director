from __future__ import annotations

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from director.config import DirectorConfig
from director.cli import app
from director.schema import (
    MusicBlueprint,
    MusicBlueprintSection,
    ProjectState,
    UserCreativeBrief,
)


def test_director_config_uses_bounded_prototype_defaults() -> None:
    config = DirectorConfig()

    assert config.max_internal_candidates == 5
    assert config.displayed_directions == 3
    assert config.min_clip_seconds == 0.8
    assert config.max_clip_seconds == 6.0


def test_brief_accepts_supported_duration() -> None:
    brief = UserCreativeBrief(
        location="开封",
        travel_type="城市漫游",
        target_duration_seconds=60,
        orientation="portrait",
        style="明亮",
        mood="探索",
        rhythm="medium",
    )

    assert brief.target_duration_seconds == 60


@pytest.mark.parametrize("duration", [29, 181])
def test_brief_rejects_duration_outside_prototype_range(duration: int) -> None:
    with pytest.raises(ValidationError):
        UserCreativeBrief(
            location="开封",
            travel_type="城市漫游",
            target_duration_seconds=duration,
            orientation="portrait",
            style="明亮",
            mood="探索",
            rhythm="medium",
        )


def test_blueprint_rejects_reference_identity() -> None:
    payload = {
        "schema_version": "0.1.0",
        "duration_seconds": 60,
        "bpm": 116,
        "meter": "4/4",
        "genre": "轻电子旅行器乐",
        "instrumentation": ["木吉他"],
        "vocals": "none",
        "sections": [
            {"start": 0, "end": 60, "role": "climax", "energy": 0.8}
        ],
        "ending": "明确落点，不淡出",
        "reference_title": "不应进入生成契约",
    }

    with pytest.raises(ValidationError):
        MusicBlueprint.model_validate(payload)


def test_blueprint_requires_contiguous_full_duration_sections() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        MusicBlueprint(
            duration_seconds=60,
            bpm=116,
            meter="4/4",
            genre="轻电子旅行器乐",
            instrumentation=["木吉他"],
            vocals="none",
            sections=[
                MusicBlueprintSection(start=0, end=10, role="intro", energy=0.2),
                MusicBlueprintSection(start=12, end=60, role="climax", energy=0.8),
            ],
            ending="明确落点，不淡出",
        )


def test_project_state_records_failure_instead_of_faking_completion() -> None:
    state = ProjectState(
        project_id="demo",
        status="blocked",
        current_stage="music_generation",
        artifact_paths={},
        errors=[
            {
                "stage": "music_generation",
                "code": "not_authorized",
                "message": "authorization required",
            }
        ],
    )

    assert state.status == "blocked"
    assert state.errors[0].code == "not_authorized"


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectState(
            project_id="demo",
            status="pending",
            current_stage="material_profile",
            artifact_paths={},
            errors=[],
            silently_assume_success=True,
        )


def test_version_is_available_as_a_subcommand() -> None:
    result = CliRunner().invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"
