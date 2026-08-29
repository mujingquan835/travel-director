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

from pydantic import BaseModel

from director.schema import ProjectState, UserCreativeBrief


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


def _validate_schema_version(value: Any) -> None:
    records = value if isinstance(value, list) else [value]
    if not records:
        return
    if not all(
        isinstance(record, dict) and record.get("schema_version") == "0.1.0"
        for record in records
    ):
        raise ProjectConflict("stage artifact does not use schema_version 0.1.0")


def _artifact_paths(paths: ProjectPaths) -> dict[str, str]:
    return {
        stage: str(paths.artifact_for(stage).relative_to(paths.root))
        for stage in LOCAL_STAGE_ORDER
    } | {
        "brief": "brief.json",
        "input_manifest": "input_manifest.json",
        "external_calls": "external_calls.json",
        "generation": "generation/music_asset.json",
        "render": "render/render_result.json",
    }


def _write_state(paths: ProjectPaths, state: ProjectState) -> None:
    _atomic_write(paths.project_state, _canonical_bytes(state.model_dump(mode="json")))


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
        state = ProjectState.model_validate_json(
            paths.project_state.read_text(encoding="utf-8")
        )
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
        artifact_paths=_artifact_paths(paths),
        completed_artifact_hashes={
            "brief": brief_hash,
            "external_calls": _sha256_bytes(external_calls_payload),
        },
    )
    _write_state(paths, state)
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
    payload = _canonical_bytes(
        {"schema_version": "0.1.0", "inputs": records}
    )
    payload_hash = _sha256_bytes(payload)

    state = ProjectState.model_validate_json(
        paths.project_state.read_text(encoding="utf-8")
    )
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


def advance_project(
    paths: ProjectPaths,
    target_stage: str,
    adapters: Mapping[str, StageAdapter],
) -> ProjectState:
    """Advance through local stages, verifying completed artifacts before skipping."""

    if target_stage not in LOCAL_STAGE_ORDER:
        raise ValueError(f"unknown target stage: {target_stage}")
    state = ProjectState.model_validate_json(
        paths.project_state.read_text(encoding="utf-8")
    )
    target_index = LOCAL_STAGE_ORDER.index(target_stage)

    for stage in LOCAL_STAGE_ORDER[: target_index + 1]:
        artifact_path = paths.artifact_for(stage)
        recorded_hash = state.completed_artifact_hashes.get(stage)
        if recorded_hash is not None:
            if not artifact_path.exists() or _sha256_file(artifact_path) != recorded_hash:
                raise ProjectConflict(f"completed artifact drifted: {stage}")
            value = json.loads(artifact_path.read_text(encoding="utf-8"))
            _validate_schema_version(value)
            continue

        adapter = adapters.get(stage)
        if adapter is None:
            raise ValueError(f"missing adapter for stage: {stage}")
        value = _json_value(adapter(paths))
        _validate_schema_version(value)
        payload = _canonical_bytes(value)
        _atomic_write(artifact_path, payload)
        state.completed_artifact_hashes[stage] = _sha256_bytes(payload)
        state.current_stage = stage
        state.status = "completed" if stage == target_stage else "partial"
        _write_state(paths, state)

    state.current_stage = target_stage
    state.status = "completed"
    _write_state(paths, state)
    return state
