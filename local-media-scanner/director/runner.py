"""Idempotent facade over the existing visual Director stage graph."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field

from director.agent_batches import (
    AgentBatchManifest,
    MaterialFrameMap,
    build_agent_batch_manifest,
)
from director.agent_observations import (
    AgentBatchResult,
    merge_agent_batch_results,
    validate_agent_batch_result,
    write_agent_batch_checkpoint,
)
from director.brief_interpreter import (
    DeterministicBriefInterpreter,
    render_brief_review,
    validate_brief_confirmation,
)
from director.director_treatment import build_director_treatment
from director.intent_matcher import build_intent_decisions, build_project_coverage
from director.project import (
    ProjectConflict,
    ProjectPaths,
    VISUAL_STAGE_ORDER,
    _atomic_write,
    _canonical_bytes,
    _sha256_file,
    create_visual_project,
    load_project_state,
    open_project,
    record_project_inputs,
    record_supporting_artifact,
    record_visual_stage_checked,
)
from director.scanner_bridge import (
    build_material_frame_map,
    build_scanner_observations_from_files,
)
from director.skill_summary import build_skill_run_summary, write_skill_run_summary
from director.skill_workflow import PreparedVisualReview, ReviewQuestion
from director.visual_review import (
    apply_visual_confirmation,
    build_automatic_director_review,
    prepare_visual_review,
    validate_visual_confirmation_against_observations,
)
from director.visual_schema import (
    BRIEF_FIELD_NAMES,
    BriefConfirmation,
    ClipObservationBatch,
    DirectorReview,
    DirectorTreatment,
    IntentDecisionBatch,
    MusicGenerationPromptRecommendationBatch,
    NormalizedBriefFields,
    NormalizedIntentDraft,
    ProjectCoverage,
    RawCreativeBrief,
    VisualProjectState,
    VisualReviewArtifact,
    VisualStrictModel,
)
from scanner.cache import create_run_dir
from scanner.config import SamplingConfig, ScanConfig
from scanner.metadata import build_manifest, discover_videos
from scanner.pipeline import ScanContext, scan_manifest
from scanner.schema import ScannerResult, TestManifest


RunState = Literal[
    "needs_visual_observation",
    "needs_user_confirmation",
    "needs_creative_direction",
    "waiting_for_music",
    "waiting_for_timeline",
    "completed",
    "blocked",
]


class RunAction(VisualStrictModel):
    kind: Literal[
        "observe_contact_sheets",
        "confirm_brief",
        "confirm_visual_fields",
        "draft_creative_direction",
        "provide_music",
        "read_music_analysis",
        "read_summary",
        "resolve_blocker",
    ]
    message: str = Field(min_length=1)
    batch_id: str | None = None
    contact_sheet_paths: list[str] = Field(default_factory=list)
    result_path: str | None = None
    required_fields: list[str] = Field(default_factory=list)
    affected_material_count: int = Field(default=0, ge=0)
    review_channel: Literal["chat", "local_page"] | None = None
    draft_path: str | None = None
    confirmation_path: str | None = None
    response_path: str | None = None
    page_path: str | None = None
    review_questions: list[ReviewQuestion] = Field(default_factory=list)


class BriefRunResponse(VisualStrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    kind: Literal["brief"] = "brief"
    status: Literal["answered", "declined"] = "answered"
    answers: dict[str, Any] = Field(default_factory=dict)


class VisualFieldRunResponse(VisualStrictModel):
    material_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    field: str = Field(min_length=1)
    value: Any = None
    confirmed_status: Literal["confirmed", "abstained"] = "confirmed"
    reviewer_note: str = ""


class VisualRunResponse(VisualStrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    kind: Literal["visual"] = "visual"
    status: Literal["answered", "declined"] = "answered"
    reviewer: str = Field(default="user", min_length=1)
    answers: list[VisualFieldRunResponse] = Field(default_factory=list)


class DirectorRunResult(VisualStrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    status: RunState
    project_path: str
    current_stage: str
    message: str = Field(min_length=1)
    actions: list[RunAction] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    recommended_duration_seconds: int | None = Field(default=None, gt=0)
    music_prompts: list[str] = Field(default_factory=list, max_length=3)
    external_call_count: Literal[0] = 0


class DirectorStatusResult(VisualStrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    project_path: str
    project_schema_version: str
    project_status: str
    current_stage: str
    completed_stages: list[str]
    run_state: Literal[
        "ready",
        "needs_visual_observation",
        "needs_user_confirmation",
        "needs_creative_direction",
        "waiting_for_music",
        "waiting_for_timeline",
        "completed",
        "blocked",
    ]
    external_call_count: Literal[0] = 0


@dataclass(frozen=True)
class PreparedScannerEvidence:
    observations: ClipObservationBatch
    frame_map: MaterialFrameMap
    batch_manifest: AgentBatchManifest
    scanner_manifest_path: Path
    scanner_result_path: Path


TModel = TypeVar("TModel", bound=BaseModel)


class RunMediaIdentity(VisualStrictModel):
    relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    ctime_ns: int = Field(ge=0)


class RunMediaFingerprint(RunMediaIdentity):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RunContract(VisualStrictModel):
    schema_version: Literal["0.3.0"] = "0.3.0"
    input_root: str = Field(min_length=1)
    brief_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media: list[RunMediaFingerprint] = Field(min_length=1)
    models_enabled: Literal[False] = False
    external_services_enabled: Literal[False] = False


class RunMediaFingerprintV2(VisualStrictModel):
    relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RunContractV2(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    input_root: str = Field(min_length=1)
    brief_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media: list[RunMediaFingerprintV2] = Field(min_length=1)
    models_enabled: Literal[False] = False
    external_services_enabled: Literal[False] = False


def _safe_project_id(input_dir: Path, raw_description: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", input_dir.name).strip("-._")
    slug = slug[:40] or "travel-project"
    identity = hashlib.sha256(
        f"{input_dir.resolve()}\0{raw_description}".encode("utf-8")
    ).hexdigest()[:10]
    return f"{slug}-{identity}"


def _resolve_project(
    input_dir: Path,
    raw_brief: RawCreativeBrief,
    *,
    project: Path | None,
    run_root: Path,
) -> tuple[ProjectPaths, bool]:
    resolved = (
        project.resolve()
        if project is not None
        else run_root.resolve()
        / _safe_project_id(input_dir, raw_brief.raw_description)
    )
    if (resolved / "project_state.json").exists() or (resolved / "brief.json").exists():
        paths = open_project(resolved)
        state = load_project_state(paths)
        if not isinstance(state, VisualProjectState):
            raise ProjectConflict("existing project is not a visual Director project")
        recorded_brief_hash = state.completed_artifact_hashes.get("brief")
        if (
            recorded_brief_hash is None
            or not paths.brief.is_file()
            or _sha256_file(paths.brief) != recorded_brief_hash
        ):
            raise ProjectConflict("existing project brief evidence drifted")
        recorded_brief = RawCreativeBrief.model_validate_json(
            paths.brief.read_text(encoding="utf-8")
        )
        if recorded_brief != raw_brief:
            raise ProjectConflict("existing project brief hash does not match")
        return paths, False
    return (
        create_visual_project(
            resolved.parent,
            resolved.name,
            raw_brief,
        ),
        True,
    )


def _media_inventory(input_dir: Path) -> list[RunMediaIdentity]:
    videos = discover_videos(input_dir)
    if not videos:
        raise ValueError("input directory contains no supported video files")
    root = input_dir.resolve()
    inventory: list[RunMediaIdentity] = []
    for path in videos:
        stat = path.stat()
        inventory.append(
            RunMediaIdentity(
                relative_path=path.resolve().relative_to(root).as_posix(),
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                ctime_ns=stat.st_ctime_ns,
            )
        )
    return inventory


def _validate_legacy_input(
    paths: ProjectPaths,
    input_dir: Path,
    media: list[RunMediaIdentity],
) -> dict[str, str]:
    state = load_project_state(paths)
    recorded_hash = state.completed_artifact_hashes.get("clip_observations")
    if recorded_hash is None:
        raise ProjectConflict(
            "legacy project has no complete source fingerprints for this input"
        )
    if (
        not paths.clip_observations.is_file()
        or _sha256_file(paths.clip_observations) != recorded_hash
    ):
        raise ProjectConflict("completed artifact drifted: clip_observations")
    observations = ClipObservationBatch.model_validate_json(
        paths.clip_observations.read_text(encoding="utf-8")
    )
    actual = {
        row.relative_path: (row.size_bytes, row.mtime_ns)
        for row in media
    }
    expected = {
        item.material.relative_path: (
            item.material.size_bytes,
            item.material.mtime_ns,
        )
        for item in observations.items
    }
    if actual != expected:
        raise ProjectConflict(
            "legacy project input membership does not match the requested input; "
            "a benchmark subset cannot represent a larger source directory"
        )
    root = input_dir.resolve()
    source_hashes: dict[str, str] = {}
    for item in observations.items:
        source = (root / item.material.relative_path).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ProjectConflict("legacy project input source fingerprint does not match")
        source_sha256 = _sha256_file(source)
        if source_sha256 != item.material.source_sha256:
            raise ProjectConflict("legacy project input source fingerprint does not match")
        source_hashes[item.material.relative_path] = source_sha256
    return source_hashes


def _record_run_contract(
    paths: ProjectPaths,
    input_dir: Path,
    media: list[RunMediaIdentity],
    *,
    new_project: bool,
) -> None:
    input_root = str(input_dir.resolve())
    brief_sha256 = _sha256_file(paths.brief)
    contract_path = paths.visual_dir / "run_contract.json"
    state = load_project_state(paths)
    recorded_hash = state.completed_artifact_hashes.get("run_contract")
    if recorded_hash is not None:
        if not contract_path.is_file() or _sha256_file(contract_path) != recorded_hash:
            raise ProjectConflict("supporting artifact hash drifted: run_contract")
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") == "0.3.0":
            recorded = RunContract.model_validate(payload)
            recorded_identity = [
                RunMediaIdentity.model_validate(
                    item.model_dump(mode="json", exclude={"source_sha256"})
                )
                for item in recorded.media
            ]
            if (
                recorded.input_root != input_root
                or recorded.brief_sha256 != brief_sha256
                or recorded_identity != media
            ):
                raise ProjectConflict(
                    "run input contract does not match the requested input"
                )
            return
        if payload.get("schema_version") == "0.2.0":
            recorded = RunContractV2.model_validate(payload)
            current_v2_identity = [
                (item.relative_path, item.size_bytes, item.mtime_ns)
                for item in media
            ]
            recorded_v2_identity = [
                (item.relative_path, item.size_bytes, item.mtime_ns)
                for item in recorded.media
            ]
            if (
                recorded.input_root != input_root
                or recorded.brief_sha256 != brief_sha256
                or recorded_v2_identity != current_v2_identity
            ):
                raise ProjectConflict("run input contract does not match the requested input")
            return
        _validate_legacy_input(paths, input_dir, media)
        if Path(str(payload.get("input_root", ""))).resolve() != input_dir.resolve():
            raise ProjectConflict("legacy run input root does not match the requested input")
        return

    verified_source_hashes = (
        {} if new_project else _validate_legacy_input(paths, input_dir, media)
    )
    root = input_dir.resolve()
    contract = RunContract(
        input_root=input_root,
        brief_sha256=brief_sha256,
        media=[
            RunMediaFingerprint(
                **item.model_dump(mode="json"),
                source_sha256=(
                    verified_source_hashes.get(item.relative_path)
                    or _sha256_file(root / item.relative_path)
                ),
            )
            for item in media
        ],
    )
    record_supporting_artifact(
        paths,
        contract_path,
        contract,
        state_key="run_contract",
    )


def _load_supporting(
    paths: ProjectPaths,
    destination: Path,
    state_key: str,
    model: type[TModel],
) -> TModel | None:
    state = load_project_state(paths)
    recorded_hash = state.completed_artifact_hashes.get(state_key)
    if recorded_hash is None:
        return None
    if not destination.is_file() or _sha256_file(destination) != recorded_hash:
        raise ProjectConflict(f"supporting artifact hash drifted: {state_key}")
    return model.model_validate_json(destination.read_text(encoding="utf-8"))


def _record_supporting_model(
    paths: ProjectPaths,
    destination: Path,
    state_key: str,
    value: TModel,
) -> TModel:
    record_supporting_artifact(
        paths,
        destination,
        value,
        state_key=state_key,
    )
    return value


def _prepare_local_scanner(
    paths: ProjectPaths, input_dir: Path
) -> PreparedScannerEvidence:
    scanner_root = paths.visual_dir / "scanner"
    manifest_path = scanner_root / "input_manifest.json"
    scanner_manifest = _load_supporting(
        paths, manifest_path, "scanner_manifest", TestManifest
    )
    if scanner_manifest is None:
        videos = discover_videos(input_dir)
        if not videos:
            raise ValueError("input directory contains no supported video files")
        scanner_manifest = _record_supporting_model(
            paths,
            manifest_path,
            "scanner_manifest",
            build_manifest(input_dir, videos),
        )
    if Path(scanner_manifest.input_root).resolve() != input_dir.resolve():
        raise ProjectConflict("scanner manifest input root does not match run input")

    runs_dir = scanner_root / "runs"
    scanner_run_dir = runs_dir / "scanner-v1"
    scanner_result_path = scanner_run_dir / "scanner_result.json"
    scanner_result = _load_supporting(
        paths, scanner_result_path, "scanner_result", ScannerResult
    )
    if scanner_result is None:
        config = ScanConfig(
            device="auto",
            sampling=SamplingConfig(profile="adaptive5"),
        )
        run_paths = create_run_dir(
            runs_dir,
            "scanner-v1",
            config,
            resume=scanner_run_dir.exists(),
        )
        scanner_result = scan_manifest(
            scanner_manifest,
            ScanContext(
                input_root=Path(scanner_manifest.input_root),
                run_dir=run_paths.root,
                config=config,
                detector=None,
                vision_encoder=None,
                model_revisions={},
                actual_device="none",
            ),
        )
        scanner_result = _record_supporting_model(
            paths,
            scanner_result_path,
            "scanner_result",
            scanner_result,
        )

    record_project_inputs(
        paths,
        {
            "scanner_manifest": manifest_path,
            "scanner_result": scanner_result_path,
        },
    )

    observations_path = paths.visual_dir / "scanner_only.json"
    observations = _load_supporting(
        paths, observations_path, "scanner_observations", ClipObservationBatch
    )
    if observations is None:
        observations = _record_supporting_model(
            paths,
            observations_path,
            "scanner_observations",
            build_scanner_observations_from_files(
                scanner_result,
                scanner_manifest,
                scanner_result_path,
            ),
        )

    frame_map_path = paths.visual_dir / "material_frame_map.json"
    frame_map = _load_supporting(
        paths, frame_map_path, "material_frame_map", MaterialFrameMap
    )
    if frame_map is None:
        frame_map = _record_supporting_model(
            paths,
            frame_map_path,
            "material_frame_map",
            build_material_frame_map(
                scanner_result,
                observations,
                scanner_run_dir,
            ),
        )

    batch_manifest = _load_supporting(
        paths,
        paths.agent_batch_manifest,
        "agent_batch_manifest",
        AgentBatchManifest,
    )
    if batch_manifest is None:
        batch_manifest = _record_supporting_model(
            paths,
            paths.agent_batch_manifest,
            "agent_batch_manifest",
            build_agent_batch_manifest(
                frame_map,
                paths.agent_batch_manifest.parent,
            ),
        )
    return PreparedScannerEvidence(
        observations=observations,
        frame_map=frame_map,
        batch_manifest=batch_manifest,
        scanner_manifest_path=manifest_path,
        scanner_result_path=scanner_result_path,
    )


def _load_recorded_stage(
    paths: ProjectPaths, stage: str, model: type[TModel]
) -> TModel | None:
    state = load_project_state(paths)
    recorded_hash = state.completed_artifact_hashes.get(stage)
    if recorded_hash is None:
        return None
    artifact = paths.artifact_for(stage)
    if not artifact.is_file() or _sha256_file(artifact) != recorded_hash:
        raise ProjectConflict(f"completed artifact drifted: {stage}")
    return model.model_validate_json(artifact.read_text(encoding="utf-8"))


def _publish_stage(
    paths: ProjectPaths,
    stage: str,
    value: TModel,
    *,
    draft_name: str | None = None,
) -> TModel:
    recorded = _load_recorded_stage(paths, stage, type(value))
    if recorded is not None:
        return recorded
    draft = paths.visual_drafts / (draft_name or f"{stage}.json")
    record_supporting_artifact(paths, draft, value)
    record_visual_stage_checked(paths, stage, draft)
    parsed = _load_recorded_stage(paths, stage, type(value))
    assert parsed is not None
    return parsed


def _pending_agent_actions(
    manifest: AgentBatchManifest,
    scanner_observations: ClipObservationBatch,
) -> tuple[list[RunAction], list[Path]]:
    actions: list[RunAction] = []
    checkpoints: list[Path] = []
    scanner_by_material = {
        item.material.material_id: item for item in scanner_observations.items
    }
    for batch in manifest.batches:
        result_path = Path(batch.result_path).resolve()
        batch_results: list[AgentBatchResult] = []
        if result_path.is_file():
            result = AgentBatchResult.model_validate_json(
                result_path.read_text(encoding="utf-8")
            )
            validate_agent_batch_result(manifest, result)
            write_agent_batch_checkpoint(result, result_path)
            checkpoints.append(result_path)
            batch_results.append(result)
            supplement_dir = result_path.parent / "supplements"
            for supplement_path in sorted(
                supplement_dir.glob(f"{batch.batch_id}-*.json")
            ):
                supplement = AgentBatchResult.model_validate_json(
                    supplement_path.read_text(encoding="utf-8")
                )
                validate_agent_batch_result(manifest, supplement)
                if supplement.batch_id != batch.batch_id:
                    raise ValueError("supplement batch ID does not match its reservation")
                write_agent_batch_checkpoint(supplement, supplement_path)
                checkpoints.append(supplement_path)
                batch_results.append(supplement)
        ready = [item for item in batch.items if item.status == "ready"]
        if not ready:
            continue
        addressed: dict[str, set[str]] = {item.material_id: set() for item in ready}
        for result in batch_results:
            if result.status != "completed":
                continue
            for item in result.items:
                addressed[item.material.material_id].update(
                    assertion.field for assertion in item.assertions
                )
        missing: dict[str, set[str]] = {}
        for packet in ready:
            scanner_item = scanner_by_material[packet.material_id]
            needed = (
                set(scanner_item.unknown_fields)
                | set(scanner_item.review_required_fields)
            ) & set(packet.allowed_fields)
            unresolved = needed - addressed[packet.material_id]
            if unresolved:
                missing[packet.material_id] = unresolved
        if batch_results and not missing:
            continue
        if batch_results:
            supplement_dir = result_path.parent / "supplements"
            supplement_count = len(list(supplement_dir.glob(f"{batch.batch_id}-*.json")))
            target_path = supplement_dir / f"{batch.batch_id}-{supplement_count + 1:03d}.json"
            message = (
                "Supplement only unresolved fields without changing prior assertions, "
                "then save a validated AgentBatchResult to the reserved supplement path."
            )
        else:
            target_path = result_path
            message = (
                "Observe only the reserved contact sheets and save one "
                "validated AgentBatchResult to the reserved result path."
            )
        actions.append(
            RunAction(
                kind="observe_contact_sheets",
                message=message,
                batch_id=batch.batch_id,
                contact_sheet_paths=[
                    item.contact_sheet_path
                    for item in ready
                    if item.contact_sheet_path is not None
                ],
                result_path=str(target_path.resolve()),
                required_fields=sorted(
                    {field for fields in missing.values() for field in fields}
                ),
            )
        )
    return actions, checkpoints


def _write_pending_merged_observations(
    paths: ProjectPaths, value: ClipObservationBatch
) -> Path:
    """Refresh a derived draft only before final observations are published."""

    state = load_project_state(paths)
    if "clip_observations" in state.completed_artifact_hashes:
        raise ProjectConflict("published clip observations cannot be refreshed")
    destination = paths.visual_drafts / "clip_observations.merged.json"
    _atomic_write(destination, _canonical_bytes(value.model_dump(mode="json")))
    return destination


def _brief_confirmation_from_response(
    paths: ProjectPaths,
    draft: NormalizedIntentDraft,
    response_path: Path,
    output_path: Path,
) -> BriefConfirmation:
    response = BriefRunResponse.model_validate_json(
        response_path.read_text(encoding="utf-8")
    )
    if response.status == "declined":
        raise ProjectConflict("required Brief confirmation was declined")

    required = set(draft.review_required_fields)
    provided = set(response.answers)
    missing = sorted(required - provided)
    unexpected = sorted(provided - required)
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        raise ValueError(
            "Brief response fields do not match request: " + "; ".join(details)
        )

    original = draft.normalized_fields.model_dump(mode="json")
    confirmed_payload = dict(original)
    confirmed_payload.update(response.answers)
    confirmed_fields = NormalizedBriefFields.model_validate(confirmed_payload)
    confirmed_json = confirmed_fields.model_dump(mode="json")
    confirmation = BriefConfirmation(
        status="completed",
        draft_sha256=_sha256_file(paths.visual_drafts / "intent_brief.json"),
        normalized_fields=confirmed_fields,
        changed_fields=sorted(
            field
            for field in BRIEF_FIELD_NAMES
            if original[field] != confirmed_json[field]
        ),
        confirmed_at=datetime.now(timezone.utc).isoformat(),
    )
    validate_brief_confirmation(
        confirmation,
        draft,
        _sha256_file(paths.visual_drafts / "intent_brief.json"),
    )
    record_supporting_artifact(paths, output_path, confirmation)
    return confirmation


def _brief_confirmation(
    paths: ProjectPaths,
    draft: NormalizedIntentDraft,
) -> tuple[BriefConfirmation | None, RunAction | None]:
    recorded = _load_recorded_stage(
        paths, "brief_confirmation", BriefConfirmation
    )
    if recorded is not None:
        return recorded, None

    user_confirmation = paths.visual_dir / "review" / "brief_confirmation.json"
    automatic_draft = paths.visual_drafts / "brief_confirmation.json"
    response_path = paths.visual_dir / "review" / "brief_response.json"
    source = user_confirmation if user_confirmation.is_file() else automatic_draft
    if source.is_file():
        confirmation = BriefConfirmation.model_validate_json(
            source.read_text(encoding="utf-8")
        )
        validate_brief_confirmation(
            confirmation,
            draft,
            _sha256_file(paths.visual_drafts / "intent_brief.json"),
        )
        record_supporting_artifact(paths, automatic_draft, confirmation)
        return confirmation, None

    if draft.status == "completed" and not draft.review_required_fields:
        confirmation = BriefConfirmation(
            status="completed",
            draft_sha256=_sha256_file(paths.visual_drafts / "intent_brief.json"),
            normalized_fields=draft.normalized_fields,
            changed_fields=[],
            confirmed_at=datetime.now(timezone.utc).isoformat(),
        )
        record_supporting_artifact(paths, automatic_draft, confirmation)
        return confirmation, None

    if response_path.is_file():
        return (
            _brief_confirmation_from_response(
                paths,
                draft,
                response_path,
                automatic_draft,
            ),
            None,
        )

    user_confirmation.parent.mkdir(parents=True, exist_ok=True)
    page_path: Path | None = None
    channel: Literal["chat", "local_page"] = "chat"
    if len(draft.review_required_fields) > 5:
        channel = "local_page"
        page_path = paths.visual_dir / "review" / "brief_review.html"
        if not page_path.is_file():
            render_brief_review(
                draft,
                page_path,
                draft_sha256=_sha256_file(paths.visual_drafts / "intent_brief.json"),
            )
    return None, RunAction(
        kind="confirm_brief",
        message="Confirm only the missing or conflicting Brief fields.",
        required_fields=list(draft.review_required_fields),
        review_channel=channel,
        draft_path=str((paths.visual_drafts / "intent_brief.json").resolve()),
        confirmation_path=str(user_confirmation.resolve()),
        response_path=(
            str(response_path.resolve()) if channel == "chat" else None
        ),
        page_path=str(page_path.resolve()) if page_path is not None else None,
    )


def _import_brief_page_confirmation(
    paths: ProjectPaths,
    draft: NormalizedIntentDraft,
    response_file: Path,
    destination: Path,
) -> None:
    try:
        confirmation = BriefConfirmation.model_validate_json(
            response_file.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        raise ValueError(
            "response file is not a valid Brief confirmation"
        ) from exc
    validate_brief_confirmation(
        confirmation,
        draft,
        _sha256_file(paths.visual_drafts / "intent_brief.json"),
    )
    record_supporting_artifact(paths, destination, confirmation)


def _visual_confirmation_from_response(
    paths: ProjectPaths,
    merged: ClipObservationBatch,
    prepared: PreparedVisualReview,
    response_path: Path,
    confirmation_path: Path,
) -> "VisualConfirmation":
    from director.evaluation import FieldConfirmation, VisualConfirmation

    response = VisualRunResponse.model_validate_json(
        response_path.read_text(encoding="utf-8")
    )
    if response.status == "declined":
        raise ProjectConflict("required visual confirmation was declined")

    required = {
        (question.material_id, field)
        for question in prepared.route.questions
        for field in question.fields
    }
    provided = [(answer.material_id, answer.field) for answer in response.answers]
    provided_set = set(provided)
    if len(provided) != len(provided_set):
        raise ValueError("visual response contains duplicate material fields")
    missing = sorted(required - provided_set)
    unexpected = sorted(provided_set - required)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing={len(missing)}")
        if unexpected:
            details.append(f"unexpected={len(unexpected)}")
        raise ValueError(
            "visual response fields do not match request: " + "; ".join(details)
        )

    by_material = {item.material.material_id: item for item in merged.items}
    changed_at = datetime.now(timezone.utc).isoformat()
    items = []
    for answer in response.answers:
        observation = by_material[answer.material_id]
        assertions = {
            assertion.field: assertion for assertion in observation.assertions
        }
        original = assertions.get(answer.field)
        items.append(
            FieldConfirmation(
                material_id=answer.material_id,
                field=answer.field,
                original_value=original.value if original is not None else None,
                original_status=(
                    original.status if original is not None else "abstained"
                ),
                confirmed_value=(
                    answer.value
                    if answer.confirmed_status == "confirmed"
                    else None
                ),
                confirmed_status=answer.confirmed_status,
                reviewer_note=answer.reviewer_note,
                changed_at=changed_at,
            )
        )
    merged_path = paths.visual_drafts / "clip_observations.merged.json"
    confirmation = VisualConfirmation(
        source_observations_sha256=_sha256_file(merged_path),
        status="completed",
        reviewer=response.reviewer,
        items=items,
    )
    validate_visual_confirmation_against_observations(
        confirmation,
        merged,
        _sha256_file(merged_path),
    )
    record_supporting_artifact(paths, confirmation_path, confirmation)
    return confirmation


def _import_visual_page_confirmation(
    paths: ProjectPaths,
    merged: ClipObservationBatch,
    response_file: Path,
    destination: Path,
) -> None:
    from director.evaluation import VisualConfirmation

    try:
        confirmation = VisualConfirmation.model_validate_json(
            response_file.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        raise ValueError(
            "response file is not a valid visual confirmation"
        ) from exc
    merged_path = paths.visual_drafts / "clip_observations.merged.json"
    validate_visual_confirmation_against_observations(
        confirmation,
        merged,
        _sha256_file(merged_path),
    )
    record_supporting_artifact(paths, destination, confirmation)


def _visual_confirmation(
    paths: ProjectPaths,
    merged: ClipObservationBatch,
    frame_map: MaterialFrameMap,
) -> tuple[ClipObservationBatch | None, RunAction | None]:
    if merged.status == "completed" and not any(
        item.review_required_fields for item in merged.items
    ):
        return merged, None

    review_dir = paths.visual_dir / "review"
    prepared_path = review_dir / "review_route.json"
    confirmation_path = review_dir / "visual_confirmation.json"
    if confirmation_path.is_file() and prepared_path.is_file():
        prepared = PreparedVisualReview.model_validate_json(
            prepared_path.read_text(encoding="utf-8")
        )
    else:
        prepared = prepare_visual_review(
            merged,
            frame_map,
            review_dir,
            source_observations_sha256=_sha256_file(
                paths.visual_drafts / "clip_observations.merged.json"
            ),
        )
    response_path = review_dir / "visual_response.json"
    if prepared.route.channel == "chat" and response_path.is_file():
        _visual_confirmation_from_response(
            paths,
            merged,
            prepared,
            response_path,
            confirmation_path,
        )
    if not confirmation_path.is_file():
        return None, RunAction(
            kind="confirm_visual_fields",
            message="Confirm only the unresolved visual fields reported by the route.",
            required_fields=sorted(
                {
                    field
                    for question in prepared.route.questions
                    for field in question.fields
                }
            ),
            affected_material_count=prepared.route.affected_material_count,
            review_channel=(
                "local_page"
                if prepared.route.channel == "local_page"
                else "chat"
            ),
            draft_path=str(
                (paths.visual_drafts / "clip_observations.merged.json").resolve()
            ),
            confirmation_path=str(confirmation_path.resolve()),
            response_path=(
                str(response_path.resolve())
                if prepared.route.channel == "chat"
                else None
            ),
            page_path=prepared.html_path,
            review_questions=list(prepared.route.questions),
        )

    from director.evaluation import VisualConfirmation

    confirmation = VisualConfirmation.model_validate_json(
        confirmation_path.read_text(encoding="utf-8")
    )
    merged_path = paths.visual_drafts / "clip_observations.merged.json"
    validate_visual_confirmation_against_observations(
        confirmation,
        merged,
        _sha256_file(merged_path),
    )
    assisted = apply_visual_confirmation(merged, confirmation, confirmation_path)
    if assisted.status != "completed":
        raise ProjectConflict(
            "completed visual confirmation left required fields unresolved"
        )
    return assisted, None


def _artifacts(paths: ProjectPaths, **extra: Path) -> dict[str, str]:
    artifacts = {
        "project_state": str(paths.project_state.resolve()),
        "brief": str(paths.brief.resolve()),
    }
    artifacts.update({name: str(path.resolve()) for name, path in extra.items()})
    return artifacts


def _result(
    paths: ProjectPaths,
    status: RunState,
    current_stage: str,
    message: str,
    *,
    actions: list[RunAction] | None = None,
    artifacts: dict[str, str] | None = None,
    recommended_duration_seconds: int | None = None,
    music_prompts: list[str] | None = None,
) -> DirectorRunResult:
    return DirectorRunResult(
        status=status,
        project_path=str(paths.root.resolve()),
        current_stage=current_stage,
        message=message,
        actions=actions or [],
        artifact_paths=artifacts or _artifacts(paths),
        recommended_duration_seconds=recommended_duration_seconds,
        music_prompts=music_prompts or [],
    )


def _waiting_for_music_result(
    paths: ProjectPaths,
    summary: "SkillRunSummary",
    summary_path: Path | None = None,
) -> DirectorRunResult:
    confirmation = _load_recorded_stage(
        paths, "brief_confirmation", BriefConfirmation
    )
    if confirmation is None or confirmation.normalized_fields.target_duration_seconds is None:
        raise ProjectConflict("confirmed Brief is missing target duration")
    from director.audio_catalog_cache import get_audio_catalog, write_json_if_changed
    from director.music_recommender import recommend_music

    recommendation_path = paths.root / "music_selection" / "recommendations.json"
    music_brief = getattr(summary, "music_brief", "")
    target = confirmation.normalized_fields.target_duration_seconds
    try:
        catalog, signature = get_audio_catalog()
        recommendations = recommend_music(catalog, music_brief, target)
        payload = {"status": "ready" if recommendations.recommendations else "no_matches",
                   "music_brief": music_brief, "inventory": signature,
                   **recommendations.model_dump(mode="json")}
    except (OSError, ValueError) as exc:
        payload = {"status": "unavailable", "reason": str(exc),
                   "target_duration_seconds": target, "recommendations": []}
    write_json_if_changed(recommendation_path, payload)
    available = bool(payload["recommendations"])
    selection_message = (
        "Choose one recommended local file, then import its version_path with --music. "
        "Do not auto-select. You may also provide another local music file."
        if available else
        "Local recommendations unavailable or no eligible matches; provide a local music file. "
        + payload.get("reason", "No sufficiently long matching versions.")
    )
    return _result(
        paths,
        "waiting_for_music",
        "creative_direction" if summary_path is not None else "visual_review",
        selection_message,
        actions=[
            RunAction(
                kind="provide_music",
                message=selection_message,
                result_path=str((summary_path or paths.final_summary).resolve()),
            )
        ],
        artifacts={**summary.artifact_paths, "music_recommendations": str(recommendation_path.resolve())},
        recommended_duration_seconds=(
            confirmation.normalized_fields.target_duration_seconds
        ),
        music_prompts=list(summary.music_prompts),
    )


def _waiting_for_timeline_result(
    paths: ProjectPaths,
    summary: "SkillRunSummary",
) -> DirectorRunResult:
    from director.audio_import import load_music_evidence

    evidence = load_music_evidence(paths)
    if evidence is None:
        raise ProjectConflict("music evidence is not complete")
    asset, structure = evidence
    return _result(
        paths,
        "waiting_for_timeline",
        "music_analysis",
        "The uploaded music is frozen and analyzed. Timeline work is not enabled yet.",
        actions=[
            RunAction(
                kind="read_music_analysis",
                message="Review the measured local music analysis.",
                result_path=str(paths.music_structure.resolve()),
            )
        ],
        artifacts={
            **summary.artifact_paths,
            "music_asset": str(paths.generated_music.resolve()),
            "frozen_music": str((paths.root / asset.frozen_relative_path).resolve()),
            "music_structure": str(paths.music_structure.resolve()),
        },
        recommended_duration_seconds=round(structure.duration_seconds),
    )


def _completed_timeline_result(
    paths: ProjectPaths,
    summary: "SkillRunSummary",
    timeline_path: Path,
    markdown_path: Path,
) -> DirectorRunResult:
    from director.audio_import import load_music_evidence

    from director.timeline_delivery_store import validate_timeline_delivery

    timeline = validate_timeline_delivery(paths)
    evidence = load_music_evidence(paths)
    if evidence is None:
        raise ProjectConflict("music evidence is not complete")
    asset, structure = evidence
    return _result(
        paths,
        "completed",
        "timeline_delivery",
        "The timeline plan and Markdown delivery are verified; footage slots remain placeholders.",
        actions=[
            RunAction(
                kind="read_summary",
                message="Review the generated timeline delivery Markdown.",
                result_path=str(markdown_path.resolve()),
            )
        ],
        artifacts={
            **summary.artifact_paths,
            "music_asset": str(paths.generated_music.resolve()),
            "frozen_music": str((paths.root / asset.frozen_relative_path).resolve()),
            "music_structure": str(paths.music_structure.resolve()),
            "timeline_delivery": str(timeline_path.resolve()),
            "timeline_markdown": str(markdown_path.resolve()),
        },
        recommended_duration_seconds=round(timeline.target_duration_seconds),
    )


def _build_and_record_delivery(
    paths: ProjectPaths,
    summary: "SkillRunSummary",
) -> tuple[Path, Path]:
    from director.audio_import import load_music_evidence
    from director.creative_direction import load_creative
    from director.delivery import build_fast_mode_timeline
    from director.audio_catalog import build_audio_catalog, resolve_audio_root

    evidence = load_music_evidence(paths)
    if evidence is None:
        raise ProjectConflict("music evidence is not complete")
    asset, structure = evidence

    creative = load_creative(paths, validate_sources=False)
    creative_sections = None
    target_duration = structure.duration_seconds
    if creative is not None:
        creative_direction, _, _ = creative
        creative_sections = creative_direction.sections
        target_duration = creative_direction.target_duration_seconds

    sfx_entries = None
    try:
        audio_root = resolve_audio_root()
        catalog = build_audio_catalog(audio_root)
        sfx_entries = catalog.sfx
    except Exception:
        pass

    frozen_music_path = str((paths.root / asset.frozen_relative_path).resolve())
    timeline = build_fast_mode_timeline(
        music_structure=structure,
        target_duration_seconds=target_duration,
        music_asset_path=frozen_music_path,
        creative_sections=creative_sections,
        sfx_entries=sfx_entries,
    )

    from director.timeline_delivery_store import record_timeline_delivery

    return record_timeline_delivery(paths, timeline)


def _advance_creative(
    paths: ProjectPaths,
    creative_response: Path | None,
    music: Path | None,
    build_timeline: bool = False,
) -> DirectorRunResult:
    from director.audio_import import freeze_and_analyze_music, load_music_evidence
    from director.creative_direction import creative_request, import_creative, load_creative, load_current_creative, _context

    # Check the local-only ledger before any music recovery/import can write.
    _context(paths)
    frozen_plan = load_creative(paths, validate_sources=False)
    if "music_asset" in load_project_state(paths).completed_artifact_hashes and frozen_plan is None:
        build_skill_run_summary(paths.root)

    # Existing frozen music remains a completed input, including legacy projects.
    if (music is not None and creative_response is None
            and "music_asset" in load_project_state(paths).completed_artifact_hashes):
        # The immutable asset can precede analysis after an interrupted/failed run.
        # This function verifies both the recorded asset and matching source hash.
        freeze_and_analyze_music(paths, music)
    music_evidence = load_music_evidence(paths)
    if music_evidence is not None:
        if creative_response is not None:
            raise ProjectConflict("music is already frozen; use a new version for creative changes")
        creative = load_creative(paths, validate_sources=False)
        summary = creative[1] if creative is not None else build_skill_run_summary(paths.root)
        if music is not None:
            freeze_and_analyze_music(paths, music)

        state = load_project_state(paths)
        if "timeline_delivery" in state.completed_artifact_hashes:
            json_path = paths.root / "delivery" / "fast_mode_timeline.json"
            md_path = paths.root / "delivery" / "timeline_delivery.md"
            return _completed_timeline_result(paths, summary, json_path, md_path)

        if build_timeline:
            json_path, md_path = _build_and_record_delivery(paths, summary)
            return _completed_timeline_result(paths, summary, json_path, md_path)

        return _waiting_for_timeline_result(paths, summary)

    creative = import_creative(paths, creative_response) if creative_response is not None else load_current_creative(paths)
    if creative is not None:
        _, summary, summary_path = creative
        if music is not None:
            freeze_and_analyze_music(paths, music)
            if build_timeline:
                json_path, md_path = _build_and_record_delivery(paths, summary)
                return _completed_timeline_result(paths, summary, json_path, md_path)
            return _waiting_for_timeline_result(paths, summary)
        return _waiting_for_music_result(paths, summary, summary_path)
    if music is not None:
        raise ValueError("creative direction is required before importing music")
    if build_timeline:
        raise ValueError("music and creative direction are required before building timeline")
    request, request_path = creative_request(paths)
    return _result(
        paths, "needs_creative_direction", "creative_direction",
        "Use the reference evidence to author an AV section plan and three music prompts in this conversation.",
        actions=[RunAction(
            kind="draft_creative_direction",
            message="Read the request and submit the invoking session's plan using --creative-response. No routine user approval is required.",
            result_path=str(request_path.resolve()),
            response_path=request["response_path"],
            review_channel="chat",
        )],
        artifacts=request["artifact_paths"] | {"creative_request": str(request_path.resolve())},
        recommended_duration_seconds=request["brief"]["normalized_fields"]["target_duration_seconds"],
    )


def _advance_run(
    paths: ProjectPaths,
    input_dir: Path,
    response_file: Path | None = None,
    music: Path | None = None,
    creative_response: Path | None = None,
    build_timeline: bool = False,
) -> DirectorRunResult:
    # Validate every recorded visual source even when resuming beyond it.
    state = load_project_state(paths)
    for stage in VISUAL_STAGE_ORDER:
        if stage in state.completed_artifact_hashes:
            path = paths.artifact_for(stage)
            if not path.is_file() or _sha256_file(path) != state.completed_artifact_hashes[stage]:
                raise ProjectConflict(f"completed artifact drifted: {stage}")
    existing_review = _load_recorded_stage(paths, "director_review", DirectorReview)
    if existing_review is not None:
        if response_file is not None:
            raise ValueError("project is not waiting for a confirmation file")
        return _advance_creative(paths, creative_response, music, build_timeline=build_timeline)
    if creative_response is not None:
        raise ValueError("project is not waiting for creative direction")
    if music is not None:
        raise ValueError("project is not waiting for music")

    observations = _load_recorded_stage(
        paths, "clip_observations", ClipObservationBatch
    )
    if observations is None:
        prepared = _prepare_local_scanner(paths, input_dir)
        agent_actions, checkpoints = _pending_agent_actions(
            prepared.batch_manifest,
            prepared.observations,
        )
        if agent_actions:
            if response_file is not None:
                raise ValueError("project is not waiting for a confirmation file")
            return _result(
                paths,
                "needs_visual_observation",
                "agent_batches",
                "Local contact sheets are ready for bounded visual observation.",
                actions=agent_actions,
                artifacts=_artifacts(
                    paths,
                    scanner_manifest=prepared.scanner_manifest_path,
                    scanner_result=prepared.scanner_result_path,
                    agent_batch_manifest=paths.agent_batch_manifest,
                ),
            )

        raw_draft = merge_agent_batch_results(
            prepared.observations,
            prepared.batch_manifest,
            checkpoints,
        )
        _write_pending_merged_observations(paths, raw_draft)
    else:
        prepared = None
        raw_draft = observations

    intent = _load_recorded_stage(paths, "intent_brief", NormalizedIntentDraft)
    if intent is None:
        draft_path = paths.visual_drafts / "intent_brief.json"
        if draft_path.is_file():
            intent = NormalizedIntentDraft.model_validate_json(
                draft_path.read_text(encoding="utf-8")
            )
        else:
            raw_brief = RawCreativeBrief.model_validate_json(
                paths.brief.read_text(encoding="utf-8")
            )
            intent = DeterministicBriefInterpreter().normalize(raw_brief)
            record_supporting_artifact(paths, draft_path, intent)
    elif not (paths.visual_drafts / "intent_brief.json").is_file():
        record_supporting_artifact(
            paths,
            paths.visual_drafts / "intent_brief.json",
            intent,
        )

    confirmation, brief_action = _brief_confirmation(paths, intent)
    if brief_action is not None:
        if response_file is None:
            return _result(
                paths,
                "needs_user_confirmation",
                "intent_brief",
                "The Brief has missing or conflicting required fields.",
                actions=[brief_action],
                artifacts=_artifacts(
                    paths,
                    intent_brief=paths.visual_drafts / "intent_brief.json",
                ),
            )
        if brief_action.review_channel != "local_page":
            raise ValueError("response file import requires a local-page confirmation")
        _import_brief_page_confirmation(
            paths,
            intent,
            response_file,
            Path(brief_action.confirmation_path or ""),
        )
        confirmation, brief_action = _brief_confirmation(paths, intent)
        if brief_action is not None:
            raise ProjectConflict("imported Brief confirmation was not accepted")
        response_file = None
    assert confirmation is not None

    if observations is None:
        assert prepared is not None
        final_observations, visual_action = _visual_confirmation(
            paths,
            raw_draft,
            prepared.frame_map,
        )
        if visual_action is not None:
            if response_file is None:
                return _result(
                    paths,
                    "needs_user_confirmation",
                    "clip_observations",
                    "Some visual fields remain unresolved after bounded observation.",
                    actions=[visual_action],
                    artifacts=_artifacts(
                        paths,
                        merged_observations=(
                            paths.visual_drafts / "clip_observations.merged.json"
                        ),
                    ),
                )
            if visual_action.review_channel != "local_page":
                raise ValueError("response file import requires a local-page confirmation")
            _import_visual_page_confirmation(
                paths,
                raw_draft,
                response_file,
                Path(visual_action.confirmation_path or ""),
            )
            final_observations, visual_action = _visual_confirmation(
                paths,
                raw_draft,
                prepared.frame_map,
            )
            if visual_action is not None:
                raise ProjectConflict("imported visual confirmation was not accepted")
            response_file = None
        assert final_observations is not None
        observations = _publish_stage(
            paths,
            "clip_observations",
            final_observations,
            draft_name="clip_observations.json",
        )

    intent = _publish_stage(paths, "intent_brief", intent)
    confirmation = _publish_stage(paths, "brief_confirmation", confirmation)

    decisions = _load_recorded_stage(paths, "intent_decisions", IntentDecisionBatch)
    if decisions is None:
        decisions = _publish_stage(
            paths,
            "intent_decisions",
            build_intent_decisions(observations, confirmation),
        )

    coverage = _load_recorded_stage(paths, "project_coverage", ProjectCoverage)
    if coverage is None:
        coverage = _publish_stage(
            paths,
            "project_coverage",
            build_project_coverage(observations, decisions),
        )

    treatment = _load_recorded_stage(paths, "director_treatment", DirectorTreatment)
    if treatment is None:
        treatment = _publish_stage(
            paths,
            "director_treatment",
            build_director_treatment(decisions, coverage, confirmation),
        )

    review = _load_recorded_stage(paths, "director_review", DirectorReview)
    if review is None:
        review = _publish_stage(
            paths,
            "director_review",
            build_automatic_director_review(treatment),
        )

    if response_file is not None:
        raise ValueError("project is not waiting for a confirmation file")
    return _advance_creative(paths, None, None, build_timeline=build_timeline)


def run_travel_director(
    input_dir: Path,
    raw_description: str,
    *,
    project: Path | None = None,
    run_root: Path = Path("prototype/runs"),
    response_file: Path | None = None,
    music: Path | None = None,
    creative_response: Path | None = None,
    new_music_version: bool = False,
    build_timeline: bool = False,
) -> DirectorRunResult:
    """Advance one local visual project to its next explicit stop state."""

    resolved_input = input_dir.resolve()
    raw_brief = RawCreativeBrief(raw_description=raw_description)
    paths: ProjectPaths | None = None
    try:
        if new_music_version and (project is None or music is None or creative_response is not None or response_file is not None):
            raise ValueError("--new-music-version requires --project and --music only")
        if not resolved_input.is_dir():
            raise ValueError(f"input directory does not exist: {resolved_input}")
        media = _media_inventory(resolved_input)
        if creative_response is not None:
            creative_response = creative_response.resolve()
            if project is None:
                raise ValueError("creative response import requires --project")
            if response_file is not None or music is not None:
                raise ValueError("creative response cannot be combined with music or confirmation")
            if not creative_response.is_file():
                raise ValueError(f"creative response file does not exist: {creative_response}")
        if response_file is not None:
            response_file = response_file.resolve()
            if project is None:
                raise ValueError("response file import requires --project")
            if not response_file.is_file():
                raise ValueError(f"response file does not exist: {response_file}")
        if music is not None:
            music = music.resolve()
            if project is None:
                raise ValueError("music import requires --project")
            if response_file is not None:
                raise ValueError("music and response file cannot be imported together")
            if not music.is_file():
                raise ValueError(f"music file does not exist: {music}")
        paths, new_project = _resolve_project(
            resolved_input,
            raw_brief,
            project=project,
            run_root=run_root,
        )
        _record_run_contract(
            paths,
            resolved_input,
            media,
            new_project=new_project,
        )
        if new_music_version:
            from director.music_version import create_music_version
            from director.audio_import import freeze_and_analyze_music
            from director.creative_direction import load_creative
            paths = create_music_version(paths, music)
            creative = load_creative(paths, validate_sources=False)
            summary = creative[1] if creative is not None else build_skill_run_summary(paths.root)
            freeze_and_analyze_music(paths, music)
            if build_timeline:
                json_path, md_path = _build_and_record_delivery(paths, summary)
                return _completed_timeline_result(paths, summary, json_path, md_path)
            return _waiting_for_timeline_result(paths, summary)
        return _advance_run(paths, resolved_input, response_file, music, creative_response, build_timeline=build_timeline)
    except (OSError, ProjectConflict, ValueError) as exc:
        if paths is None:
            intended = (
                project.resolve()
                if project is not None
                else run_root.resolve()
                / _safe_project_id(resolved_input, raw_brief.raw_description)
            )
            return DirectorRunResult(
                status="blocked",
                project_path=str(intended),
                current_stage="initialization",
                message=str(exc),
                actions=[
                    RunAction(
                        kind="resolve_blocker",
                        message=str(exc),
                    )
                ],
            )
        state = load_project_state(paths)
        return _result(
            paths,
            "blocked",
            state.current_stage,
            str(exc),
            actions=[
                RunAction(
                    kind="resolve_blocker",
                    message=str(exc),
                )
            ],
        )


def inspect_travel_director(project: Path) -> DirectorStatusResult:
    """Read and validate current project checkpoints without writing files."""

    paths = open_project(project.resolve())
    state = load_project_state(paths)
    if not isinstance(state, VisualProjectState):
        raise ProjectConflict("status requires a V0.2 visual project")

    completed = [
        stage
        for stage in VISUAL_STAGE_ORDER
        if stage in state.completed_artifact_hashes
    ]
    current_stage = state.current_stage
    for stage in completed:
        artifact = paths.artifact_for(stage)
        if (
            not artifact.is_file()
            or _sha256_file(artifact) != state.completed_artifact_hashes[stage]
        ):
            raise ProjectConflict(f"completed artifact drifted: {stage}")

    if "director_review" in completed:
        from director.audio_import import load_music_evidence
        from director.creative_direction import load_creative, load_current_creative, _context

        _context(paths)
        delivered = "timeline_delivery" in state.completed_artifact_hashes
        frozen = load_music_evidence(paths) is not None
        creative = load_creative(paths, validate_sources=False) if frozen else load_current_creative(paths)
        if delivered:
            from director.timeline_delivery_store import validate_timeline_delivery
            validate_timeline_delivery(paths)
            run_state = "completed"
            current_stage = "timeline_delivery"
        elif frozen:
            run_state = "waiting_for_timeline"
            current_stage = "music_analysis"
        elif creative is not None:
            run_state = "waiting_for_music"
            current_stage = "creative_direction"
        else:
            run_state = "needs_creative_direction"
            current_stage = "creative_direction"
    else:
        run_state: Literal[
            "ready",
            "needs_visual_observation",
            "needs_user_confirmation",
            "needs_creative_direction",
            "waiting_for_music",
            "waiting_for_timeline",
            "completed",
            "blocked",
        ] = "ready"
        if paths.agent_batch_manifest.is_file():
            manifest = _load_supporting(
                paths,
                paths.agent_batch_manifest,
                "agent_batch_manifest",
                AgentBatchManifest,
            ) or AgentBatchManifest.model_validate_json(
                paths.agent_batch_manifest.read_text(encoding="utf-8")
            )
            if any(
                any(item.status == "ready" for item in batch.items)
                and not Path(batch.result_path).is_file()
                for batch in manifest.batches
            ):
                run_state = "needs_visual_observation"
        intent_draft = paths.visual_drafts / "intent_brief.json"
        if intent_draft.is_file():
            intent = NormalizedIntentDraft.model_validate_json(
                intent_draft.read_text(encoding="utf-8")
            )
            if (
                intent.review_required_fields
                and "brief_confirmation" not in completed
            ):
                run_state = "needs_user_confirmation"
        if (
            (paths.visual_dir / "review" / "brief_review.html").is_file()
            or (paths.visual_dir / "review" / "review_route.json").is_file()
        ):
            run_state = "needs_user_confirmation"

    return DirectorStatusResult(
        project_path=str(paths.root.resolve()),
        project_schema_version=state.schema_version,
        project_status=state.status,
        current_stage=current_stage,
        completed_stages=completed,
        run_state=run_state,
    )
