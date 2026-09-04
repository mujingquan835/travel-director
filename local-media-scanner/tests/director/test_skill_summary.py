from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from director.cli import app
from director.director_treatment import build_director_treatment
from director.intent_matcher import build_intent_decisions, build_project_coverage
from director.music_prompt_recommender import recommend_music_prompts
from director.project import (
    ProjectConflict,
    create_visual_project,
    load_project_state,
    open_project,
    record_supporting_artifact,
    record_visual_stage_checked,
)
from director.skill_summary import (
    EXTERNAL_SERVICES,
    build_skill_run_summary,
    write_skill_run_summary,
)
from director.visual_review import build_automatic_director_review
from director.visual_schema import NormalizedIntentDraft, RawCreativeBrief
from tests.director.test_intent_matcher import confirmed_brief, six_confirmed_observations


def _record_visual_draft(paths, stage: str, payload: object) -> Path:
    artifact = paths.visual_drafts / f"{stage}.json"
    artifact.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_visual_stage_checked(paths, stage, artifact)
    return artifact


def _intent_brief_payload(
    raw_description: str, travel_type: str = "城市漫游"
) -> dict[str, object]:
    return NormalizedIntentDraft(
        status="completed",
        raw_description=raw_description,
        normalized_fields=confirmed_brief(travel_type).normalized_fields,
        source_spans=[],
        unknown_fields=[],
        conflicting_fields=[],
        review_required_fields=[],
        issues=[],
    ).model_dump(mode="json")


