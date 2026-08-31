from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from director.cli import app
from director.director_treatment import (
    build_director_treatment,
    validate_treatment_enhancement,
)
from director.intent_matcher import build_intent_decisions, build_project_coverage
from director.visual_schema import (
    BriefConfirmation,
    DirectorTreatment,
    EvidenceRef,
)
from tests.director.test_intent_matcher import (
    confirmed_brief,
    six_confirmed_observations,
)


def build_city_treatment() -> tuple[DirectorTreatment, object, object, BriefConfirmation]:
    observations = six_confirmed_observations()
    brief = confirmed_brief("城市漫游")
    decisions = build_intent_decisions(observations, brief)
    coverage = build_project_coverage(observations, decisions)
    treatment = build_director_treatment(decisions, coverage, brief)
    return treatment, observations, decisions, brief


def test_treatment_has_evidence_bound_chapters_emotions_and_memberships() -> None:
    treatment, observations, decisions, _brief = build_city_treatment()

    assert treatment.status == "completed"
    assert treatment.mode == "deterministic"
    assert treatment.chapters
    assert all(chapter.evidence_refs for chapter in treatment.chapters)
    assert all(statement.evidence_refs for statement in treatment.emotional_arc)
    assert treatment.pacing_evidence_refs
    memberships = {
        material_id
        for values in (
            treatment.core_materials,
            treatment.candidate_materials,
            treatment.redundant_materials,
            treatment.reject_suggestions,
            treatment.review_required,
        )
        for material_id in values
    }
    assert memberships == {item.material.material_id for item in observations.items}
    assert treatment.unsupported_inferences == []
    assert treatment.core_materials == [
        item.material_id for item in decisions.items if item.bucket == "core"
    ]


def test_treatment_exposes_missing_ending_instead_of_inventing_one() -> None:
    treatment, _observations, _decisions, _brief = build_city_treatment()

    assert any("ending" in gap for gap in treatment.coverage_gaps)
    assert all("ending" not in chapter.director_functions for chapter in treatment.chapters)


def test_enhancement_validator_rejects_new_evidence_or_memberships() -> None:
    treatment, _observations, _decisions, _brief = build_city_treatment()
    rewritten = treatment.model_copy(
        update={"logline": "从城市环境进入，在行进和人物气息中完成一次克制的探索。"}
    )
    validate_treatment_enhancement(treatment, rewritten)

    invented_ref = EvidenceRef(
        material_id=None,
        artifact_path="invented.json",
        field_path="facts.sunset",
        source_kind="director_rule",
        status="confirmed",
        sha256="f" * 64,
    )
    invented = treatment.model_copy(
        update={"evidence_refs": [*treatment.evidence_refs, invented_ref]}
    )
    with pytest.raises(ValueError, match="evidence"):
        validate_treatment_enhancement(treatment, invented)

    changed_membership = treatment.model_copy(
        update={"core_materials": treatment.core_materials[1:]}
    )
    with pytest.raises(ValueError, match="membership"):
        validate_treatment_enhancement(treatment, changed_membership)


def test_partial_brief_cannot_enter_director_reasoning() -> None:
    brief = confirmed_brief("城市漫游").model_copy(update={"status": "partial"})
    observations = six_confirmed_observations()
    decisions = build_intent_decisions(observations, confirmed_brief("城市漫游"))
    coverage = build_project_coverage(observations, decisions)

    with pytest.raises(ValueError, match="confirmed brief"):
        build_director_treatment(decisions, coverage, brief)


def test_build_director_treatment_cli_writes_three_stage_artifacts(tmp_path: Path) -> None:
    observations_path = tmp_path / "confirmed_observations.json"
    brief_path = tmp_path / "brief_confirmation.json"
    decisions_path = tmp_path / "intent_decisions.json"
    coverage_path = tmp_path / "project_coverage.json"
    treatment_path = tmp_path / "director_treatment.json"
    observations_path.write_text(
        six_confirmed_observations().model_dump_json(indent=2), encoding="utf-8"
    )
    brief_path.write_text(
        confirmed_brief("城市漫游").model_dump_json(indent=2), encoding="utf-8"
    )

    result = CliRunner().invoke(
        app,
        [
            "build-director-treatment",
            "--observations",
            str(observations_path),
            "--brief-confirmation",
            str(brief_path),
            "--decisions-output",
            str(decisions_path),
            "--coverage-output",
            str(coverage_path),
            "--output",
            str(treatment_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(decisions_path.read_text(encoding="utf-8"))["status"] == "completed"
    assert json.loads(coverage_path.read_text(encoding="utf-8"))["status"] == "completed"
    payload = json.loads(treatment_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "deterministic"
    assert "source_in" not in json.dumps(payload)
    assert "source_out" not in json.dumps(payload)


def test_cli_refuses_to_overwrite_confirmed_inputs(tmp_path: Path) -> None:
    observations_path = tmp_path / "confirmed_observations.json"
    brief_path = tmp_path / "brief_confirmation.json"
    observations_path.write_text(
        six_confirmed_observations().model_dump_json(), encoding="utf-8"
    )
    brief_path.write_text(confirmed_brief("城市漫游").model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "build-director-treatment",
            "--observations",
            str(observations_path),
            "--brief-confirmation",
            str(brief_path),
            "--decisions-output",
            str(observations_path),
            "--coverage-output",
            str(tmp_path / "coverage.json"),
            "--output",
            str(tmp_path / "treatment.json"),
        ],
    )

    assert result.exit_code != 0
    assert "cannot overwrite" in result.output
