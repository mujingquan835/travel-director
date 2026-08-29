from __future__ import annotations

import json
from pathlib import Path

import pytest

from director.project import (
    LOCAL_STAGE_ORDER,
    ProjectConflict,
    advance_project,
    create_project,
    record_project_inputs,
)
from director.schema import UserCreativeBrief


def brief() -> UserCreativeBrief:
    return UserCreativeBrief(
        location="开封",
        travel_type="城市漫游",
        target_duration_seconds=60,
        orientation="portrait",
        style="明亮",
        mood="探索",
        rhythm="medium",
    )


def test_existing_project_requires_matching_brief_hash(tmp_path: Path) -> None:
    create_project(tmp_path, "demo", brief())

    with pytest.raises(ProjectConflict):
        create_project(
            tmp_path,
            "demo",
            brief().model_copy(update={"mood": "安静"}),
        )


def test_create_project_initializes_fixed_evidence_layout(tmp_path: Path) -> None:
    paths = create_project(tmp_path, "demo", brief())

    assert paths.brief.exists()
    assert paths.project_state.exists()
    assert paths.external_calls.exists()
    assert json.loads(paths.external_calls.read_text(encoding="utf-8")) == []
    assert paths.catalog_dir.is_dir()
    assert paths.generation_dir.is_dir()
    assert paths.render_dir.is_dir()


def test_resume_skips_completed_local_stage(tmp_path: Path) -> None:
    paths = create_project(tmp_path, "demo", brief())
    calls: dict[str, int] = {stage: 0 for stage in LOCAL_STAGE_ORDER}

    def adapter(stage: str):
        def run(_paths):
            calls[stage] += 1
            return {"schema_version": "0.1.0", "stage": stage}

        return run

    adapters = {stage: adapter(stage) for stage in LOCAL_STAGE_ORDER}
    state = advance_project(paths, "timeline", adapters)
    resumed = advance_project(paths, "timeline", adapters)

    assert resumed.completed_artifact_hashes == state.completed_artifact_hashes
    assert all(calls[stage] == 1 for stage in LOCAL_STAGE_ORDER[:6])
    assert all(calls[stage] == 0 for stage in LOCAL_STAGE_ORDER[6:])


def test_resume_rejects_tampered_completed_artifact(tmp_path: Path) -> None:
    paths = create_project(tmp_path, "demo", brief())
    adapters = {
        stage: (lambda _paths, stage=stage: {"schema_version": "0.1.0", "stage": stage})
        for stage in LOCAL_STAGE_ORDER
    }
    advance_project(paths, "material_profile", adapters)
    paths.material_profile.write_text("{}", encoding="utf-8")

    with pytest.raises(ProjectConflict):
        advance_project(paths, "material_profile", adapters)


def test_project_id_cannot_escape_run_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_project(tmp_path, "../escape", brief())


def test_input_manifest_blocks_changed_local_input(tmp_path: Path) -> None:
    paths = create_project(tmp_path, "demo", brief())
    source = tmp_path / "music.wav"
    source.write_bytes(b"first")
    record_project_inputs(paths, {"music": source})
    source.write_bytes(b"changed")

    with pytest.raises(ProjectConflict):
        record_project_inputs(paths, {"music": source})
