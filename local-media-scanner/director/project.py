"""Resumable local project orchestration with immutable artifact evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from director.schema import ProjectState, UserCreativeBrief
from director.visual_schema import (
    RawCreativeBrief,
    VisualProjectState,
    validate_visual_stage_artifact,
)


LOCAL_STAGE_ORDER = (
    "material_profile",
    "search_brief",
    "catalog",
    "blueprint",
    "music_structure",
    "timeline",
    "clip_placements",
    "sfx_plan",
)

VISUAL_STAGE_ORDER = (
    "clip_observations",
    "intent_brief",
    "brief_confirmation",
    "intent_decisions",
    "project_coverage",
    "director_treatment",
    "director_review",
    "music_style_recommendations",
    "visual_review",
)

STAGE_GRAPHS = {
    "0.1.0": LOCAL_STAGE_ORDER,
    "0.2.0": VISUAL_STAGE_ORDER,
}


class ProjectConflict(RuntimeError):
    """Existing project evidence no longer matches its recorded contract."""


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    project_state: Path
    brief: Path
    input_manifest: Path
    material_profile: Path
    search_brief: Path
    catalog_dir: Path
    catalog_result: Path
    blueprint: Path
    generation_dir: Path
    generated_music: Path
    music_structure: Path
    timeline_slots: Path
    clip_placements: Path
    sfx_plan: Path
    render_dir: Path
    render_result: Path
    external_calls: Path
    visual_dir: Path
    visual_drafts: Path
    agent_batch_manifest: Path
    agent_batch_results: Path
    review_route: Path
    final_summary: Path
    clip_observations: Path
    intent_brief: Path
    brief_confirmation: Path
    intent_decisions: Path
    project_coverage: Path
    director_treatment: Path
    director_review: Path
    music_style_recommendations: Path
    visual_review: Path

    def artifact_for(self, stage: str) -> Path:
        mapping = {
            "material_profile": self.material_profile,
            "search_brief": self.search_brief,
            "catalog": self.catalog_result,
            "blueprint": self.blueprint,
            "music_structure": self.music_structure,
            "timeline": self.timeline_slots,
            "clip_placements": self.clip_placements,
            "sfx_plan": self.sfx_plan,
            "render": self.render_result,
            "clip_observations": self.clip_observations,
            "intent_brief": self.intent_brief,
            "brief_confirmation": self.brief_confirmation,
            "intent_decisions": self.intent_decisions,
            "project_coverage": self.project_coverage,
            "director_treatment": self.director_treatment,
            "director_review": self.director_review,
            "music_style_recommendations": self.music_style_recommendations,
            "visual_review": self.visual_review,
        }
        try:
            return mapping[stage]
        except KeyError as exc:
            raise ValueError(f"unknown project stage: {stage}") from exc


StageAdapter = Callable[[ProjectPaths], BaseModel | dict[str, Any] | list[Any] | Path]


def _paths(root: Path) -> ProjectPaths:
    return ProjectPaths(
        root=root,
        project_state=root / "project_state.json",
        brief=root / "brief.json",
        input_manifest=root / "input_manifest.json",
        material_profile=root / "material_profile.json",
        search_brief=root / "search_brief.json",
        catalog_dir=root / "catalog",
        catalog_result=root / "catalog" / "result.json",
        blueprint=root / "blueprint.json",
        generation_dir=root / "generation",
        generated_music=root / "generation" / "music_asset.json",
        music_structure=root / "music_structure.json",
        timeline_slots=root / "timeline_slots.json",
        clip_placements=root / "clip_placements.json",
        sfx_plan=root / "sfx_plan.json",
        render_dir=root / "render",
        render_result=root / "render" / "render_result.json",
        external_calls=root / "external_calls.json",
        visual_dir=root / "visual",
        visual_drafts=root / "visual" / "drafts",
        agent_batch_manifest=root / "visual" / "agent_batches" / "manifest.json",
        agent_batch_results=root / "visual" / "agent_batches" / "results",
        review_route=root / "visual" / "review_route.json",
        final_summary=root / "visual" / "final_summary.json",
        clip_observations=root / "visual" / "clip_observations.json",
        intent_brief=root / "visual" / "intent_brief.json",
        brief_confirmation=root / "visual" / "brief_confirmation.json",
        intent_decisions=root / "visual" / "intent_decisions.json",
        project_coverage=root / "visual" / "project_coverage.json",
        director_treatment=root / "visual" / "director_treatment.json",
        director_review=root / "visual" / "director_review.json",
        music_style_recommendations=(
            root / "visual" / "music_style_recommendations.json"
        ),
        visual_review=root / "visual" / "review.json",
    )


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_value(value: BaseModel | dict[str, Any] | list[Any] | Path) -> Any:
    if isinstance(value, Path):
        return json.loads(value.read_text(encoding="utf-8"))
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _validate_schema_version(value: Any, expected: str) -> None:
    records = value if isinstance(value, list) else [value]
    if not records:
        return
    if not all(
        isinstance(record, dict) and record.get("schema_version") == expected
        for record in records
    ):
        raise ProjectConflict(f"stage artifact does not use schema_version {expected}")


def _validated_stage_value(stage: str, value: Any, expected: str) -> Any:
    _validate_schema_version(value, expected)
    if expected != "0.2.0":
        return value
    try:
        return validate_visual_stage_artifact(stage, value)
    except (ValidationError, ValueError) as exc:
        raise ProjectConflict(f"invalid V0.2 artifact for stage {stage}: {exc}") from exc


def _artifact_paths(paths: ProjectPaths, schema_version: str) -> dict[str, str]:
    try:
        stage_order = STAGE_GRAPHS[schema_version]
    except KeyError as exc:
        raise ValueError(f"unsupported project schema_version: {schema_version}") from exc
    return {
        stage: str(paths.artifact_for(stage).relative_to(paths.root))
        for stage in stage_order
    } | {
        "brief": "brief.json",
        "input_manifest": "input_manifest.json",
        "external_calls": "external_calls.json",
    } | (
        {
            "generation": "generation/music_asset.json",
            "render": "render/render_result.json",
        }
        if schema_version == "0.1.0"
        else {}
    )


ProjectStateModel = ProjectState | VisualProjectState


def _write_state(paths: ProjectPaths, state: ProjectStateModel) -> None:
    _atomic_write(paths.project_state, _canonical_bytes(state.model_dump(mode="json")))


def load_project_state(paths: ProjectPaths | Path) -> ProjectStateModel:
    """Load a supported state model without rewriting its schema version."""

    state_path = (
        paths.project_state
        if isinstance(paths, ProjectPaths)
        else paths / "project_state.json"
    )
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    schema_version = payload.get("schema_version")
    if schema_version == "0.1.0":
        return ProjectState.model_validate(payload)
    if schema_version == "0.2.0":
        return VisualProjectState.model_validate(payload)
    raise ProjectConflict(f"unsupported project schema_version: {schema_version}")


def create_project(
    run_root: Path,
    project_id: str,
    brief: UserCreativeBrief,
) -> ProjectPaths:
    """Create or reopen a project only when its immutable brief matches."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", project_id):
        raise ValueError("project_id must be a simple filesystem-safe identifier")
    root = run_root.resolve() / project_id
    paths = _paths(root)
    brief_payload = _canonical_bytes(brief.model_dump(mode="json"))
    brief_hash = _sha256_bytes(brief_payload)

    if paths.brief.exists() or paths.project_state.exists():
        if not paths.brief.exists() or not paths.project_state.exists():
            raise ProjectConflict("existing project is missing required root evidence")
        if _sha256_file(paths.brief) != brief_hash:
            raise ProjectConflict("existing project brief hash does not match")
        state = load_project_state(paths)
        if state.schema_version != "0.1.0":
            raise ProjectConflict("existing project is not a V0.1 project")
        if state.project_id != project_id:
            raise ProjectConflict("existing project id does not match state")
        if state.completed_artifact_hashes.get("brief") != brief_hash:
            raise ProjectConflict("state brief hash does not match brief evidence")
        external_calls_hash = state.completed_artifact_hashes.get("external_calls")
        if (
            external_calls_hash is None
            or not paths.external_calls.exists()
            or _sha256_file(paths.external_calls) != external_calls_hash
        ):
            raise ProjectConflict("external call ledger drifted")
        return paths

    root.mkdir(parents=True, exist_ok=True)
    paths.catalog_dir.mkdir(exist_ok=True)
    paths.generation_dir.mkdir(exist_ok=True)
    paths.render_dir.mkdir(exist_ok=True)
    _atomic_write(paths.brief, brief_payload)
    external_calls_payload = _canonical_bytes([])
    _atomic_write(paths.external_calls, external_calls_payload)
    state = ProjectState(
        project_id=project_id,
        status="pending",
        current_stage="initialized",
        artifact_paths=_artifact_paths(paths, "0.1.0"),
        completed_artifact_hashes={
            "brief": brief_hash,
            "external_calls": _sha256_bytes(external_calls_payload),
        },
    )
    _write_state(paths, state)
    return paths


