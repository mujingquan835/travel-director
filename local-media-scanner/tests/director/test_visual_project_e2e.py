from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from director.cli import app
from director.project import (
    LOCAL_STAGE_ORDER,
    VISUAL_STAGE_ORDER,
    ProjectConflict,
    advance_project,
    create_project,
    create_visual_project,
    load_project_state,
    open_project,
)
from director.schema import UserCreativeBrief
from director.visual_schema import RawCreativeBrief


def legacy_brief() -> UserCreativeBrief:
    return UserCreativeBrief(
        location="开封",
        travel_type="城市漫游",
        target_duration_seconds=60,
        orientation="portrait",
        style="明亮",
        mood="探索",
        rhythm="medium",
    )


def visual_payload(stage: str) -> dict:
    base = {"schema_version": "0.2.0", "status": "completed"}
    material_id = f"sha256:{'a' * 64}"
    evidence = {
        "material_id": material_id,
        "artifact_path": "scanner_result.json",
        "field_path": "items[0].technical.orientation",
        "source_kind": "scanner",
        "status": "measured",
        "sha256": "b" * 64,
    }
    material = {
        "material_id": material_id,
        "relative_path": "trip/clip-01.mov",
        "source_sha256": "a" * 64,
        "size_bytes": 100,
        "mtime_ns": 123,
        "duration_seconds": 8.5,
        "fps": 25.0,
        "orientation": "portrait",
        "rotation": None,
    }
    payloads = {
        "clip_observations": base
        | {
            "mode": "automatic",
            "items": [
                {
                    "schema_version": "0.2.0",
                    "material": material,
                    "provider": "fixture",
                    "observation_status": "automatic",
                    "assertions": [
                        {
                            "field": "orientation",
                            "value": "portrait",
                            "status": "measured",
                            "confidence": None,
                            "evidence_refs": [evidence],
                        }
                    ],
                    "unknown_fields": [],
                    "review_required_fields": [],
                    "errors": [],
                }
            ],
        },
        "intent_brief": base
        | {
            "raw_description": "做一条明亮、有推进感的开封旅行短片",
            "normalized_fields": {"location": "开封", "style": "明亮"},
            "source_spans": [
                {"field": "location", "text": "开封", "start": 10, "end": 12}
            ],
            "unknown_fields": [],
            "review_required_fields": [],
        },
        "brief_confirmation": base
        | {
            "draft_sha256": "c" * 64,
            "normalized_fields": {"location": "开封", "style": "明亮"},
            "changed_fields": [],
            "confirmed_at": "2026-08-31T12:00:00+08:00",
        },
        "intent_decisions": base
        | {
            "items": [
                {
                    "material_id": material_id,
                    "bucket": "candidate",
                    "relevance_score": 0.8,
                    "confidence": 0.8,
                    "director_function_candidates": ["opening"],
                    "reasons": ["竖屏画面符合输出方向"],
                    "evidence_refs": [evidence],
                    "user_confirmation_required": False,
                }
            ]
        },
        "project_coverage": base
        | {
            "content_distribution": {"culture_architecture": 1},
            "lighting_distribution": {},
            "people_distribution": {},
            "motion_distribution": {},
            "duplicate_groups": {},
            "available_director_functions": ["opening"],
            "missing_director_functions": ["ending"],
            "uncertainty_summary": [],
            "evidence_refs": [evidence],
        },
        "director_treatment": base
        | {
            "mode": "automatic",
            "logline": "从城门进入开封，逐步建立探索感。",
            "narrative_spine": "进入—探索—收束",
            "chapters": [
                {
                    "chapter_id": "opening",
                    "title": "进入古城",
                    "director_functions": ["opening"],
                    "material_ids": [material_id],
                    "evidence_refs": [evidence],
                }
            ],
            "emotional_arc": ["期待", "探索"],
            "pacing_strategy": "逐步加速",
            "core_materials": [],
            "candidate_materials": [material_id],
            "redundant_materials": [],
            "reject_suggestions": [],
            "review_required": [],
            "coverage_gaps": ["ending"],
            "evidence_refs": [evidence],
            "unsupported_inferences": [],
        },
        "director_review": base
        | {
            "treatment_sha256": "d" * 64,
            "mode": "automatic",
            "overrides": [],
            "confirmed_at": "2026-08-31T12:01:00+08:00",
        },
        "music_style_recommendations": base
        | {
            "items": [
                {
                    "direction_id": "bright-city-pulse",
                    "plain_description": "明亮、有推进感的轻电子器乐",
                    "genres": ["light_electronic"],
                    "moods": ["exploratory"],
                    "bpm_min": 105,
                    "bpm_max": 120,
                    "instruments": ["acoustic_guitar", "synth"],
                    "drum_density": "medium",
                    "vocals": "instrumental_preferred",
                    "energy_curve": [0.3, 0.6, 0.8],
                    "fit_reason": "匹配逐步加速的导演节奏",
                    "director_evidence_refs": [evidence],
                }
            ],
            "external_call_count": 0,
        },
        "visual_review": base
        | {
            "report_path": "visual_review/index.html",
            "source_artifact_hashes": {"director_treatment": "d" * 64},
            "external_call_count": 0,
        },
    }
    return payloads[stage]


