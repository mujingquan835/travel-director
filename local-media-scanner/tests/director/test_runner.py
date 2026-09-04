from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from PIL import Image

import director.runner as runner_module
from director.agent_batches import (
    MaterialFrameMap,
    MaterialFrameSet,
    RepresentativeFrame,
    build_agent_batch_manifest,
)
from director.agent_observations import AgentBatchResult
from director.project import (
    create_visual_project,
    load_project_state,
    record_supporting_artifact,
    record_visual_stage_checked,
)
from director.runner import (
    PreparedScannerEvidence,
    inspect_travel_director,
    run_travel_director,
)
from director.visual_schema import (
    BriefConfirmation,
    ClipObservation,
    ClipObservationBatch,
    EvidenceRef,
    MaterialRef,
    NormalizedBriefFields,
    NormalizedIntentDraft,
    ObservationAssertion,
    RawCreativeBrief,
    derive_material_id,
)


BRIEF = "在开封做城市漫游，60秒，竖屏，纪实风格，探索，节奏适中，纯音乐。"


def _material(input_dir: Path) -> MaterialRef:
    source = input_dir / "clip.mov"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    stat = source.stat()
    return MaterialRef(
        material_id=derive_material_id(digest),
        relative_path="clip.mov",
        source_sha256=digest,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        duration_seconds=8.0,
        fps=25.0,
        orientation="portrait",
    )


def _scanner_observations(input_dir: Path) -> ClipObservationBatch:
    material = _material(input_dir)
    evidence = EvidenceRef(
        material_id=material.material_id,
        artifact_path="scanner_result.json",
        field_path="items[0].quality",
        source_kind="scanner",
        status="measured",
        sha256="a" * 64,
    )
    return ClipObservationBatch(
        status="completed",
        mode="scanner_only",
        items=[
            ClipObservation(
                material=material,
                provider="scanner_only",
                observation_status="automatic",
                assertions=[
                    ObservationAssertion(
                        field="technical_usability",
                        value="usable",
                        status="measured",
                        evidence_refs=[evidence],
                    ),
                    ObservationAssertion(
                        field="orientation",
                        value="portrait",
                        status="measured",
                        evidence_refs=[evidence],
                    ),
                ],
            )
        ],
    )


def _prepared_scanner(paths, input_dir: Path) -> PreparedScannerEvidence:
    run_dir = paths.visual_dir / "scanner" / "runs" / "scanner-v1"
    frames = []
    for index, color in enumerate(("red", "green", "blue")):
        frame = run_dir / "frames" / f"{index}.jpg"
        frame.parent.mkdir(parents=True, exist_ok=True)
        if not frame.is_file():
            Image.new("RGB", (80, 120), color).save(frame)
        frames.append(RepresentativeFrame(path=str(frame), timestamp=float(index)))
    frame_map = MaterialFrameMap(
        items=[MaterialFrameSet(material=_material(input_dir), frames=frames)]
    )
    manifest = build_agent_batch_manifest(
        frame_map,
        paths.agent_batch_manifest.parent,
    )
    paths.agent_batch_manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.agent_batch_manifest.write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    scanner_manifest = paths.visual_dir / "scanner" / "input_manifest.json"
    scanner_result = run_dir / "scanner_result.json"
    scanner_manifest.parent.mkdir(parents=True, exist_ok=True)
    scanner_manifest.touch(exist_ok=True)
    scanner_result.touch(exist_ok=True)
    return PreparedScannerEvidence(
        observations=_scanner_observations(input_dir),
        frame_map=frame_map,
        batch_manifest=manifest,
        scanner_manifest_path=scanner_manifest,
        scanner_result_path=scanner_result,
    )


