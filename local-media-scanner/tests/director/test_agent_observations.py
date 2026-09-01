from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from director.agent_batches import AgentBatchManifest, AgentMaterialPacket
from director.agent_observations import AgentBatchResult, merge_agent_batch_results, validate_agent_batch_result, write_agent_batch_checkpoint
from director.cli import app
from director.project import create_visual_project
from director.visual_schema import ClipObservation, ClipObservationBatch, EvidenceRef, MaterialRef, ObservationAssertion, RawCreativeBrief, derive_material_id


def _material(index: int) -> MaterialRef:
    digest = hashlib.sha256(f"clip-{index}".encode()).hexdigest()
    return MaterialRef(material_id=derive_material_id(digest), relative_path=f"trip/clip-{index:02d}.mov", source_sha256=digest, size_bytes=100 + index, mtime_ns=1000 + index, duration_seconds=4.0, fps=25.0, orientation="landscape")


def _manifest(tmp_path: Path, count: int = 2, *, ready: set[int] | None = None) -> AgentBatchManifest:
    ready = set(range(count)) if ready is None else ready
    packets = []
    for index in range(count):
        material = _material(index)
        sheet = tmp_path / "sheets" / f"{index}.jpg"
        if index in ready:
            sheet.parent.mkdir(parents=True, exist_ok=True)
            sheet.write_bytes(f"sheet-{index}".encode())
        packets.append(AgentMaterialPacket(material_id=material.material_id, relative_path=material.relative_path, status="ready" if index in ready else "review_required", contact_sheet_path=str(sheet) if index in ready else None, allowed_fields=["technical_usability", "content_family", "setting", "lighting", "people_presence", "people_count_band", "subject_candidates", "activity_candidates"], source_evidence_refs=[]))
    batches = [{"batch_id": f"batch-{batch_index:03d}", "batch_index": batch_index, "items": packets[start : start + 10], "result_path": str(tmp_path / "results" / f"batch-{batch_index:03d}.json")} for batch_index, start in enumerate(range(0, count, 10))]
    return AgentBatchManifest(items=packets, batches=batches)


def _evidence(packet: AgentMaterialPacket) -> EvidenceRef:
    assert packet.contact_sheet_path is not None
    return EvidenceRef(material_id=packet.material_id, artifact_path=packet.contact_sheet_path, field_path="contact_sheet", source_kind="visual_provider", status="candidate", confidence=0.8, sha256=hashlib.sha256(Path(packet.contact_sheet_path).read_bytes()).hexdigest())


def _agent_item(index: int, packet: AgentMaterialPacket, *, field: str = "lighting") -> ClipObservation:
    return ClipObservation(material=_material(index), provider="invoking_agent", observation_status="automatic", assertions=[ObservationAssertion(field=field, value="daylight", status="candidate", confidence=0.8, evidence_refs=[_evidence(packet)])])


def _result(manifest: AgentBatchManifest, batch_index: int = 0) -> AgentBatchResult:
    batch = manifest.batches[batch_index]
    return AgentBatchResult(batch_id=batch.batch_id, status="completed", items=[_agent_item(index, packet) for index, packet in enumerate(batch.items, start=batch_index * 10) if packet.status == "ready"])


def _scanner_batch(count: int) -> ClipObservationBatch:
    items = []
    for index in range(count):
        material = _material(index)
        items.append(ClipObservation(material=material, provider="scanner_only", observation_status="automatic", assertions=[ObservationAssertion(field="technical_usability", value="usable", status="measured", evidence_refs=[EvidenceRef(material_id=material.material_id, artifact_path="scanner-result.json", field_path="items[0].quality", source_kind="scanner", status="measured", sha256="a" * 64)])]))
    return ClipObservationBatch(status="completed", mode="scanner_only", items=items)


