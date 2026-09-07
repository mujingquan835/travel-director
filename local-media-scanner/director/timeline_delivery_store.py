"""Record and validate both files of a timeline delivery before reporting completion."""
from __future__ import annotations

import json
from pathlib import Path

from director.delivery import FastModeTimeline
from director.export.markdown import render_fast_mode_markdown
from director.project import (
    ProjectConflict, ProjectPaths, _atomic_write, _canonical_bytes, _sha256_bytes,
    _sha256_file, load_project_state, record_supporting_artifact,
)


def delivery_paths(paths: ProjectPaths) -> tuple[Path, Path, Path]:
    root = paths.root / "delivery"
    return root / "fast_mode_timeline.json", root / "timeline_delivery.md", root / "receipt.json"


def validate_timeline_delivery(paths: ProjectPaths) -> FastModeTimeline:
    timeline_path, markdown_path, receipt_path = delivery_paths(paths)
    state = load_project_state(paths)
    for key, path in (("timeline_delivery", timeline_path),
                      ("timeline_delivery_receipt", receipt_path)):
        expected = state.completed_artifact_hashes.get(key)
        if not expected:
            raise ProjectConflict(f"timeline delivery is not verified: missing {key} record")
        if not path.is_file() or _sha256_file(path) != expected:
            raise ProjectConflict(f"timeline delivery missing or drifted: {key}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("schema_version") != "1.0.0"
            or receipt.get("timeline_sha256") != _sha256_file(timeline_path)
            or not markdown_path.is_file()
            or receipt.get("markdown_sha256") != _sha256_file(markdown_path)):
        raise ProjectConflict("timeline delivery missing or drifted: timeline_markdown or receipt")
    return FastModeTimeline.model_validate_json(timeline_path.read_text(encoding="utf-8"))


def record_timeline_delivery(paths: ProjectPaths, timeline: FastModeTimeline) -> tuple[Path, Path]:
    timeline_path, markdown_path, receipt_path = delivery_paths(paths)
    markdown = render_fast_mode_markdown(timeline).encode("utf-8")
    receipt = {"schema_version": "1.0.0",
               "timeline_sha256": _sha256_bytes(_canonical_bytes(timeline.model_dump(mode="json"))),
               "markdown_sha256": _sha256_bytes(markdown)}
    # Never overwrite an earlier or partially written delivery with different content.
    for path, expected in ((timeline_path, receipt["timeline_sha256"]),
                           (markdown_path, receipt["markdown_sha256"]),
                           (receipt_path, _sha256_bytes(_canonical_bytes(receipt)))):
        if path.exists() and (not path.is_file() or _sha256_file(path) != expected):
            raise ProjectConflict(f"existing timeline delivery differs: {path.name}")
    if not markdown_path.exists():
        _atomic_write(markdown_path, markdown)
    record_supporting_artifact(paths, timeline_path, timeline, state_key="timeline_delivery")
    record_supporting_artifact(paths, receipt_path, receipt, state_key="timeline_delivery_receipt")
    validate_timeline_delivery(paths)
    return timeline_path, markdown_path