def _set_external_calls(paths, payload: list[dict[str, object]]) -> None:
    record_supporting_artifact(
        paths, paths.external_calls, payload, state_key="external_calls"
    )


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _rewrite_recorded_stage(paths, stage: str, payload: dict[str, object]) -> None:
    canonical = paths.artifact_for(stage)
    canonical.write_bytes(_canonical_bytes(payload))
    state_payload = json.loads(paths.project_state.read_text(encoding="utf-8"))
    state_payload["completed_artifact_hashes"][stage] = hashlib.sha256(
        canonical.read_bytes()
    ).hexdigest()
    paths.project_state.write_text(
        json.dumps(state_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def completed_project(
    tmp_path: Path,
    *,
    observation_mode: str = "assisted",
    treatment_override: dict[str, object] | None = None,
    review: bool = True,
    prompts: bool = True,
    ledger_payload: list[dict[str, object]] | None = None,
) -> Path:
    raw_description = "开封古城城市漫游，竖屏，60秒，纪实探索风格。"
    paths = create_visual_project(
        tmp_path,
        "demo",
        RawCreativeBrief(raw_description=raw_description),
    )
    observations = six_confirmed_observations().model_copy(
        update={"mode": observation_mode}
    )
    brief = confirmed_brief("城市漫游")
    decisions = build_intent_decisions(observations, brief)
    coverage = build_project_coverage(observations, decisions)
    treatment = build_director_treatment(decisions, coverage, brief)
    if treatment_override:
        treatment = treatment.model_copy(update=treatment_override)
    prompts_batch = (
        recommend_music_prompts(treatment, brief, coverage) if prompts else None
    )

    _record_visual_draft(
        paths, "clip_observations", observations.model_dump(mode="json")
    )
    _record_visual_draft(paths, "intent_brief", _intent_brief_payload(raw_description))
    brief = brief.model_copy(
        update={
            "draft_sha256": hashlib.sha256(
                paths.intent_brief.read_bytes()
            ).hexdigest()
        }
    )
    _record_visual_draft(paths, "brief_confirmation", brief.model_dump(mode="json"))
    _record_visual_draft(paths, "intent_decisions", decisions.model_dump(mode="json"))
    _record_visual_draft(paths, "project_coverage", coverage.model_dump(mode="json"))
    _record_visual_draft(
        paths, "director_treatment", treatment.model_dump(mode="json")
    )
    if review:
        review_artifact = build_automatic_director_review(treatment)
        _record_visual_draft(
            paths, "director_review", review_artifact.model_dump(mode="json")
        )
    if prompts and prompts_batch is not None:
        _record_visual_draft(
            paths,
            "music_style_recommendations",
            prompts_batch.model_dump(mode="json"),
        )
    _set_external_calls(paths, ledger_payload or [])
    return paths.root


def test_completed_summary_uses_three_bounded_prompts_and_absolute_paths(
    tmp_path: Path,
) -> None:
    project_root = completed_project(tmp_path, observation_mode="automatic")

    result = build_skill_run_summary(project_root)

    assert result.project_mode == "automatic"
    assert result.external_call_count == 0
    assert result.external_services == {
        name: "not_executed" for name in EXTERNAL_SERVICES
    }
    assert len(result.music_prompts) == 3
    assert all(len(prompt) <= 200 for prompt in result.music_prompts)
    assert all(Path(path).is_absolute() for path in result.artifact_paths.values())
    assert result.artifact_paths["final_summary"].endswith("visual/final_summary.json")
    assert "input_manifest" not in result.artifact_paths
    assert "review_route" not in result.artifact_paths


@pytest.mark.parametrize(
    ("kwargs", "expected_gap"),
    [
        (
            {
                "treatment_override": {
                    "unsupported_inferences": ["guessed soundtrack"]
                },
                "prompts": False,
            },
            "unsupported_inferences",
        ),
        ({"review": False, "prompts": False}, "director_review"),
        (
            {
                "ledger_payload": [
                    {
                        "provider": "quduoduo",
                        "operation": "search",
                        "authorized_at": "2026-09-01T10:00:00+08:00",
                        "call_count": 1,
                        "expected_cost": "unknown",
                        "actual_cost": "unknown",
                        "output_status": "not_started",
                    }
                ]
            },
            "external_calls",
        ),
    ],
)
def test_completed_summary_gate_blocks_unsupported_review_and_external_calls(
    tmp_path: Path,
    kwargs: dict[str, object],
    expected_gap: str,
) -> None:
    project_root = completed_project(tmp_path, **kwargs)

    result = build_skill_run_summary(project_root)

    assert result.project_mode == "blocked"
    assert result.music_prompts == []
    assert expected_gap in result.material_gaps


def test_incomplete_brief_confirmation_prevents_completed_summary(tmp_path: Path) -> None:
    raw_description = "开封古城城市漫游，竖屏，60秒，纪实探索风格。"
    paths = create_visual_project(
        tmp_path,
        "demo",
        RawCreativeBrief(raw_description=raw_description),
    )
    observations = six_confirmed_observations()
    brief = confirmed_brief("城市漫游").model_copy(update={"status": "partial"})

    _record_visual_draft(
        paths, "clip_observations", observations.model_dump(mode="json")
    )
    _record_visual_draft(paths, "intent_brief", _intent_brief_payload(raw_description))
    brief = brief.model_copy(
        update={
            "draft_sha256": hashlib.sha256(
                paths.intent_brief.read_bytes()
            ).hexdigest()
        }
    )
    _record_visual_draft(paths, "brief_confirmation", brief.model_dump(mode="json"))

    result = build_skill_run_summary(paths.root)

    assert result.project_mode == "blocked"
    assert result.music_prompts == []
    assert "brief_confirmation" in result.material_gaps


def test_blocked_summary_retains_checkpoint_paths_and_zero_prompts(tmp_path: Path) -> None:
    raw_description = "开封古城城市漫游，竖屏，60秒，纪实探索风格。"
    paths = create_visual_project(
        tmp_path,
        "demo",
        RawCreativeBrief(raw_description=raw_description),
    )
    observations = six_confirmed_observations()

    _record_visual_draft(
        paths, "clip_observations", observations.model_dump(mode="json")
    )
    _record_visual_draft(paths, "intent_brief", _intent_brief_payload(raw_description))

    result = build_skill_run_summary(paths.root)

    assert result.project_mode == "blocked"
    assert result.music_prompts == []
    assert result.artifact_paths["clip_observations"] == str(
        paths.clip_observations.resolve()
    )
    assert result.artifact_paths["intent_brief"] == str(paths.intent_brief.resolve())
    assert result.artifact_paths["final_summary"] == str(paths.final_summary.resolve())


def test_counts_are_derived_from_artifacts_not_treatment_prose(tmp_path: Path) -> None:
    project_root = completed_project(
        tmp_path,
        treatment_override={
            "logline": "共有999条素材且全部成功，这只是故意写错的文案。",
        },
    )

    result = build_skill_run_summary(project_root)

    assert result.material_count == 6
    assert result.review_required_count == 0
    assert result.unavailable_count == 0
    assert result.successful_material_count == sum(result.bucket_counts.values())


def test_skill_summary_cli_writes_final_summary_and_records_visual_review(
    tmp_path: Path,
) -> None:
    project_root = completed_project(tmp_path, observation_mode="automatic")
    output = project_root / "visual" / "final_summary.json"

    result = CliRunner().invoke(
        app,
        [
            "skill-summary",
            "--project",
            str(project_root),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["project_mode"] == "automatic"
    state = load_project_state(project_root)
    assert state.current_stage == "visual_review"
    visual_review = json.loads(
        (project_root / "visual" / "review.json").read_text(encoding="utf-8")
    )
    assert visual_review["report_path"] == str(output.resolve())
    assert visual_review["external_call_count"] == 0
    assert set(visual_review["source_artifact_hashes"]) == {
        "clip_observations",
        "brief_confirmation",
        "director_treatment",
        "director_review",
        "music_style_recommendations",
    }


def test_write_summary_refreshes_only_derived_optional_paths(tmp_path: Path) -> None:
    project_root = completed_project(tmp_path, observation_mode="automatic")
    paths = open_project(project_root)
    expected = write_skill_run_summary(project_root)
    stale = expected.model_dump(mode="json")
    stale["artifact_paths"]["input_manifest"] = str(paths.input_manifest.resolve())
    stale["artifact_paths"]["review_route"] = str(paths.review_route.resolve())
    paths.final_summary.write_text(json.dumps(stale), encoding="utf-8")

    refreshed = write_skill_run_summary(project_root)

    assert refreshed == expected
    payload = json.loads(paths.final_summary.read_text(encoding="utf-8"))
    assert "input_manifest" not in payload["artifact_paths"]
    assert "review_route" not in payload["artifact_paths"]


def test_summary_rejects_stale_brief_confirmation_hash_even_when_state_matches(
    tmp_path: Path,
) -> None:
    project_root = completed_project(tmp_path, observation_mode="automatic")
    paths = open_project(project_root)
    payload = json.loads(paths.brief_confirmation.read_text(encoding="utf-8"))
    payload["draft_sha256"] = "f" * 64
    _rewrite_recorded_stage(paths, "brief_confirmation", payload)

    with pytest.raises(ProjectConflict, match="brief confirmation draft hash mismatch"):
        build_skill_run_summary(project_root)


def test_summary_accepts_hash_of_semantically_identical_preserved_intent_draft(
    tmp_path: Path,
) -> None:
    project_root = completed_project(tmp_path, observation_mode="automatic")
    paths = open_project(project_root)
    draft_hash = hashlib.sha256(
        (paths.visual_drafts / "intent_brief.json").read_bytes()
    ).hexdigest()
    assert draft_hash != load_project_state(paths).completed_artifact_hashes["intent_brief"]
    payload = json.loads(paths.brief_confirmation.read_text(encoding="utf-8"))
    payload["draft_sha256"] = draft_hash
    _rewrite_recorded_stage(paths, "brief_confirmation", payload)

    result = build_skill_run_summary(project_root)

    assert result.project_mode == "automatic"


def test_completed_confirmation_resolves_partial_intent_draft_gate(
    tmp_path: Path,
) -> None:
    project_root = completed_project(tmp_path, observation_mode="automatic")
    paths = open_project(project_root)
    intent = json.loads(paths.intent_brief.read_text(encoding="utf-8"))
    intent["status"] = "partial"
    preserved_draft = paths.visual_drafts / "intent_brief.json"
    preserved_draft.write_text(
        json.dumps(intent, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _rewrite_recorded_stage(paths, "intent_brief", intent)
    confirmation = json.loads(paths.brief_confirmation.read_text(encoding="utf-8"))
    confirmation["draft_sha256"] = hashlib.sha256(
        preserved_draft.read_bytes()
    ).hexdigest()
    _rewrite_recorded_stage(paths, "brief_confirmation", confirmation)

    result = build_skill_run_summary(project_root)

    assert result.project_mode == "automatic"
    assert "intent_brief" not in result.material_gaps
    assert len(result.music_prompts) == 3


def test_summary_rejects_stale_director_review_hash_even_when_state_matches(
    tmp_path: Path,
) -> None:
    project_root = completed_project(tmp_path, observation_mode="automatic")
    paths = open_project(project_root)
    payload = json.loads(paths.director_review.read_text(encoding="utf-8"))
    payload["treatment_sha256"] = "e" * 64
    _rewrite_recorded_stage(paths, "director_review", payload)

    with pytest.raises(ProjectConflict, match="director review treatment hash mismatch"):
        build_skill_run_summary(project_root)


def test_summary_rejects_state_file_hash_drift(tmp_path: Path) -> None:
    project_root = completed_project(tmp_path, observation_mode="automatic")
    paths = open_project(project_root)
    payload = json.loads(paths.intent_brief.read_text(encoding="utf-8"))
    payload["provider"] = "tampered"
    paths.intent_brief.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConflict, match="completed artifact drifted: intent_brief"):
        build_skill_run_summary(project_root)


def test_skill_summary_preflight_leaves_no_summary_when_visual_review_conflicts(
    tmp_path: Path,
) -> None:
    project_root = completed_project(tmp_path, observation_mode="automatic")
    paths = open_project(project_root)
    paths.visual_review.write_text(
        json.dumps(
            {
                "schema_version": "0.2.0",
                "status": "completed",
                "report_path": "conflict.json",
                "source_artifact_hashes": {"director_treatment": "d" * 64},
                "external_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output = project_root / "visual" / "final_summary.json"

    result = CliRunner().invoke(
        app,
        [
            "skill-summary",
            "--project",
            str(project_root),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code != 0
    assert "untracked artifact already exists:" in result.output
    assert "visual_review" in result.output
    assert not output.exists()
