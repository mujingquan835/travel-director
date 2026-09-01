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
    create_visual_project,
    record_visual_stage_checked,
)
from director.schema import UserCreativeBrief
from director.visual_schema import RawCreativeBrief


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


def _visual_observations(status: str = "completed") -> dict:
    material_id = f"sha256:{'a' * 64}"
    return {
        "schema_version": "0.2.0", "status": status, "mode": "automatic",
        "items": [{
            "schema_version": "0.2.0",
            "material": {"material_id": material_id, "relative_path": "trip/a.mov", "source_sha256": "a" * 64, "size_bytes": 1, "mtime_ns": 1, "duration_seconds": 1.0, "fps": 25.0, "orientation": "landscape"},
            "provider": "scanner_only", "observation_status": "automatic",
            "assertions": [{"field": "technical_usability", "value": "usable", "status": "measured", "evidence_refs": [{"material_id": material_id, "artifact_path": "scanner.json", "field_path": "items[0]", "source_kind": "scanner", "status": "measured", "sha256": "b" * 64}]}],
            "unknown_fields": [], "review_required_fields": [], "errors": [],
        }],
    }


def test_record_visual_stage_publishes_identical_draft_once(tmp_path: Path) -> None:
    paths = create_visual_project(tmp_path, "visual", RawCreativeBrief(raw_description="test"))
    draft = paths.visual_dir / "drafts" / "clip_observations.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(json.dumps(_visual_observations()), encoding="utf-8")
    first = record_visual_stage_checked(paths, "clip_observations", draft)
    second = record_visual_stage_checked(paths, "clip_observations", draft)
    assert first == second
    assert paths.clip_observations.exists()
    assert paths.clip_observations.resolve() != draft.resolve()


def test_record_visual_stage_rejects_changed_draft_and_out_of_order_stage(tmp_path: Path) -> None:
    paths = create_visual_project(tmp_path, "visual", RawCreativeBrief(raw_description="test"))
    observations = paths.visual_dir / "drafts" / "clip_observations.json"
    observations.parent.mkdir(parents=True, exist_ok=True)
    observations.write_text(json.dumps(_visual_observations()), encoding="utf-8")
    record_visual_stage_checked(paths, "clip_observations", observations)
    observations.write_text(json.dumps(_visual_observations("partial")), encoding="utf-8")
    with pytest.raises(ProjectConflict, match="already differs"):
        record_visual_stage_checked(paths, "clip_observations", observations)
    treatment = paths.visual_dir / "drafts" / "director_treatment.json"
    treatment.write_text(json.dumps({"schema_version": "0.2.0", "status": "completed"}), encoding="utf-8")
    with pytest.raises(ProjectConflict, match="predecessor"):
        record_visual_stage_checked(paths, "director_treatment", treatment)
