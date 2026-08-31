from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from director.cli import app
from director.director_treatment import build_director_treatment
from director.intent_matcher import build_intent_decisions, build_project_coverage
from director.music_prompt_recommender import recommend_music_prompts
from director.visual_schema import MusicGenerationPromptRecommendationBatch
from tests.director.test_intent_matcher import (
    confirmed_brief,
    six_confirmed_observations,
)


def completed_inputs(travel_type: str = "城市漫游"):
    observations = six_confirmed_observations()
    brief = confirmed_brief(travel_type)
    decisions = build_intent_decisions(observations, brief)
    coverage = build_project_coverage(observations, decisions)
    treatment = build_director_treatment(decisions, coverage, brief)
    return treatment, brief, coverage


def test_returns_exactly_three_self_contained_prompts_under_200_characters() -> None:
    treatment, brief, coverage = completed_inputs()
    result = recommend_music_prompts(treatment, brief, coverage)

    assert result.status == "completed"
    assert result.external_call_count == 0
    assert len(result.items) == 3
    for item in result.items:
        prompt = item.generation_prompt
        parameters = item.parameters
        assert len(prompt) <= 200
        assert f"{parameters.duration_seconds}秒" in prompt
        assert f"{parameters.bpm} BPM" in prompt
        assert parameters.genre in prompt
        assert parameters.mood in prompt
        assert all(instrument in prompt for instrument in parameters.instruments)
        assert parameters.energy_structure in prompt
        assert "鼓点" in prompt
        assert "不模仿具体歌曲或艺人" in prompt
        assert item.fit_reason
        assert item.director_evidence_refs


def test_three_directions_are_pairwise_different_on_at_least_two_axes() -> None:
    treatment, brief, coverage = completed_inputs()
    items = recommend_music_prompts(treatment, brief, coverage).items

    for left_index, left in enumerate(items):
        assert len(left.difference_axes) >= 2
        for right in items[left_index + 1 :]:
            differences = {
                "genre": left.parameters.genre != right.parameters.genre,
                "mood": left.parameters.mood != right.parameters.mood,
                "rhythm": left.parameters.bpm != right.parameters.bpm,
                "instrumentation": left.parameters.instruments
                != right.parameters.instruments,
                "drum_density": left.parameters.drum_density
                != right.parameters.drum_density,
                "energy_structure": left.parameters.energy_structure
                != right.parameters.energy_structure,
            }
            assert sum(differences.values()) >= 2


def test_prompt_parameters_follow_brief_and_director_evidence() -> None:
    treatment, brief, coverage = completed_inputs("自然旅行")
    result = recommend_music_prompts(treatment, brief, coverage)

    assert all(item.parameters.duration_seconds == 60 for item in result.items)
    assert any("宁静" in item.generation_prompt for item in result.items)
    assert all(
        any(ref.source_kind == "user_brief" for ref in item.director_evidence_refs)
        for item in result.items
    )
    assert all("曲多多" not in item.generation_prompt for item in result.items)
    assert all("已生成" not in item.generation_prompt for item in result.items)


def test_incomplete_upstream_artifact_is_rejected() -> None:
    treatment, brief, coverage = completed_inputs()

    with pytest.raises(ValueError, match="completed"):
        recommend_music_prompts(
            treatment.model_copy(update={"status": "partial"}), brief, coverage
        )
    with pytest.raises(ValueError, match="completed"):
        recommend_music_prompts(
            treatment, brief.model_copy(update={"status": "partial"}), coverage
        )


def test_schema_rejects_too_long_prompt_or_fewer_than_three_items() -> None:
    treatment, brief, coverage = completed_inputs()
    result = recommend_music_prompts(treatment, brief, coverage)
    payload = result.model_dump(mode="json")
    payload["items"][0]["generation_prompt"] = "长" * 201
    with pytest.raises(ValidationError, match="200"):
        MusicGenerationPromptRecommendationBatch.model_validate(payload)

    payload = result.model_dump(mode="json")
    payload["items"] = payload["items"][:2]
    with pytest.raises(ValidationError):
        MusicGenerationPromptRecommendationBatch.model_validate(payload)


def test_long_optional_user_text_is_bounded_without_losing_three_outputs() -> None:
    treatment, brief, coverage = completed_inputs()
    brief.normalized_fields.mood = "非常具体且很长的旅行情绪描述" * 20
    brief.normalized_fields.instrument_preferences = ["特别长的自定义乐器名称" * 20]

    result = recommend_music_prompts(treatment, brief, coverage)

    assert len(result.items) == 3
    assert all(len(item.generation_prompt) <= 200 for item in result.items)


def test_recommend_music_prompts_cli_writes_one_ready_to_use_batch(
    tmp_path: Path,
) -> None:
    treatment, brief, coverage = completed_inputs()
    treatment_path = tmp_path / "director_treatment.json"
    brief_path = tmp_path / "brief_confirmation.json"
    coverage_path = tmp_path / "project_coverage.json"
    output = tmp_path / "music_style_recommendations.json"
    treatment_path.write_text(treatment.model_dump_json(indent=2), encoding="utf-8")
    brief_path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    coverage_path.write_text(coverage.model_dump_json(indent=2), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "recommend-music-prompts",
            "--treatment",
            str(treatment_path),
            "--brief-confirmation",
            str(brief_path),
            "--coverage",
            str(coverage_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["items"]) == 3
    assert payload["external_call_count"] == 0
    assert all(len(item["generation_prompt"]) <= 200 for item in payload["items"])
