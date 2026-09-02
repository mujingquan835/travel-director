"""Validate bounded invoking-agent observations and merge saved checkpoints."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from director.agent_batches import AGENT_VISUAL_FIELDS, AgentBatch, AgentBatchManifest, AgentMaterialPacket
from director.project import _atomic_write, _canonical_bytes
from director.visual_schema import ClipObservation, ClipObservationBatch, ProviderIssue, VisualStrictModel


class AgentBatchResult(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    batch_id: str
    provider: Literal["invoking_agent"] = "invoking_agent"
    status: Literal["completed", "failed"]
    items: list[ClipObservation]
    errors: list[ProviderIssue] = Field(default_factory=list)


def _packet_key(packet: AgentMaterialPacket) -> tuple[str, str]:
    return packet.material_id, packet.relative_path


def _manifest_batch_index(manifest: AgentBatchManifest) -> dict[str, AgentBatch]:
    expected = {_packet_key(packet) for packet in manifest.items}
    if len(expected) != len(manifest.items):
        raise ValueError("manifest items contain duplicate material membership")
    if len({packet.material_id for packet in manifest.items}) != len(manifest.items):
        raise ValueError("manifest items contain duplicate material IDs")
    batch_ids = [batch.batch_id for batch in manifest.batches]
    batch_indexes = [batch.batch_index for batch in manifest.batches]
    result_paths = [Path(batch.result_path).resolve() for batch in manifest.batches]
    if (
        len(batch_ids) != len(set(batch_ids))
        or set(batch_indexes) != set(range(len(manifest.batches)))
        or len(result_paths) != len(set(result_paths))
        or any(batch.batch_id != f"batch-{batch.batch_index:03d}" for batch in manifest.batches)
        or any(Path(batch.result_path).name != f"{batch.batch_id}.json" for batch in manifest.batches)
    ):
        raise ValueError("manifest batch reservations are not unique and consistent")
    canonical_packets = {packet.material_id: packet for packet in manifest.items}
    by_material: dict[str, AgentBatch] = {}
    for batch in manifest.batches:
        for packet in batch.items:
            key = _packet_key(packet)
            if (
                key not in expected
                or canonical_packets.get(packet.material_id) != packet
            ):
                raise ValueError("batch packet must exactly match canonical manifest packet")
            if packet.material_id in by_material:
                raise ValueError("manifest batches must partition manifest items exactly once")
            by_material[packet.material_id] = batch
    if set(by_material) != {packet.material_id for packet in manifest.items}:
        raise ValueError("manifest batches must partition manifest items exactly once")
    return by_material


def _batch(manifest: AgentBatchManifest, batch_id: str) -> AgentBatch:
    _manifest_batch_index(manifest)
    for batch in manifest.batches:
        if batch.batch_id == batch_id:
            return batch
    raise ValueError(f"result batch is not assigned by manifest: {batch_id}")


def _packet_by_material(batch) -> dict[str, AgentMaterialPacket]:
    return {packet.material_id: packet for packet in batch.items}


def _assert_contact_sheet_evidence(item: ClipObservation, packet: AgentMaterialPacket) -> None:
    expected = Path(packet.contact_sheet_path or "").resolve()
    expected_hash = hashlib.sha256(expected.read_bytes()).hexdigest()
    for assertion in item.assertions:
        if assertion.field not in AGENT_VISUAL_FIELDS:
            raise ValueError(f"agent assertion field is not allowed: {assertion.field}")
        if assertion.status not in {"candidate", "abstained"}:
            raise ValueError(f"agent assertion status is not allowed: {assertion.status}")
        if assertion.status != "candidate":
            continue
        matching = False
        for evidence in assertion.evidence_refs:
            if evidence.material_id != packet.material_id:
                raise ValueError("agent evidence references an unrelated material")
            if Path(evidence.artifact_path).resolve() != expected:
                raise ValueError("agent candidate evidence must reference its packet contact sheet")
            if evidence.source_kind != "visual_provider":
                raise ValueError("agent candidate evidence must be visual_provider evidence")
            if evidence.sha256 != expected_hash:
                raise ValueError("agent candidate contact sheet hash does not match packet")
            matching = True
        if not matching:
            raise ValueError("agent candidate requires contact sheet evidence")


def validate_agent_batch_result(
    manifest: AgentBatchManifest, result: AgentBatchResult
) -> AgentBatchResult:
    """Reject observations outside the manifest's material and evidence bounds."""

    batch = _batch(manifest, result.batch_id)
    packets = _packet_by_material(batch)
    if result.status == "failed":
        if result.items:
            raise ValueError("failed agent result must not contain material items")
        return result

    ready_ids = {packet.material_id for packet in batch.items if packet.status == "ready"}
    seen: set[str] = set()
    for item in result.items:
        material_id = item.material.material_id
        packet = packets.get(material_id)
        if packet is None:
            raise ValueError(f"agent result material is not assigned to batch: {material_id}")
        if item.material.relative_path != packet.relative_path:
            raise ValueError("agent result material path does not match packet")
        if packet.status != "ready":
            raise ValueError("agent result must not fabricate assertions for review-required material")
        if material_id in seen:
            raise ValueError(f"agent result contains duplicate material: {material_id}")
        seen.add(material_id)
        _assert_contact_sheet_evidence(item, packet)
    missing = ready_ids - seen
    if missing:
        raise ValueError(f"agent result is missing ready material: {sorted(missing)[0]}")
    return result


