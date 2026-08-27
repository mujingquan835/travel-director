"""Deterministic cache identities and immutable scanner run directories."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from scanner.config import ScanConfig
from scanner.schema import ManifestEntry
from scanner.telemetry import collect_environment


def cache_key(
    entry: ManifestEntry,
    config: ScanConfig,
    model_revisions: Mapping[str, str],
) -> str:
    payload = {
        "entry": entry.model_dump(mode="json"),
        "config": config.model_dump(mode="json"),
        "model_revisions": dict(sorted(model_revisions.items())),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class RunPaths:
    root: Path
    frames: Path
    evidence: Path
    cache_links: Path
    logs: Path


def config_hash(config: ScanConfig) -> str:
    encoded = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def create_run_dir(
    base: Path,
    run_id: str,
    config: ScanConfig,
    *,
    resume: bool = False,
) -> RunPaths:
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run_id must be one safe path component")
    root = base / run_id
    if root.exists():
        if not resume:
            raise FileExistsError(f"run already exists: {root}")
        stored = json.loads((root / "run_config.json").read_text(encoding="utf-8"))
        if stored.get("config_hash") != config_hash(config):
            raise ValueError("cannot resume a run with a different config")
    frames = root / "frames"
    evidence = root / "evidence"
    cache_links = root / "cache-links"
    logs = root / "logs"
    for path in (frames, evidence, cache_links, logs):
        path.mkdir(parents=True, exist_ok=resume)
    if not resume:
        (root / "run_config.json").write_text(
            json.dumps(
                {"config_hash": config_hash(config), "config": config.model_dump(mode="json")},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (root / "environment.json").write_text(
            json.dumps(collect_environment(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return RunPaths(
        root=root,
        frames=frames,
        evidence=evidence,
        cache_links=cache_links,
        logs=logs,
    )
