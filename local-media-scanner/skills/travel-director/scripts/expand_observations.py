#!/usr/bin/env python3
"""Expand compact visual observations into a full AgentBatchResult JSON.

The invoking agent writes a small JSON with only the visual judgments
(field, value, confidence).  This script reads the agent-batch manifest
and scanner observations to fill in every mechanical field: material
identity, SHA-256 hashes, absolute paths, evidence references, and the
full Pydantic-compatible structure that the Runner validates.

Usage (from the resolved package root):

    python3 <skill-root>/scripts/expand_observations.py \
        --manifest   <project>/visual/agent_batches/manifest.json \
        --scanner    <project>/visual/scanner_only.json \
        --batch-id   batch-000 \
        --input      /tmp/compact_batch_000.json \
        --output     <project>/visual/agent_batches/results/batch-000.json

The compact input format is documented in visual-observation-contract.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ALLOWED_FIELDS = frozenset((
    "technical_usability",
    "content_families",
    "setting",
    "lighting",
    "people_presence",
    "people_count_band",
    "subject_candidates",
    "activity_candidates",
))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_evidence_ref(
    material_id: str,
    contact_sheet_path: str,
    contact_sheet_sha256: str,
    confidence: float | None,
) -> dict:
    return {
        "material_id": material_id,
        "artifact_path": contact_sheet_path,
        "field_path": "contact_sheet",
        "frame_timestamp": None,
        "source_kind": "visual_provider",
        "status": "candidate",
        "confidence": confidence,
        "sha256": contact_sheet_sha256,
    }


def _build_assertion(
    compact: dict,
    material_id: str,
    contact_sheet_path: str,
    contact_sheet_sha256: str,
) -> dict:
    field = compact["field"]
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"unsupported assertion field: {field}")

    status = compact.get("status", "candidate")
    value = compact.get("value")
    confidence = compact.get("confidence")

    if status == "abstained":
        return {
            "field": field,
            "value": None,
            "status": "abstained",
            "confidence": None,
            "evidence_refs": [],
        }

    if status != "candidate":
        raise ValueError(f"unsupported assertion status: {status}")

    if confidence is None:
        raise ValueError(f"candidate assertion for {field} requires confidence")

    return {
        "field": field,
        "value": value,
        "status": "candidate",
        "confidence": confidence,
        "evidence_refs": [
            _build_evidence_ref(
                material_id, contact_sheet_path, contact_sheet_sha256, confidence,
            )
        ],
    }


def _find_material_ref(
    scanner_items: list[dict], relative_path: str,
) -> dict:
    for item in scanner_items:
        mat = item["material"]
        if mat["relative_path"] == relative_path:
            return mat
    raise ValueError(f"scanner observations missing material: {relative_path}")


def expand(
    manifest: dict,
    scanner_observations: dict,
    batch_id: str,
    compact_observations: dict,
) -> dict:
    # Find the batch in the manifest
    batch = None
    for b in manifest["batches"]:
        if b["batch_id"] == batch_id:
            batch = b
            break
    if batch is None:
        raise ValueError(f"batch {batch_id} not found in manifest")

    # Build lookup: relative_path -> manifest packet
    manifest_items = {item["material_id"]: item for item in manifest["items"]}
    batch_packets = {
        manifest_items[item["material_id"]]["relative_path"]: manifest_items[item["material_id"]]
        for item in batch["items"]
    }

    # Build lookup: relative_path -> compact observation
    compact_by_path = {
        item["relative_path"]: item for item in compact_observations["items"]
    }

    # Cache contact-sheet SHA-256 to avoid re-hashing
    sheet_hashes: dict[str, str] = {}

    result_items = []
    for packet in batch["items"]:
        full_packet = manifest_items[packet["material_id"]]
        relative_path = full_packet["relative_path"]
        material_id = full_packet["material_id"]

        if full_packet["status"] != "ready":
            continue

        compact_item = compact_by_path.get(relative_path)
        if compact_item is None:
            raise ValueError(
                f"compact observations missing material: {relative_path}"
            )

        # Get full MaterialRef from scanner observations
        material_ref = _find_material_ref(
            scanner_observations["items"], relative_path,
        )

        # Get contact sheet path and compute hash
        contact_sheet_path = full_packet["contact_sheet_path"]
        if contact_sheet_path is None:
            raise ValueError(
                f"ready material {relative_path} has no contact sheet"
            )
        resolved = str(Path(contact_sheet_path).resolve())
        if resolved not in sheet_hashes:
            sheet_hashes[resolved] = _sha256_file(Path(resolved))
        sheet_sha256 = sheet_hashes[resolved]

        # Expand assertions
        assertions = []
        for compact_assertion in compact_item["assertions"]:
            assertions.append(
                _build_assertion(
                    compact_assertion, material_id, resolved, sheet_sha256,
                )
            )

        result_items.append({
            "schema_version": "0.2.0",
            "material": material_ref,
            "provider": "invoking_agent",
            "observation_status": "automatic",
            "assertions": assertions,
            "unknown_fields": [],
            "review_required_fields": [],
            "errors": [],
        })

    # Quality gate: check abstention rate
    total_assertions = sum(len(item["assertions"]) for item in result_items)
    abstained_count = sum(
        1
        for item in result_items
        for a in item["assertions"]
        if a["status"] == "abstained"
    )
    if total_assertions > 0:
        abstention_rate = abstained_count / total_assertions
        if abstention_rate > 0.4:
            print(
                f"WARNING: high abstention rate {abstention_rate:.0%} "
                f"({abstained_count}/{total_assertions}); "
                f"review contact sheets for quality issues",
                file=sys.stderr,
            )

    return {
        "schema_version": "0.2.0",
        "batch_id": batch_id,
        "provider": "invoking_agent",
        "status": "completed",
        "items": result_items,
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Expand compact visual observations into AgentBatchResult."
    )
    parser.add_argument("--manifest", required=True, help="Agent batch manifest JSON")
    parser.add_argument("--scanner", required=True, help="Scanner observations JSON")
    parser.add_argument("--batch-id", required=True, help="Batch ID (e.g. batch-000)")
    parser.add_argument("--input", required=True, help="Compact observations JSON")
    parser.add_argument("--output", required=True, help="Output AgentBatchResult JSON")

    args = parser.parse_args()

    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        scanner = json.loads(Path(args.scanner).read_text(encoding="utf-8"))
        compact = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"failed to read input: {exc}", file=sys.stderr)
        return 1

    try:
        result = expand(manifest, scanner, args.batch_id, compact)
    except (ValueError, KeyError) as exc:
        print(f"expansion failed: {exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    output_path.write_text(payload, encoding="utf-8")
    print(f"wrote {output_path} ({len(payload)} bytes, {len(result['items'])} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
