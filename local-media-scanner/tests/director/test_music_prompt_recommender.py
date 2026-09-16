from __future__ import annotations

from pathlib import Path

import pytest
from click.utils import strip_ansi
from pydantic import ValidationError
from typer.testing import CliRunner

from director.cli import app
from director.director_treatment import build_director_treatment
from director.intent_matcher import build_intent_decisions, build_project_coverage
from director.music_prompt_recommender import recommend_music_prompts
from director.visual_schema import MusicGenerationPromptRecommendationBatch
from tests.director.test_intent_matcher import confirmed_brief, six_confirmed_observations
from tests.director.test_skill_summary import legacy_prompt_fixture


def completed_inputs():
    observations = six_confirmed_observations()
    brief = confirmed_brief("城市漫游")
    decisions = build_intent_decisions(observations, brief)
    coverage = build_project_coverage(observations, decisions)
    treatment = build_director_treatment(decisions, coverage, brief)
    return treatment, brief, coverage


def test_old_generator_requires_session_creative_direction():
    with pytest.raises(ValueError, match="--creative-response"):
        recommend_music_prompts(*completed_inputs())


def test_legacy_artifact_remains_readable():
    historical = legacy_prompt_fixture(completed_inputs()[0])
    loaded = MusicGenerationPromptRecommendationBatch.model_validate_json(
        historical.model_dump_json()
    )
    assert len(loaded.items) == 3
    assert loaded.items[0].parameters.genre == "轻电子旅行器乐"
    assert "原创，不模仿具体歌曲或艺人。" in loaded.items[0].generation_prompt


def test_schema_does_not_require_disclaimer_or_fixed_vocal_wording():
    payload = legacy_prompt_fixture(completed_inputs()[0]).model_dump(mode="json")
    for item in payload["items"]:
        item["generation_prompt"] = item["generation_prompt"].replace(
            "器乐为主，无清晰歌词。原创，不模仿具体歌曲或艺人。", "以器乐承担叙事。"
        )
    parsed = MusicGenerationPromptRecommendationBatch.model_validate(payload)
    assert all("无清晰歌词" not in item.generation_prompt for item in parsed.items)


@pytest.mark.parametrize("mutation", ["too_long", "too_few", "duplicate", "missing_parameters"])
def test_historical_schema_preserves_structural_validation(mutation):
    payload = legacy_prompt_fixture(completed_inputs()[0]).model_dump(mode="json")
    if mutation == "too_long":
        payload["items"][0]["generation_prompt"] = "长" * 201
    elif mutation == "too_few":
        payload["items"] = payload["items"][:2]
    elif mutation == "duplicate":
        payload["items"][1] = payload["items"][0]
    else:
        payload["items"][0]["generation_prompt"] = "与参数不一致"
    with pytest.raises(ValidationError):
        MusicGenerationPromptRecommendationBatch.model_validate(payload)


@pytest.mark.parametrize("existing_output", [False, True])
def test_old_cli_redirects_without_writing_or_overwriting(tmp_path: Path, existing_output):
    paths = []
    for name, artifact in zip(("treatment", "brief", "coverage"), completed_inputs()):
        path = tmp_path / f"{name}.json"
        path.write_text(artifact.model_dump_json(), encoding="utf-8")
        paths.append(path)
    output = tmp_path / "music.json"
    if existing_output:
        output.write_text("preserved", encoding="utf-8")
    result = CliRunner().invoke(app, [
        "recommend-music-prompts", "--treatment", str(paths[0]),
        "--brief-confirmation", str(paths[1]), "--coverage", str(paths[2]),
        "--output", str(output),
    ], terminal_width=200)
    assert result.exit_code != 0
    normalized_output = "".join(strip_ansi(result.output).split())
    assert "--creative-response" in normalized_output
    if existing_output:
        assert output.read_text(encoding="utf-8") == "preserved"
    else:
        assert not output.exists()
