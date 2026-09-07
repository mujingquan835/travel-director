"""Create an independent music version without altering parent evidence."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from director.audio_import import load_music_evidence
from director.creative_direction import _context, load_creative
from director.project import (
    ProjectConflict, ProjectPaths, VISUAL_STAGE_ORDER, _paths, _sha256_file,
    _write_state, load_project_state, open_project, record_supporting_artifact,
)
from director.skill_summary import build_skill_run_summary


def create_music_version(parent: ProjectPaths, source: Path) -> ProjectPaths:
    """Copy local evidence once; content-addressed destination makes retries stable.

    Scanner outputs and immutable observations are copied byte-for-byte, never
    recomputed. Absolute provenance references continue to identify their sources.
    Frozen audio and any downstream editing outputs are not copied.
    """
    evidence = load_music_evidence(parent)
    if evidence is None:
        raise ProjectConflict("--new-music-version requires a frozen parent project")
    asset, _ = evidence
    digest = _sha256_file(source)
    if digest == asset.source_sha256:
        raise ProjectConflict("new music must differ from the parent; use --music to resume")
    _context(parent)
    state = load_project_state(parent)
    for stage in VISUAL_STAGE_ORDER:
        if stage in state.completed_artifact_hashes:
            if _sha256_file(parent.artifact_for(stage)) != state.completed_artifact_hashes[stage]:
                raise ProjectConflict(f"completed artifact drifted: {stage}")
    if load_creative(parent, validate_sources=False) is None:
        build_skill_run_summary(parent.root)  # verify the legacy contract read-only
    parent_hash = _sha256_file(parent.project_state)
    target = parent.root.with_name(f"{parent.root.name}-music-{digest[:16]}")
    linkage = {
        "schema_version": "1.0.0", "parent_project": str(parent.root.resolve()),
        "parent_state_sha256": parent_hash,
        "parent_music_sha256": asset.source_sha256, "selected_music_sha256": digest,
    }
    if target.exists():
        child = open_project(target)
        record = target / "music_version.json"
        expected = load_project_state(child).completed_artifact_hashes.get("music_version")
        if (not record.is_file() or _sha256_file(record) != expected
                or json.loads(record.read_text()) != linkage):
            raise ProjectConflict("music version destination has a different lineage")
        _context(child)
        child_state = load_project_state(child)
        for stage in VISUAL_STAGE_ORDER:
            if stage in child_state.completed_artifact_hashes:
                if _sha256_file(child.artifact_for(stage)) != child_state.completed_artifact_hashes[stage]:
                    raise ProjectConflict(f"completed artifact drifted: {stage}")
        if load_creative(child, validate_sources=False) is None:
            build_skill_run_summary(child.root)
        return child
    excluded = {"generation", "music_structure.json", "timeline_slots.json",
                "clip_placements.json", "sfx_plan.json", "render", "music_version.json", "delivery"}
    for path in parent.root.rglob('*'):
        if path.is_symlink():
            raise ProjectConflict("music version evidence must not contain symbolic links")
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        shutil.copytree(parent.root, temporary, dirs_exist_ok=True,
                        ignore=lambda directory, names: excluded.intersection(names)
                        if Path(directory) == parent.root else set())
        if _sha256_file(parent.project_state) != parent_hash:
            raise ProjectConflict("parent changed while creating music version")
        child = _paths(temporary)
        child_state = load_project_state(child)
        child_state.project_id = target.name
        removed = {"music_asset", "music_structure", "music_version", "timeline",
                   "clip_placements", "sfx_plan", "render", "generation", "timeline_delivery", "timeline_delivery_receipt"}
        for key in removed:
            child_state.completed_artifact_hashes.pop(key, None)
            child_state.artifact_paths.pop(key, None)
        _write_state(child, child_state)
        record_supporting_artifact(child, temporary / "music_version.json", linkage,
                                   state_key="music_version")
        _context(child)
        load_creative(child, validate_sources=False)
        # Never merge into or replace an existing project directory.
        if target.exists():
            raise ProjectConflict("music version destination appeared during copy; retry")
        os.rename(temporary, target)
    except BaseException:
        # Only remove the uniquely-created private staging directory.
        shutil.rmtree(temporary)
        raise
    return open_project(target)