def write_agent_batch_checkpoint(result: AgentBatchResult, path: Path) -> Path:
    """Create an immutable canonical checkpoint, or reuse equivalent saved bytes."""

    target = path.resolve()
    payload = _canonical_bytes(result.model_dump(mode="json"))
    if target.exists():
        try:
            existing = AgentBatchResult.model_validate_json(target.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise ValueError(f"malformed checkpoint: {target}") from exc
        if existing.model_dump(mode="json") != result.model_dump(mode="json"):
            raise ValueError(f"existing checkpoint differs: {target}")
        return target
    _atomic_write(target, payload)
    return target


def _load_checkpoint(path: Path) -> AgentBatchResult:
    try:
        return AgentBatchResult.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise ValueError(f"malformed checkpoint: {path}") from exc


def _dedupe_assertions(assertions):
    deduped = []
    seen = set()
    for assertion in assertions:
        refs = []
        refs_seen = set()
        for evidence in assertion.evidence_refs:
            key = json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            if key not in refs_seen:
                refs_seen.add(key)
                refs.append(evidence)
        assertion = assertion.model_copy(update={"evidence_refs": refs})
        key = json.dumps(assertion.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            deduped.append(assertion)
    return deduped


def merge_agent_batch_results(
    scanner_observations: ClipObservationBatch,
    manifest: AgentBatchManifest,
    result_paths: list[Path],
) -> ClipObservationBatch:
    """Merge immutable checkpoints without changing Scanner measurements."""

    batch_by_material = _manifest_batch_index(manifest)
    manifest_keys = {_packet_key(packet) for packet in manifest.items}
    scanner_ids = [item.material.material_id for item in scanner_observations.items]
    if len(scanner_ids) != len(set(scanner_ids)):
        raise ValueError("duplicate scanner material ID")
    scanner_keys = {
        (item.material.material_id, item.material.relative_path)
        for item in scanner_observations.items
    }
    if scanner_keys != manifest_keys:
        raise ValueError("scanner observations must exactly match manifest materials")

    results: dict[str, AgentBatchResult] = {}
    for path in result_paths:
        result = _load_checkpoint(path)
        validate_agent_batch_result(manifest, result)
        if result.batch_id in results:
            raise ValueError(f"duplicate checkpoint for batch: {result.batch_id}")
        results[result.batch_id] = result

    packets = {packet.material_id: packet for packet in manifest.items}
    agent_items = {
        item.material.material_id: item
        for result in results.values()
        if result.status == "completed"
        for item in result.items
    }
    unavailable_batches = {
        batch.batch_id
        for batch in manifest.batches
        if batch.batch_id not in results or results[batch.batch_id].status == "failed"
    }
    merged_items: list[ClipObservation] = []
    has_review = bool(unavailable_batches)
    for scanner_item in scanner_observations.items:
        packet = packets.get(scanner_item.material.material_id)
        if packet is None or packet.relative_path != scanner_item.material.relative_path:
            raise ValueError("scanner observation is not represented by the agent manifest")
        batch = batch_by_material[packet.material_id]
        agent_item = agent_items.get(packet.material_id)
        measured_fields = {
            assertion.field for assertion in scanner_item.assertions if assertion.status == "measured"
        }
        agent_assertions = [
            assertion for assertion in agent_item.assertions if assertion.field not in measured_fields
        ] if agent_item else []
        replacement_fields = {assertion.field for assertion in agent_assertions}
        assertions = [
            assertion
            for assertion in scanner_item.assertions
            if assertion.status == "measured" or assertion.field not in replacement_fields
        ]
        if agent_assertions:
            assertions.extend(agent_assertions)
        resolved_fields = {
            assertion.field
            for assertion in agent_assertions
            if assertion.status == "candidate"
        }
        abstained_fields = {
            assertion.field
            for assertion in agent_assertions
            if assertion.status == "abstained"
        }
        review_fields = set(scanner_item.review_required_fields) - resolved_fields
        unknown_fields = set(scanner_item.unknown_fields) - resolved_fields
        errors = list(scanner_item.errors)
        if packet.status != "ready" or batch.batch_id in unavailable_batches:
            review_fields.update(AGENT_VISUAL_FIELDS)
            unknown_fields.update(AGENT_VISUAL_FIELDS)
            errors.append(ProviderIssue(
                code="agent_batch_unavailable",
                message="No completed contact-sheet result is available for this material.",
            ))
        else:
            review_fields.update(abstained_fields)
            unknown_fields.update(abstained_fields)
        if review_fields:
            has_review = True
        merged_items.append(scanner_item.model_copy(update={
            "provider": "invoking_agent" if agent_assertions else scanner_item.provider,
            "observation_status": "assisted" if review_fields else "automatic",
            "assertions": _dedupe_assertions(assertions),
            "unknown_fields": sorted(unknown_fields),
            "review_required_fields": sorted(review_fields),
            "errors": errors,
        }))
    return ClipObservationBatch(
        status="partial" if has_review else "completed",
        mode="assisted" if has_review else "automatic",
        items=sorted(merged_items, key=lambda item: item.material.relative_path),
    )