def create_visual_project(
    run_root: Path,
    project_id: str,
    brief: RawCreativeBrief,
) -> ProjectPaths:
    """Create or reopen a V0.2 visual project with an immutable raw brief."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", project_id):
        raise ValueError("project_id must be a simple filesystem-safe identifier")
    root = run_root.resolve() / project_id
    paths = _paths(root)
    brief_payload = _canonical_bytes(brief.model_dump(mode="json"))
    brief_hash = _sha256_bytes(brief_payload)

    if paths.brief.exists() or paths.project_state.exists():
        if not paths.brief.exists() or not paths.project_state.exists():
            raise ProjectConflict("existing project is missing required root evidence")
        if _sha256_file(paths.brief) != brief_hash:
            raise ProjectConflict("existing project brief hash does not match")
        state = load_project_state(paths)
        if state.schema_version != "0.2.0":
            raise ProjectConflict("existing project is not a V0.2 visual project")
        if state.project_id != project_id:
            raise ProjectConflict("existing project id does not match state")
        if state.completed_artifact_hashes.get("brief") != brief_hash:
            raise ProjectConflict("state brief hash does not match brief evidence")
        external_calls_hash = state.completed_artifact_hashes.get("external_calls")
        if (
            external_calls_hash is None
            or not paths.external_calls.exists()
            or _sha256_file(paths.external_calls) != external_calls_hash
        ):
            raise ProjectConflict("external call ledger drifted")
        paths.visual_drafts.mkdir(parents=True, exist_ok=True)
        paths.agent_batch_results.mkdir(parents=True, exist_ok=True)
        return paths

    root.mkdir(parents=True, exist_ok=True)
    paths.visual_dir.mkdir(exist_ok=True)
    paths.visual_drafts.mkdir(exist_ok=True)
    paths.agent_batch_results.mkdir(parents=True, exist_ok=True)
    _atomic_write(paths.brief, brief_payload)
    external_calls_payload = _canonical_bytes([])
    _atomic_write(paths.external_calls, external_calls_payload)
    state = VisualProjectState(
        project_id=project_id,
        status="pending",
        current_stage="initialized",
        artifact_paths=_artifact_paths(paths, "0.2.0"),
        completed_artifact_hashes={
            "brief": brief_hash,
            "external_calls": _sha256_bytes(external_calls_payload),
        },
    )
    _write_state(paths, state)
    return paths


def open_project(root: Path) -> ProjectPaths:
    """Resolve an existing project without mutating it."""

    paths = _paths(root.resolve())
    if not paths.project_state.is_file() or not paths.brief.is_file():
        raise FileNotFoundError("project_state.json and brief.json are required")
    load_project_state(paths)
    return paths


def record_project_inputs(
    paths: ProjectPaths,
    inputs: Mapping[str, Path],
) -> str:
    """Record immutable hashes for every local input used by an orchestration run."""

    records: dict[str, dict[str, str]] = {}
    for name, source in sorted(inputs.items()):
        resolved = source.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        records[name] = {
            "path": str(resolved),
            "sha256": _sha256_file(resolved),
        }
    state = load_project_state(paths)
    payload = _canonical_bytes(
        {"schema_version": state.schema_version, "inputs": records}
    )
    payload_hash = _sha256_bytes(payload)

    recorded_hash = state.completed_artifact_hashes.get("input_manifest")
    if recorded_hash is not None:
        if (
            not paths.input_manifest.exists()
            or _sha256_file(paths.input_manifest) != recorded_hash
            or recorded_hash != payload_hash
        ):
            raise ProjectConflict("existing project input manifest does not match")
        return recorded_hash

    _atomic_write(paths.input_manifest, payload)
    state.completed_artifact_hashes["input_manifest"] = payload_hash
    _write_state(paths, state)
    return payload_hash


def record_stage_artifact(
    paths: ProjectPaths,
    stage: str,
    value: BaseModel | dict[str, Any] | list[Any] | Path,
) -> str:
    """Atomically record a stage result without overwriting prior evidence."""

    artifact_path = paths.artifact_for(stage)
    json_value = _json_value(value)
    state = load_project_state(paths)
    json_value = _validated_stage_value(stage, json_value, state.schema_version)
    payload = _canonical_bytes(json_value)
    payload_hash = _sha256_bytes(payload)
    recorded_hash = state.completed_artifact_hashes.get(stage)
    if recorded_hash is not None:
        if (
            not artifact_path.exists()
            or _sha256_file(artifact_path) != recorded_hash
            or recorded_hash != payload_hash
        ):
            raise ProjectConflict(f"completed artifact already differs: {stage}")
        return recorded_hash
    if artifact_path.exists():
        raise ProjectConflict(f"untracked artifact already exists: {stage}")
    _atomic_write(artifact_path, payload)
    state.completed_artifact_hashes[stage] = payload_hash
    state.current_stage = stage
    result_status = json_value.get("status") if isinstance(json_value, dict) else None
    state.status = result_status if result_status in {"completed", "failed", "blocked", "partial"} else "completed"
    if isinstance(state, VisualProjectState) and stage == "director_review":
        state.completion_mode = json_value["mode"]
    _write_state(paths, state)
    return payload_hash


def record_visual_stage_checked(paths: ProjectPaths, stage: str, artifact: Path) -> str:
    """Publish one checked V0.2 draft only after all predecessors are complete."""

    preflight_visual_stage_checked(paths, stage, artifact)
    return record_stage_artifact(paths, stage, artifact.resolve())


def preflight_visual_stage_checked(
    paths: ProjectPaths,
    stage: str,
    artifact: Path,
    value: BaseModel | dict[str, Any] | list[Any] | Path | None = None,
) -> str:
    """Validate a V0.2 stage publication path and payload without writing it."""

    state = load_project_state(paths)
    if state.schema_version != "0.2.0":
        raise ProjectConflict("record-visual-stage requires a V0.2 visual project")
    if stage not in VISUAL_STAGE_ORDER:
        raise ValueError(f"unknown visual stage: {stage}")
    draft = artifact.resolve()
    canonical = paths.artifact_for(stage).resolve()
    if draft == canonical:
        raise ProjectConflict("canonical artifact cannot be its own draft input")
    if value is None and not draft.is_file():
        raise FileNotFoundError(draft)
    drafts_root = paths.visual_drafts.resolve()
    if not draft.is_relative_to(drafts_root):
        raise ProjectConflict("visual stage draft must be under visual/drafts")
    for predecessor in VISUAL_STAGE_ORDER[: VISUAL_STAGE_ORDER.index(stage)]:
        predecessor_path = paths.artifact_for(predecessor)
        recorded_hash = state.completed_artifact_hashes.get(predecessor)
        if recorded_hash is None or not predecessor_path.is_file():
            raise ProjectConflict(f"predecessor is not recorded: {predecessor}")
        if _sha256_file(predecessor_path) != recorded_hash:
            raise ProjectConflict(f"predecessor artifact hash drifted: {predecessor}")
        try:
            predecessor_value = _validated_stage_value(
                predecessor,
                json.loads(predecessor_path.read_text(encoding="utf-8")),
                "0.2.0",
            )
        except (json.JSONDecodeError, OSError) as exc:
            raise ProjectConflict(f"predecessor artifact is invalid: {predecessor}") from exc
        if predecessor_value.get("status") != "completed":
            raise ProjectConflict(f"predecessor is not completed: {predecessor}")
    if value is None:
        if not draft.is_file():
            raise FileNotFoundError(draft)
        payload_value = json.loads(draft.read_text(encoding="utf-8"))
    else:
        payload_value = _json_value(value)
    payload_value = _validated_stage_value(stage, payload_value, "0.2.0")
    payload = _canonical_bytes(payload_value)
    payload_hash = _sha256_bytes(payload)
    recorded_hash = state.completed_artifact_hashes.get(stage)
    if recorded_hash is not None:
        if (
            not canonical.exists()
            or _sha256_file(canonical) != recorded_hash
            or recorded_hash != payload_hash
        ):
            raise ProjectConflict(f"completed artifact already differs: {stage}")
        return recorded_hash
    if canonical.exists():
        raise ProjectConflict(f"untracked artifact already exists: {stage}")
    return payload_hash


def record_supporting_artifact(
    paths: ProjectPaths,
    artifact: Path,
    value: BaseModel | dict[str, Any] | list[Any] | Path,
    *,
    state_key: str | None = None,
) -> str:
    """Write a project-scoped supporting artifact without bypassing hash checks."""

    destination = artifact.resolve()
    if destination == paths.root.resolve() or not destination.is_relative_to(
        paths.root.resolve()
    ):
        raise ProjectConflict("supporting artifact must stay within the project root")
    if destination.exists() and not destination.is_file():
        raise ProjectConflict("supporting artifact destination must be a file")

    payload = _canonical_bytes(_json_value(value))
    payload_hash = _sha256_bytes(payload)
    if state_key is None:
        if destination.exists():
            if _sha256_file(destination) != payload_hash:
                raise ProjectConflict("supporting artifact already differs")
            return payload_hash
        _atomic_write(destination, payload)
        return payload_hash

    state = load_project_state(paths)
    recorded_hash = state.completed_artifact_hashes.get(state_key)
    if recorded_hash is not None:
        if not destination.exists() or _sha256_file(destination) != recorded_hash:
            raise ProjectConflict(f"supporting artifact hash drifted: {state_key}")
        if recorded_hash == payload_hash:
            return recorded_hash
    elif destination.exists() and _sha256_file(destination) != payload_hash:
        raise ProjectConflict("untracked supporting artifact already differs")

    _atomic_write(destination, payload)
    state.completed_artifact_hashes[state_key] = payload_hash
    _write_state(paths, state)
    return payload_hash


def advance_project(
    paths: ProjectPaths,
    target_stage: str,
    adapters: Mapping[str, StageAdapter],
) -> ProjectStateModel:
    """Advance through local stages, verifying completed artifacts before skipping."""

    state = load_project_state(paths)
    stage_order = STAGE_GRAPHS[state.schema_version]
    if target_stage not in stage_order:
        raise ValueError(f"unknown target stage: {target_stage}")
    target_index = stage_order.index(target_stage)

    for stage in stage_order[: target_index + 1]:
        artifact_path = paths.artifact_for(stage)
        recorded_hash = state.completed_artifact_hashes.get(stage)
        if recorded_hash is not None:
            if not artifact_path.exists() or _sha256_file(artifact_path) != recorded_hash:
                raise ProjectConflict(f"completed artifact drifted: {stage}")
            value = json.loads(artifact_path.read_text(encoding="utf-8"))
            _validated_stage_value(stage, value, state.schema_version)
            if value.get("status") in {"blocked", "failed"}:
                state.current_stage = stage
                state.status = value["status"]
                _write_state(paths, state)
                return state
            continue

        adapter = adapters.get(stage)
        if adapter is None:
            raise ValueError(f"missing adapter for stage: {stage}")
        value = _json_value(adapter(paths))
        value = _validated_stage_value(stage, value, state.schema_version)
        payload = _canonical_bytes(value)
        _atomic_write(artifact_path, payload)
        state.completed_artifact_hashes[stage] = _sha256_bytes(payload)
        state.current_stage = stage
        result_status = value.get("status")
        state.status = (
            result_status
            if result_status in {"blocked", "failed"}
            else "completed" if stage == target_stage else "partial"
        )
        if isinstance(state, VisualProjectState) and stage == "director_review":
            state.completion_mode = value["mode"]
        _write_state(paths, state)
        if result_status in {"blocked", "failed"}:
            return state

    state.current_stage = target_stage
    state.status = "completed"
    _write_state(paths, state)
    return state