def _write_agent_result(result_path: Path, input_dir: Path) -> None:
    material = _material(input_dir)
    sheet = next(result_path.parent.parent.glob("contact_sheets/*.jpg"))
    evidence = EvidenceRef(
        material_id=material.material_id,
        artifact_path=str(sheet.resolve()),
        field_path="contact_sheet",
        source_kind="visual_provider",
        status="candidate",
        confidence=0.9,
        sha256=hashlib.sha256(sheet.read_bytes()).hexdigest(),
    )
    observation = ClipObservation(
        material=material,
        provider="invoking_agent",
        observation_status="automatic",
        assertions=[
            ObservationAssertion(
                field="content_families",
                value=["urban"],
                status="candidate",
                confidence=0.9,
                evidence_refs=[evidence],
            )
        ],
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        AgentBatchResult(
            batch_id="batch-000",
            status="completed",
            items=[observation],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )


def _write_agent_result_requiring_visual_confirmation(
    result_path: Path, input_dir: Path
) -> None:
    material = _material(input_dir)
    sheet = next(result_path.parent.parent.glob("contact_sheets/*.jpg"))
    evidence = EvidenceRef(
        material_id=material.material_id,
        artifact_path=str(sheet.resolve()),
        field_path="contact_sheet",
        source_kind="visual_provider",
        status="candidate",
        confidence=0.9,
        sha256=hashlib.sha256(sheet.read_bytes()).hexdigest(),
    )
    observation = ClipObservation(
        material=material,
        provider="invoking_agent",
        observation_status="assisted",
        assertions=[
            ObservationAssertion(
                field="content_families",
                value=["urban"],
                status="candidate",
                confidence=0.9,
                evidence_refs=[evidence],
            ),
            ObservationAssertion(
                field="lighting",
                status="abstained",
            ),
        ],
        unknown_fields=["lighting"],
        review_required_fields=["lighting"],
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        AgentBatchResult(
            batch_id="batch-000",
            status="completed",
            items=[observation],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )


def _write_agent_result_requiring_local_page(
    result_path: Path, input_dir: Path
) -> None:
    material = _material(input_dir)
    sheet = next(result_path.parent.parent.glob("contact_sheets/*.jpg"))
    evidence = EvidenceRef(
        material_id=material.material_id,
        artifact_path=str(sheet.resolve()),
        field_path="contact_sheet",
        source_kind="visual_provider",
        status="candidate",
        confidence=0.9,
        sha256=hashlib.sha256(sheet.read_bytes()).hexdigest(),
    )
    review_fields = [
        "setting",
        "lighting",
        "people_presence",
        "people_count_band",
        "subject_candidates",
        "activity_candidates",
    ]
    observation = ClipObservation(
        material=material,
        provider="invoking_agent",
        observation_status="assisted",
        assertions=[
            ObservationAssertion(
                field="content_families",
                value=["urban"],
                status="candidate",
                confidence=0.9,
                evidence_refs=[evidence],
            ),
            *[
                ObservationAssertion(field=field, status="abstained")
                for field in review_fields
            ],
        ],
        unknown_fields=review_fields,
        review_required_fields=review_fields,
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        AgentBatchResult(
            batch_id="batch-000",
            status="completed",
            items=[observation],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )


def test_run_stops_for_visual_observation_then_waits_for_music_idempotently(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"

    waiting = run_travel_director(input_dir, BRIEF, project=project)

    assert waiting.status == "needs_visual_observation"
    assert len(waiting.actions) == 1
    result_path = Path(waiting.actions[0].result_path or "")
    state_before_retry = (project / "project_state.json").read_bytes()

    repeated = run_travel_director(input_dir, BRIEF, project=project)

    assert repeated.status == "needs_visual_observation"
    assert (project / "project_state.json").read_bytes() == state_before_retry

    _write_agent_result(result_path, input_dir)
    music_wait = run_travel_director(input_dir, BRIEF, project=project)
    hashes = dict(load_project_state(project).completed_artifact_hashes)
    resumed = run_travel_director(input_dir, BRIEF, project=project)

    assert music_wait.status == "waiting_for_music"
    assert resumed.status == "waiting_for_music"
    assert load_project_state(project).completed_artifact_hashes == hashes
    assert music_wait.external_call_count == 0
    assert music_wait.recommended_duration_seconds == 60
    assert len(music_wait.music_prompts) == 3
    assert music_wait.actions[0].kind == "provide_music"
    assert music_wait.actions[0].result_path == str(
        (project / "visual" / "final_summary.json").resolve()
    )


def test_incomplete_agent_result_routes_to_immutable_supplement(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    paths = create_visual_project(
        tmp_path / "runs", "supplement", RawCreativeBrief(raw_description=BRIEF)
    )
    prepared = _prepared_scanner(paths, input_dir)
    scanner_item = prepared.observations.items[0].model_copy(
        update={"unknown_fields": ["lighting"], "review_required_fields": ["lighting"]}
    )
    scanner = prepared.observations.model_copy(update={"items": [scanner_item]})
    first_actions, _ = runner_module._pending_agent_actions(
        prepared.batch_manifest, scanner
    )
    base_path = Path(first_actions[0].result_path or "")
    _write_agent_result(base_path, input_dir)

    supplement_actions, checkpoints = runner_module._pending_agent_actions(
        prepared.batch_manifest, scanner
    )

    assert len(checkpoints) == 1
    assert supplement_actions[0].required_fields == ["lighting"]
    supplement_path = Path(supplement_actions[0].result_path or "")
    assert supplement_path.parent.name == "supplements"
    material = _material(input_dir)
    sheet = next(base_path.parent.parent.glob("contact_sheets/*.jpg"))
    evidence = EvidenceRef(
        material_id=material.material_id,
        artifact_path=str(sheet.resolve()),
        field_path="contact_sheet",
        source_kind="visual_provider",
        status="candidate",
        confidence=0.9,
        sha256=hashlib.sha256(sheet.read_bytes()).hexdigest(),
    )
    supplement_path.parent.mkdir(parents=True, exist_ok=True)
    supplement_path.write_text(
        AgentBatchResult(
            batch_id="batch-000",
            status="completed",
            items=[
                ClipObservation(
                    material=material,
                    provider="invoking_agent",
                    observation_status="automatic",
                    assertions=[
                        ObservationAssertion(
                            field="lighting",
                            value="daylight",
                            status="candidate",
                            confidence=0.9,
                            evidence_refs=[evidence],
                        )
                    ],
                )
            ],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    final_actions, final_checkpoints = runner_module._pending_agent_actions(
        prepared.batch_manifest, scanner
    )
    merged = runner_module.merge_agent_batch_results(
        scanner, prepared.batch_manifest, final_checkpoints
    )

    assert final_actions == []
    assert len(final_checkpoints) == 2
    assert merged.status == "completed"


def test_run_resumes_existing_visual_project_without_rebuilding_scanner(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"legacy source")
    paths = create_visual_project(
        tmp_path / "runs",
        "legacy-visual",
        RawCreativeBrief(raw_description=BRIEF),
    )
    observations = _scanner_observations(input_dir)
    material = observations.items[0].material
    observations.items[0].assertions.append(
        ObservationAssertion(
            field="content_families",
            value=["urban"],
            status="candidate",
            confidence=0.8,
            evidence_refs=[
                EvidenceRef(
                    material_id=material.material_id,
                    artifact_path="preserved-contact-sheet.jpg",
                    field_path="contact_sheet",
                    source_kind="visual_provider",
                    status="candidate",
                    confidence=0.8,
                    sha256="b" * 64,
                )
            ],
        )
    )
    draft = paths.visual_drafts / "preserved-observations.json"
    record_supporting_artifact(paths, draft, observations)
    record_visual_stage_checked(paths, "clip_observations", draft)
    original_hash = load_project_state(paths).completed_artifact_hashes[
        "clip_observations"
    ]

    def scanner_must_not_run(*_args, **_kwargs):
        raise AssertionError("recorded observations must be reused")

    monkeypatch.setattr(
        runner_module, "_prepare_local_scanner", scanner_must_not_run
    )
    original_sha256_file = runner_module._sha256_file
    source = input_dir / "clip.mov"
    source_hash_calls = 0

    def tracking_sha256_file(path: Path) -> str:
        nonlocal source_hash_calls
        if path.resolve() == source.resolve():
            source_hash_calls += 1
        return original_sha256_file(path)

    monkeypatch.setattr(runner_module, "_sha256_file", tracking_sha256_file)
    result = run_travel_director(input_dir, BRIEF, project=paths.root)

    assert result.status == "waiting_for_music"
    assert source_hash_calls == 1
    assert (
        load_project_state(paths).completed_artifact_hashes["clip_observations"]
        == original_hash
    )


def test_status_is_read_only_and_detects_waiting_state(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"
    run_travel_director(input_dir, BRIEF, project=project)
    before = (project / "project_state.json").read_bytes()

    status = inspect_travel_director(project)

    assert status.run_state == "needs_visual_observation"
    assert (project / "project_state.json").read_bytes() == before


def test_completed_run_reports_tampered_stage_as_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"
    waiting = run_travel_director(input_dir, BRIEF, project=project)
    _write_agent_result(Path(waiting.actions[0].result_path or ""), input_dir)
    assert (
        run_travel_director(input_dir, BRIEF, project=project).status
        == "waiting_for_music"
    )
    (project / "visual" / "director_treatment.json").write_text(
        "{}", encoding="utf-8"
    )

    blocked = run_travel_director(input_dir, BRIEF, project=project)

    assert blocked.status == "blocked"
    assert "drifted" in blocked.message


def test_status_reports_chat_brief_confirmation_without_a_page(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"
    waiting = run_travel_director(
        input_dir,
        "在开封做城市漫游，60秒，竖屏。",
        project=project,
    )
    _write_agent_result(Path(waiting.actions[0].result_path or ""), input_dir)

    confirmation = run_travel_director(
        input_dir,
        "在开封做城市漫游，60秒，竖屏。",
        project=project,
    )
    status = inspect_travel_director(project)

    assert confirmation.status == "needs_user_confirmation"
    assert confirmation.actions[0].review_channel == "chat"
    assert confirmation.actions[0].response_path is not None
    assert confirmation.actions[0].page_path is None
    assert status.run_state == "needs_user_confirmation"


def test_run_converts_simple_brief_response_to_strict_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"
    brief = "在开封做城市漫游，60秒，竖屏。"
    waiting = run_travel_director(input_dir, brief, project=project)
    _write_agent_result(Path(waiting.actions[0].result_path or ""), input_dir)

    confirmation = run_travel_director(input_dir, brief, project=project)
    action = confirmation.actions[0]
    response_path = Path(action.response_path or "")
    response_path.write_text(
        json.dumps(
            {
                "kind": "brief",
                "answers": {
                    "style": "纪实",
                    "mood": "探索",
                    "rhythm": "medium",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    music_wait = run_travel_director(input_dir, brief, project=project)

    strict = json.loads(
        (project / "visual" / "drafts" / "brief_confirmation.json").read_text(
            encoding="utf-8"
        )
    )
    assert music_wait.status == "waiting_for_music"
    assert strict["draft_sha256"]
    assert strict["changed_fields"] == ["mood", "rhythm", "style"]
    assert strict["normalized_fields"]["style"] == "纪实"


def test_run_converts_simple_visual_response_to_strict_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"
    waiting = run_travel_director(input_dir, BRIEF, project=project)
    _write_agent_result_requiring_visual_confirmation(
        Path(waiting.actions[0].result_path or ""), input_dir
    )

    confirmation = run_travel_director(input_dir, BRIEF, project=project)
    action = confirmation.actions[0]
    response_path = Path(action.response_path or "")
    assert action.kind == "confirm_visual_fields"
    assert action.review_channel == "chat"
    assert action.review_questions[0].fields == ["lighting"]
    response_path.write_text(
        json.dumps(
            {
                "kind": "visual",
                "answers": [
                    {
                        "material_id": _material(input_dir).material_id,
                        "field": "lighting",
                        "value": "daylight",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    music_wait = run_travel_director(input_dir, BRIEF, project=project)

    strict = json.loads(
        (project / "visual" / "review" / "visual_confirmation.json").read_text(
            encoding="utf-8"
        )
    )
    assert music_wait.status == "waiting_for_music"
    assert strict["source_observations_sha256"]
    assert strict["items"][0]["original_status"] == "abstained"
    assert strict["items"][0]["confirmed_value"] == "daylight"


def test_run_blocks_when_required_confirmation_is_declined(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"
    brief = "在开封做城市漫游，60秒，竖屏。"
    waiting = run_travel_director(input_dir, brief, project=project)
    _write_agent_result(Path(waiting.actions[0].result_path or ""), input_dir)
    confirmation = run_travel_director(input_dir, brief, project=project)
    Path(confirmation.actions[0].response_path or "").write_text(
        json.dumps({"kind": "brief", "status": "declined"}),
        encoding="utf-8",
    )

    blocked = run_travel_director(input_dir, brief, project=project)

    assert blocked.status == "blocked"
    assert "declined" in blocked.message
    assert not (project / "visual" / "music_style_recommendations.json").exists()


def _finish_visual_flow(
    input_dir: Path,
    project: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    first = run_travel_director(input_dir, BRIEF, project=project)
    _write_agent_result(Path(first.actions[0].result_path or ""), input_dir)
    result = run_travel_director(input_dir, BRIEF, project=project)
    assert result.status == "waiting_for_music"


def test_new_run_contract_hashes_each_source_once_and_records_fast_identity(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / "clip.mov"
    source.write_bytes(b"local source")
    project = tmp_path / "runs" / "demo"
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    original_sha256_file = runner_module._sha256_file
    source_hash_calls = 0

    def tracking_sha256_file(path: Path) -> str:
        nonlocal source_hash_calls
        if path.resolve() == source.resolve():
            source_hash_calls += 1
        return original_sha256_file(path)

    monkeypatch.setattr(runner_module, "_sha256_file", tracking_sha256_file)

    run_travel_director(input_dir, BRIEF, project=project)

    contract = json.loads(
        (project / "visual" / "run_contract.json").read_text(encoding="utf-8")
    )
    assert source_hash_calls == 1
    assert contract["schema_version"] == "0.3.0"
    assert contract["media"][0]["ctime_ns"] == source.stat().st_ctime_ns
    assert contract["media"][0]["source_sha256"] == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()


def test_unchanged_resume_does_not_rehash_source_media(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / "clip.mov"
    source.write_bytes(b"local source")
    project = tmp_path / "runs" / "demo"
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    first = run_travel_director(input_dir, BRIEF, project=project)
    _write_agent_result(Path(first.actions[0].result_path or ""), input_dir)
    assert run_travel_director(input_dir, BRIEF, project=project).status == (
        "waiting_for_music"
    )
    original_sha256_file = runner_module._sha256_file
    source_hash_calls = 0

    def tracking_sha256_file(path: Path) -> str:
        nonlocal source_hash_calls
        if path.resolve() == source.resolve():
            source_hash_calls += 1
        return original_sha256_file(path)

    monkeypatch.setattr(runner_module, "_sha256_file", tracking_sha256_file)

    resumed = run_travel_director(input_dir, BRIEF, project=project)

    assert resumed.status == "waiting_for_music"
    assert source_hash_calls == 0


def test_completed_visual_project_rejects_a_different_input_without_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    first_input = tmp_path / "first-input"
    first_input.mkdir()
    (first_input / "clip.mov").write_bytes(b"first source")
    second_input = tmp_path / "second-input"
    second_input.mkdir()
    (second_input / "clip.mov").write_bytes(b"second source")
    project = tmp_path / "runs" / "demo"
    _finish_visual_flow(first_input, project, monkeypatch)
    protected = {
        path: path.read_bytes()
        for path in (
            project / "project_state.json",
            project / "visual" / "run_contract.json",
            project / "visual" / "final_summary.json",
        )
    }

    blocked = run_travel_director(second_input, BRIEF, project=project)

    assert blocked.status == "blocked"
    assert "input" in blocked.message.lower()
    assert {path: path.read_bytes() for path in protected} == protected


@pytest.mark.parametrize("mutation", ["add", "remove", "mtime", "content"])
def test_completed_visual_project_rejects_changed_media_without_mutation(
    tmp_path: Path, monkeypatch, mutation: str
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / "clip.mov"
    source.write_bytes(b"original source")
    project = tmp_path / "runs" / "demo"
    _finish_visual_flow(input_dir, project, monkeypatch)
    protected = {
        path: path.read_bytes()
        for path in (
            project / "project_state.json",
            project / "visual" / "run_contract.json",
            project / "visual" / "final_summary.json",
        )
    }

    if mutation == "add":
        (input_dir / "added.mp4").write_bytes(b"added")
    elif mutation == "remove":
        source.unlink()
    elif mutation == "mtime":
        original_stat = source.stat()
        os.utime(
            source,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1),
        )
    else:
        original_stat = source.stat()
        source.write_bytes(b"changed content")
        os.utime(
            source,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )

    original_sha256_file = runner_module._sha256_file
    source_hash_calls = 0

    def tracking_sha256_file(path: Path) -> str:
        nonlocal source_hash_calls
        if path.resolve() == source.resolve():
            source_hash_calls += 1
        return original_sha256_file(path)

    monkeypatch.setattr(runner_module, "_sha256_file", tracking_sha256_file)
    blocked = run_travel_director(input_dir, BRIEF, project=project)

    assert blocked.status == "blocked"
    assert "input" in blocked.message.lower()
    assert source_hash_calls == 0
    assert {path: path.read_bytes() for path in protected} == protected


def _brief_page_download(project: Path, *, valid_hash: bool = True) -> Path:
    draft_path = project / "visual" / "drafts" / "intent_brief.json"
    draft = NormalizedIntentDraft.model_validate_json(
        draft_path.read_text(encoding="utf-8")
    )
    fields = NormalizedBriefFields(
        location="开封",
        travel_type="城市漫游",
        target_duration_seconds=60,
        orientation="portrait",
        style="纪实",
        mood="探索",
        rhythm="medium",
    )
    original = draft.normalized_fields.model_dump(mode="json")
    confirmed = fields.model_dump(mode="json")
    download = project.parent / "downloaded-brief-confirmation.json"
    download.write_text(
        BriefConfirmation(
            status="completed",
            draft_sha256=(
                hashlib.sha256(draft_path.read_bytes()).hexdigest()
                if valid_hash
                else "0" * 64
            ),
            normalized_fields=fields,
            changed_fields=sorted(
                field for field, value in confirmed.items() if original[field] != value
            ),
            confirmed_at="2026-09-04T12:00:00+08:00",
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    return download


def test_run_imports_a_downloaded_brief_page_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"
    first = run_travel_director(input_dir, "开封旅行", project=project)
    _write_agent_result(Path(first.actions[0].result_path or ""), input_dir)
    confirmation = run_travel_director(input_dir, "开封旅行", project=project)
    assert confirmation.actions[0].review_channel == "local_page"
    download = _brief_page_download(project)

    music_wait = run_travel_director(
        input_dir,
        "开封旅行",
        project=project,
        response_file=download,
    )
    state_after_import = (project / "project_state.json").read_bytes()
    repeated = run_travel_director(
        input_dir,
        "开封旅行",
        project=project,
        response_file=download,
    )

    assert music_wait.status == "waiting_for_music"
    assert repeated.status == "blocked"
    assert "not waiting" in repeated.message
    assert (project / "project_state.json").read_bytes() == state_after_import
    imported = BriefConfirmation.model_validate_json(
        (project / "visual" / "review" / "brief_confirmation.json").read_text(
            encoding="utf-8"
        )
    )
    assert imported.draft_sha256 == hashlib.sha256(
        (project / "visual" / "drafts" / "intent_brief.json").read_bytes()
    ).hexdigest()


def test_run_rejects_a_downloaded_brief_confirmation_with_the_wrong_hash(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"
    first = run_travel_director(input_dir, "开封旅行", project=project)
    _write_agent_result(Path(first.actions[0].result_path or ""), input_dir)
    confirmation = run_travel_director(input_dir, "开封旅行", project=project)
    assert confirmation.actions[0].review_channel == "local_page"
    download = _brief_page_download(project, valid_hash=False)
    before = (project / "project_state.json").read_bytes()

    blocked = run_travel_director(
        input_dir,
        "开封旅行",
        project=project,
        response_file=download,
    )

    assert blocked.status == "blocked"
    assert "hash" in blocked.message.lower()
    assert not (project / "visual" / "review" / "brief_confirmation.json").exists()
    assert (project / "project_state.json").read_bytes() == before


def test_run_rejects_a_downloaded_confirmation_of_the_wrong_type(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"
    first = run_travel_director(input_dir, "开封旅行", project=project)
    _write_agent_result(Path(first.actions[0].result_path or ""), input_dir)
    confirmation = run_travel_director(input_dir, "开封旅行", project=project)
    assert confirmation.actions[0].review_channel == "local_page"
    download = tmp_path / "downloaded-visual-response.json"
    download.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "kind": "visual",
                "status": "answered",
                "answers": [],
            }
        ),
        encoding="utf-8",
    )
    before = (project / "project_state.json").read_bytes()

    blocked = run_travel_director(
        input_dir,
        "开封旅行",
        project=project,
        response_file=download,
    )

    assert blocked.status == "blocked"
    assert "Brief confirmation" in blocked.message
    assert not (project / "visual" / "review" / "brief_confirmation.json").exists()
    assert (project / "project_state.json").read_bytes() == before


def test_run_imports_a_downloaded_visual_page_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    from director.evaluation import FieldConfirmation, VisualConfirmation

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"local source")
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    project = tmp_path / "runs" / "demo"
    first = run_travel_director(input_dir, BRIEF, project=project)
    _write_agent_result_requiring_local_page(
        Path(first.actions[0].result_path or ""), input_dir
    )
    confirmation = run_travel_director(input_dir, BRIEF, project=project)
    assert confirmation.actions[0].review_channel == "local_page"
    merged = project / "visual" / "drafts" / "clip_observations.merged.json"
    values = {
        "setting": "outdoor",
        "lighting": "daylight",
        "people_presence": "absent",
        "people_count_band": "none",
        "subject_candidates": ["城门"],
        "activity_candidates": ["步行"],
    }
    download = tmp_path / "downloaded-visual-confirmation.json"
    download.write_text(
        VisualConfirmation(
            source_observations_sha256=hashlib.sha256(merged.read_bytes()).hexdigest(),
            status="completed",
            reviewer="user",
            items=[
                FieldConfirmation(
                    material_id=_material(input_dir).material_id,
                    field=field,
                    original_value=None,
                    original_status="abstained",
                    confirmed_value=value,
                    confirmed_status="confirmed",
                    changed_at="2026-09-04T12:00:00+08:00",
                )
                for field, value in values.items()
            ],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    music_wait = run_travel_director(
        input_dir,
        BRIEF,
        project=project,
        response_file=download,
    )

    assert music_wait.status == "waiting_for_music"
    assert (project / "visual" / "review" / "visual_confirmation.json").is_file()


def test_legacy_subset_cannot_bind_to_a_larger_input_directory(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"legacy source")
    paths = create_visual_project(
        tmp_path / "runs",
        "legacy-subset",
        RawCreativeBrief(raw_description=BRIEF),
    )
    draft = paths.visual_drafts / "legacy-observations.json"
    record_supporting_artifact(paths, draft, _scanner_observations(input_dir))
    record_visual_stage_checked(paths, "clip_observations", draft)
    (input_dir / "extra.mp4").write_bytes(b"not in the frozen subset")
    before = paths.project_state.read_bytes()

    blocked = run_travel_director(input_dir, BRIEF, project=paths.root)

    assert blocked.status == "blocked"
    assert "benchmark subset" in blocked.message
    assert paths.project_state.read_bytes() == before
    assert not (paths.visual_dir / "run_contract.json").exists()


def test_v2_run_contract_resumes_without_rewrite_or_source_rehash(
    tmp_path: Path, monkeypatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / "clip.mov"
    source.write_bytes(b"v2 contracted source")
    paths = create_visual_project(
        tmp_path / "runs",
        "v2-contract",
        RawCreativeBrief(raw_description=BRIEF),
    )
    stat = source.stat()
    contract_path = paths.visual_dir / "run_contract.json"
    record_supporting_artifact(
        paths,
        contract_path,
        {
            "schema_version": "0.2.0",
            "input_root": str(input_dir.resolve()),
            "brief_sha256": hashlib.sha256(paths.brief.read_bytes()).hexdigest(),
            "media": [
                {
                    "relative_path": "clip.mov",
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            ],
            "models_enabled": False,
            "external_services_enabled": False,
        },
        state_key="run_contract",
    )
    original_contract = contract_path.read_bytes()
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    original_sha256_file = runner_module._sha256_file
    source_hash_calls = 0

    def tracking_sha256_file(path: Path) -> str:
        nonlocal source_hash_calls
        if path.resolve() == source.resolve():
            source_hash_calls += 1
        return original_sha256_file(path)

    monkeypatch.setattr(runner_module, "_sha256_file", tracking_sha256_file)

    result = run_travel_director(input_dir, BRIEF, project=paths.root)

    assert result.status == "needs_visual_observation"
    assert source_hash_calls == 0
    assert contract_path.read_bytes() == original_contract


def test_legacy_project_without_material_fingerprints_cannot_bind_an_input(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "clip.mov").write_bytes(b"unverified legacy source")
    paths = create_visual_project(
        tmp_path / "runs",
        "legacy-without-observations",
        RawCreativeBrief(raw_description=BRIEF),
    )
    before = paths.project_state.read_bytes()

    blocked = run_travel_director(input_dir, BRIEF, project=paths.root)

    assert blocked.status == "blocked"
    assert "source fingerprints" in blocked.message
    assert paths.project_state.read_bytes() == before
    assert not (paths.visual_dir / "run_contract.json").exists()


def test_new_run_validates_media_inventory_before_creating_a_project(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "notes.txt").write_text("not footage", encoding="utf-8")
    run_root = tmp_path / "runs"

    blocked = run_travel_director(input_dir, BRIEF, run_root=run_root)

    assert blocked.status == "blocked"
    assert "no supported video" in blocked.message
    assert not Path(blocked.project_path).exists()
    assert not run_root.exists()