def test_legacy_and_visual_projects_use_independent_stage_graphs(tmp_path: Path) -> None:
    legacy = create_project(tmp_path, "legacy", legacy_brief())
    visual = create_visual_project(
        tmp_path,
        "visual",
        RawCreativeBrief(raw_description="做一条明亮的开封旅行短片"),
    )

    assert load_project_state(legacy).schema_version == "0.1.0"
    assert load_project_state(visual).schema_version == "0.2.0"
    assert "material_profile" in load_project_state(legacy).artifact_paths
    assert "clip_observations" in load_project_state(visual).artifact_paths
    assert "director_review" in load_project_state(visual).artifact_paths
    assert LOCAL_STAGE_ORDER != VISUAL_STAGE_ORDER


def test_visual_project_runs_fixture_stage_graph_and_resumes(tmp_path: Path) -> None:
    paths = create_visual_project(
        tmp_path,
        "visual",
        RawCreativeBrief(raw_description="做一条明亮的开封旅行短片"),
    )
    calls = {stage: 0 for stage in VISUAL_STAGE_ORDER}

    def adapter(stage: str):
        def run(_paths):
            calls[stage] += 1
            return visual_payload(stage)

        return run

    adapters = {stage: adapter(stage) for stage in VISUAL_STAGE_ORDER}
    state = advance_project(paths, "visual_review", adapters)
    resumed = advance_project(paths, "visual_review", adapters)

    assert state.schema_version == "0.2.0"
    assert resumed.status == "completed"
    assert all(calls[stage] == 1 for stage in VISUAL_STAGE_ORDER)


def test_visual_stage_rejects_wrong_schema_version(tmp_path: Path) -> None:
    paths = create_visual_project(
        tmp_path,
        "visual",
        RawCreativeBrief(raw_description="做一条明亮的开封旅行短片"),
    )

    with pytest.raises(ProjectConflict, match="0.2.0"):
        advance_project(
            paths,
            "clip_observations",
            {
                "clip_observations": lambda _paths: {
                    "schema_version": "0.1.0",
                    "status": "completed",
                    "items": [],
                }
            },
        )


def test_visual_project_stops_at_blocked_stage(tmp_path: Path) -> None:
    paths = create_visual_project(
        tmp_path,
        "visual",
        RawCreativeBrief(raw_description="做一条明亮的开封旅行短片"),
    )
    calls: list[str] = []

    def blocked_observations(_paths):
        calls.append("clip_observations")
        return {
            "schema_version": "0.2.0",
            "status": "blocked",
            "mode": "scanner_only",
            "items": [],
        }

    def should_not_run(_paths):
        calls.append("intent_brief")
        return visual_payload("intent_brief")

    state = advance_project(
        paths,
        "visual_review",
        {
            "clip_observations": blocked_observations,
            "intent_brief": should_not_run,
        },
    )

    assert state.status == "blocked"
    assert state.current_stage == "clip_observations"
    assert calls == ["clip_observations"]
    assert not paths.intent_brief.exists()


def test_visual_cli_initializes_and_reports_status(tmp_path: Path) -> None:
    brief = tmp_path / "raw-brief.json"
    brief.write_text(
        RawCreativeBrief(raw_description="做一条明亮的开封旅行短片").model_dump_json(),
        encoding="utf-8",
    )
    runner = CliRunner()
    created = runner.invoke(
        app,
        [
            "init-visual-project",
            "--project-id",
            "visual-cli",
            "--raw-brief",
            str(brief),
            "--run-root",
            str(tmp_path / "runs"),
        ],
    )

    assert created.exit_code == 0, created.output
    root = tmp_path / "runs" / "visual-cli"
    opened = open_project(root)
    assert opened.brief.exists()

    status = runner.invoke(app, ["visual-status", "--project", str(root)])
    assert status.exit_code == 0, status.output
    payload = json.loads(status.stdout)
    assert payload["schema_version"] == "0.2.0"
    assert payload["current_stage"] == "initialized"
