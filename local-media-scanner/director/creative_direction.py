"""Versioned, evidence-bound creative plans authored by the invoking session."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field

from director.creative_schema import (
    CreativeDirection,
    load_reference_library,
    reference_library_sha256,
    validate_creative_direction,
)
from director.project import (
    ProjectConflict, ProjectPaths, VISUAL_STAGE_ORDER, _canonical_bytes,
    _sha256_file, load_project_state, record_supporting_artifact,
)
from director.visual_schema import (
    BriefConfirmation, ClipObservationBatch, DirectorTreatment, ProjectCoverage,
    VisualStrictModel, validate_visual_stage_artifact,
)


class CreativeSummary(VisualStrictModel):
    schema_version: str = "1.0.0"
    project_mode: str
    logline: str
    material_count: int
    material_gaps: list[str]
    target_duration_seconds: float
    location: str
    orientation: str
    selected_references: list[dict]
    sections: list[dict]
    music_brief: str
    music_prompts: list[str]
    artifact_paths: dict[str, str]
    external_call_count: int = Field(default=0, ge=0, le=0)


def _context(paths: ProjectPaths):
    from director.skill_summary import _external_call_payload
    state = load_project_state(paths)
    if _external_call_payload(paths, state):
        raise ProjectConflict("external call ledger must be empty for local-only creative direction")
    if _sha256_file(paths.brief) != state.completed_artifact_hashes.get('brief'):
        raise ProjectConflict('creative source artifact missing or drifted: brief')
    artifacts = {}
    hashes = {}
    stages = VISUAL_STAGE_ORDER[:VISUAL_STAGE_ORDER.index("director_review") + 1]
    for stage in stages:
        path = paths.artifact_for(stage)
        expected = state.completed_artifact_hashes.get(stage)
        if not expected or not path.is_file() or _sha256_file(path) != expected:
            raise ProjectConflict(f"creative source artifact missing or drifted: {stage}")
        artifacts[stage] = validate_visual_stage_artifact(stage, json.loads(path.read_text()))
        hashes[stage] = expected
    hashes["reference_library"] = reference_library_sha256()
    return hashes, artifacts


def _validate(paths: ProjectPaths, payload: dict) -> CreativeDirection:
    hashes, artifacts = _context(paths)
    observations = ClipObservationBatch.model_validate(artifacts["clip_observations"])
    return validate_creative_direction(
        payload, source_hashes=hashes,
        brief=BriefConfirmation.model_validate(artifacts["brief_confirmation"]),
        treatment=DirectorTreatment.model_validate(artifacts["director_treatment"]),
        coverage=ProjectCoverage.model_validate(artifacts["project_coverage"]),
        material_ids={item.material.material_id for item in observations.items},
    )


def creative_request(paths: ProjectPaths) -> tuple[dict, Path]:
    hashes, artifacts = _context(paths)
    digest = hashlib.sha256(_canonical_bytes(hashes)).hexdigest()
    destination = paths.root / "creative" / "requests" / f"{digest}.json"
    request = {
        "schema_version": "1.0.0", "kind": "draft_creative_direction",
        "source_hashes": hashes,
        "brief": artifacts["brief_confirmation"],
        "reference_library": load_reference_library(resolve_paths=True),
        "artifact_paths": {
            key: str(paths.artifact_for(key).resolve()) for key in artifacts
        },
        "response_path": str((paths.root / "creative" / "responses" / f"{digest}.json").resolve()),
        "response_schema": CreativeDirection.model_json_schema(),
        "instructions": [
            "Use current user instructions before default references. Do not request routine approval.",
            "Author the reference selection, AV section plan, music brief and three prompts in that order.",
            "Unknown reference sound is not a heard fact; SFX and music ideas are creative proposals.",
            "Submit through run --creative-response, never overwrite visual stage artifacts.",
        ],
        "external_call_count": 0,
    }
    # Relocating a copied project must not overwrite its earlier request.
    request_id = hashlib.sha256(_canonical_bytes(request)).hexdigest()
    destination = destination.with_name(f"{request_id}.json")
    record_supporting_artifact(paths, destination, request, state_key=f"creative_request:{request_id}")
    return request, destination


def _read_checked(paths: ProjectPaths, path: Path, key: str) -> dict:
    expected = load_project_state(paths).completed_artifact_hashes.get(key)
    if not expected or not path.is_file() or _sha256_file(path) != expected:
        raise ProjectConflict(f"creative artifact missing or drifted: {key}")
    return json.loads(path.read_text())


def load_creative(paths: ProjectPaths, *, validate_sources: bool = True) -> tuple[CreativeDirection, CreativeSummary, Path] | None:
    index_path = paths.root / "creative" / "current.json"
    recorded = load_project_state(paths).completed_artifact_hashes.get("creative_current")
    if recorded is None:
        if index_path.exists():
            raise ProjectConflict("untracked creative index exists")
        return None
    index = _read_checked(paths, index_path, "creative_current")
    revision = index.get("revision_id", "")
    if len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
        raise ProjectConflict("invalid creative revision id")
    root = paths.root / "creative" / "revisions" / revision
    payload = _read_checked(paths, root / "direction.json", f"creative_direction:{revision}")
    if hashlib.sha256(_canonical_bytes(payload)).hexdigest() != revision:
        raise ProjectConflict("creative revision does not match its content")
    direction = _validate(paths, payload) if validate_sources else CreativeDirection.model_validate(payload)
    summary = CreativeSummary.model_validate(
        _read_checked(paths, root / "summary.json", f"creative_summary:{revision}")
    )
    summary.artifact_paths = {
        key: str((paths.root / relative).resolve())
        for key, relative in summary.artifact_paths.items()
    }
    return direction, summary, root / "summary.json"


def import_creative(paths: ProjectPaths, response: Path) -> tuple[CreativeDirection, CreativeSummary, Path]:
    payload = json.loads(response.read_text(encoding="utf-8"))
    direction = _validate(paths, payload)
    canonical = direction.model_dump(mode="json")
    revision = hashlib.sha256(_canonical_bytes(canonical)).hexdigest()
    # The new submission was checked against current sources above. Old revisions
    # remain integrity checked, but need not use today's reference-library version.
    existing = load_creative(paths, validate_sources=False)
    if existing is not None and existing[0] == direction:
        return existing
    if paths.generated_music.exists() or paths.music_structure.exists():
        raise ProjectConflict("music is already frozen; create a new version before changing its creative plan")
    root = paths.root / "creative" / "revisions" / revision
    _, artifacts = _context(paths)
    treatment = DirectorTreatment.model_validate(artifacts["director_treatment"])
    relative_paths = {
        stage: paths.artifact_for(stage).relative_to(paths.root).as_posix()
        for stage in artifacts
    }
    relative_paths.update({
        "creative_direction": (root / "direction.json").relative_to(paths.root).as_posix(),
        "creative_summary": (root / "summary.json").relative_to(paths.root).as_posix(),
    })
    summary = CreativeSummary(
        project_mode="assisted" if treatment.review_required else "automatic",
        logline=treatment.logline,
        material_count=len(artifacts["clip_observations"]["items"]),
        material_gaps=treatment.coverage_gaps,
        target_duration_seconds=direction.target_duration_seconds,
        location=direction.location, orientation=direction.orientation,
        selected_references=[row.model_dump(mode="json") for row in direction.selected_references],
        sections=[row.model_dump(mode="json") for row in direction.sections],
        music_brief=direction.music_brief,
        music_prompts=[row.generation_prompt for row in direction.music_prompts],
        artifact_paths=relative_paths,
    )
    record_supporting_artifact(paths, root / "direction.json", canonical,
                              state_key=f"creative_direction:{revision}")
    record_supporting_artifact(paths, root / "summary.json", summary,
                              state_key=f"creative_summary:{revision}")
    record_supporting_artifact(paths, paths.root / "creative" / "current.json",
                              {"schema_version": "1.0.0", "revision_id": revision},
                              state_key="creative_current")
    result = load_creative(paths)
    assert result is not None
    return result


def load_current_creative(paths: ProjectPaths):
    """A stale, intact revision can request an update; corruption still blocks."""
    existing = load_creative(paths, validate_sources=False)
    if existing is None:
        return None
    hashes, _ = _context(paths)
    if existing[0].source_hashes != hashes:
        return None
    return load_creative(paths)