def test_validation_rejects_material_not_assigned_to_batch(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    result = _result(manifest)
    result.items[0] = _agent_item(99, manifest.batches[0].items[0])
    with pytest.raises(ValueError, match="not assigned"):
        validate_agent_batch_result(manifest, result)


def test_validation_requires_each_ready_packet_once_and_skips_missing_frames(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 2, ready={0})
    result = _result(manifest)
    assert validate_agent_batch_result(manifest, result) == result
    result.items = []
    with pytest.raises(ValueError, match="missing ready material"):
        validate_agent_batch_result(manifest, result)


@pytest.mark.parametrize("field", ["location_name", "person_name", "relationship", "story_identity"])
def test_validation_rejects_unsupported_agent_assertion_fields(tmp_path: Path, field: str) -> None:
    manifest = _manifest(tmp_path, 1)
    result = _result(manifest)
    result.items[0] = _agent_item(0, manifest.batches[0].items[0], field=field)
    with pytest.raises(ValueError, match="not allowed"):
        validate_agent_batch_result(manifest, result)


def test_candidate_requires_its_packet_contact_sheet_evidence(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 1)
    result = _result(manifest)
    assertion = result.items[0].assertions[0]
    assertion.evidence_refs[0] = assertion.evidence_refs[0].model_copy(update={"artifact_path": str(tmp_path / "unrelated.jpg")})
    with pytest.raises(ValueError, match="contact sheet"):
        validate_agent_batch_result(manifest, result)


def test_candidate_rejects_contact_sheet_hash_that_does_not_match_packet(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 1)
    result = _result(manifest)
    assertion = result.items[0].assertions[0]
    assertion.evidence_refs[0] = assertion.evidence_refs[0].model_copy(update={"sha256": "f" * 64})
    with pytest.raises(ValueError, match="contact sheet hash"):
        validate_agent_batch_result(manifest, result)


def test_completed_checkpoint_is_reused_without_rewriting_bytes(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 1)
    result = validate_agent_batch_result(manifest, _result(manifest))
    checkpoint = tmp_path / "results" / "batch-000.json"
    original = result.model_dump_json(indent=2).encode()
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(original)
    assert write_agent_batch_checkpoint(result, checkpoint) == checkpoint
    assert checkpoint.read_bytes() == original


def test_malformed_checkpoint_is_reported_and_not_replaced(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 1)
    checkpoint = tmp_path / "results" / "batch-000.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{malformed", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed checkpoint"):
        merge_agent_batch_results(_scanner_batch(1), manifest, [checkpoint])
    assert checkpoint.read_text(encoding="utf-8") == "{malformed"


def test_merge_two_result_files_preserves_measured_assertions_and_sorts_paths(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 12)
    paths = []
    for batch_index in range(2):
        checkpoint = tmp_path / "results" / f"batch-{batch_index:03d}.json"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(_result(manifest, batch_index).model_dump_json(), encoding="utf-8")
        paths.append(checkpoint)
    merged = merge_agent_batch_results(_scanner_batch(12), manifest, list(reversed(paths)))
    assert merged.status == "completed"
    assert merged.mode == "automatic"
    assert [item.material.relative_path for item in merged.items] == sorted(item.material.relative_path for item in merged.items)
    assert all(any(assertion.field == "technical_usability" and assertion.status == "measured" for assertion in item.assertions) and any(assertion.field == "lighting" and assertion.status == "candidate" for assertion in item.assertions) for item in merged.items)


def test_merge_does_not_add_agent_candidate_over_scanner_measured_field(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 1)
    result = _result(manifest)
    result.items[0] = _agent_item(0, manifest.batches[0].items[0], field="technical_usability")
    checkpoint = tmp_path / "results" / "batch-000.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(result.model_dump_json(), encoding="utf-8")

    merged = merge_agent_batch_results(_scanner_batch(1), manifest, [checkpoint])

    matching = [assertion for assertion in merged.items[0].assertions if assertion.field == "technical_usability"]
    assert [assertion.status for assertion in matching] == ["measured"]


def test_missing_or_failed_batch_keeps_agent_fields_for_review(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 11)
    complete = tmp_path / "results" / "batch-000.json"
    complete.parent.mkdir(parents=True)
    complete.write_text(_result(manifest).model_dump_json(), encoding="utf-8")
    merged = merge_agent_batch_results(_scanner_batch(11), manifest, [complete])
    last = next(item for item in merged.items if item.material.relative_path == "trip/clip-10.mov")
    assert merged.status == "partial"
    assert merged.mode == "assisted"
    assert all(assertion.status == "measured" for assertion in last.assertions)
    assert "lighting" in last.review_required_fields

    failed = tmp_path / "results" / "batch-001.json"
    failed.write_text(AgentBatchResult(batch_id="batch-001", status="failed", items=[]).model_dump_json(), encoding="utf-8")
    failed_merge = merge_agent_batch_results(_scanner_batch(11), manifest, [complete, failed])
    failed_last = next(item for item in failed_merge.items if item.material.relative_path == "trip/clip-10.mov")
    assert failed_merge.status == "partial"
    assert "lighting" in failed_last.review_required_fields


def test_merge_rejects_scanner_material_set_that_omits_manifest_item(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 2)

    with pytest.raises(ValueError, match="exactly match manifest"):
        merge_agent_batch_results(_scanner_batch(1), manifest, [])


def test_merge_rejects_duplicate_scanner_material_id(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 1)
    duplicate = _scanner_batch(1).items[0]
    scanner = _scanner_batch(1).model_copy(update={"items": [duplicate, duplicate]})

    with pytest.raises(ValueError, match="duplicate scanner material"):
        merge_agent_batch_results(scanner, manifest, [])


@pytest.mark.parametrize("batch_items", [[0, 0], [0]], ids=["duplicate", "missing"])
def test_merge_rejects_manifest_batches_that_do_not_partition_items(
    tmp_path: Path, batch_items: list[int]
) -> None:
    manifest = _manifest(tmp_path, 2)
    bad_batch = manifest.batches[0].model_copy(
        update={"items": [manifest.items[index] for index in batch_items]}
    )
    malformed = manifest.model_copy(update={"batches": [bad_batch]})

    with pytest.raises(ValueError, match="partition manifest items"):
        merge_agent_batch_results(_scanner_batch(2), malformed, [])


def test_merge_rejects_batch_packet_that_changes_canonical_status_and_sheet(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 1)
    altered_packet = manifest.items[0].model_copy(
        update={"status": "review_required", "contact_sheet_path": None}
    )
    altered_batch = manifest.batches[0].model_copy(update={"items": [altered_packet]})
    malformed = manifest.model_copy(update={"batches": [altered_batch]})

    with pytest.raises(ValueError, match="exactly match canonical manifest packet"):
        merge_agent_batch_results(_scanner_batch(1), malformed, [])


@pytest.mark.parametrize("kind", ["batch_id", "batch_index", "result_path"])
def test_merge_rejects_duplicate_or_inconsistent_batch_reservations(
    tmp_path: Path, kind: str
) -> None:
    manifest = _manifest(tmp_path, 11)
    second = manifest.batches[1]
    first = manifest.batches[0]
    updates = {
        "batch_id": {"batch_id": first.batch_id},
        "batch_index": {"batch_index": first.batch_index},
        "result_path": {"result_path": first.result_path},
    }[kind]
    malformed = manifest.model_copy(
        update={"batches": [first, second.model_copy(update=updates)]}
    )

    with pytest.raises(ValueError, match="batch reservations"):
        merge_agent_batch_results(_scanner_batch(11), malformed, [])


def _merge_cli_fixture(tmp_path: Path) -> tuple[list[str], Path, Path, Path]:
    paths = create_visual_project(
        tmp_path / "runs", "visual", RawCreativeBrief(raw_description="test")
    )
    manifest = _manifest(tmp_path, 1)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    scanner_path = tmp_path / "scanner.json"
    scanner_path.write_text(_scanner_batch(1).model_dump_json(), encoding="utf-8")
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    (result_dir / "batch-000.json").write_text(_result(manifest).model_dump_json(), encoding="utf-8")
    args = [
        "merge-agent-batches", "--project", str(paths.root),
        "--scanner-observations", str(scanner_path), "--manifest", str(manifest_path),
        "--result-dir", str(result_dir),
    ]
    return args, paths.root, paths.clip_observations, paths.visual_drafts


def test_merge_cli_rejects_canonical_stage_output(tmp_path: Path) -> None:
    args, _project, canonical, _drafts = _merge_cli_fixture(tmp_path)
    canonical.write_bytes(b"published canonical evidence")

    result = CliRunner().invoke(app, [*args, "--output", str(canonical)])

    assert result.exit_code != 0
    assert "visual/drafts" in result.output
    assert canonical.read_bytes() == b"published canonical evidence"


def test_merge_cli_rejects_output_outside_project_drafts_and_traversal(tmp_path: Path) -> None:
    args, _project, _canonical, drafts = _merge_cli_fixture(tmp_path)
    outside = tmp_path / "outside.json"
    traversal = drafts / ".." / "clip_observations.json"

    for output in (outside, traversal):
        result = CliRunner().invoke(app, [*args, "--output", str(output)])
        assert result.exit_code != 0
        assert "visual/drafts" in result.output
        assert not output.exists()
