#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path


SKILL_NAME = "travel-director"


def _source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _file_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            manifest[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return manifest


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, copy_function=shutil.copy2)


def _backup_path(backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return backup_root / f"{SKILL_NAME}.backup-{timestamp}"


def _migrate_legacy_backups(skills_root: Path, backup_root: Path) -> None:
    legacy_backups = sorted(skills_root.glob(f"{SKILL_NAME}.backup-*"))
    if not legacy_backups:
        return
    backup_root.mkdir(parents=True, exist_ok=True)
    for legacy in legacy_backups:
        destination = backup_root / legacy.name
        if destination.exists():
            raise RuntimeError(f"backup destination already exists: {destination}")
        legacy.replace(destination)


def install_skill(codex_home: Path, *, replace: bool) -> Path:
    source = _source_root()
    source_manifest = _file_manifest(source)
    destination_parent = codex_home.resolve() / "skills"
    destination_parent.mkdir(parents=True, exist_ok=True)
    backup_root = codex_home.resolve() / "skill-backups"
    _migrate_legacy_backups(destination_parent, backup_root)
    destination = destination_parent / SKILL_NAME

    if destination.exists():
        if not destination.is_dir():
            raise RuntimeError(f"destination exists but is not a directory: {destination}")
        destination_manifest = _file_manifest(destination)
        if destination_manifest == source_manifest:
            return destination
        if not replace:
            raise RuntimeError(
                f"differing destination already exists: {destination}; rerun with --replace"
            )

    staging_root = Path(
        tempfile.mkdtemp(prefix=f".{SKILL_NAME}.stage-", dir=destination_parent)
    )
    staged_skill = staging_root / SKILL_NAME
    try:
        _copy_tree(source, staged_skill)
        staged_manifest = _file_manifest(staged_skill)
        if staged_manifest != source_manifest:
            raise RuntimeError("staging manifest does not match source manifest")

        if destination.exists():
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = _backup_path(backup_root)
            if backup.exists():
                raise RuntimeError(f"backup destination already exists: {backup}")
            destination.replace(backup)

        staged_skill.replace(destination)
        published_manifest = _file_manifest(destination)
        if published_manifest != source_manifest:
            raise RuntimeError("published manifest does not match source manifest")
        return destination
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-home", required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    try:
        installed = install_skill(Path(args.codex_home), replace=args.replace)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(str(installed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
