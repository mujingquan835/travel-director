#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
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


def _manifest_sha256(manifest: dict[str, str]) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _git_value(package_root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(package_root), *args], check=False, capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _source_version(source: Path) -> dict[str, object]:
    package_root = source.parents[1]
    pyproject = package_root / "pyproject.toml"
    project_version = None
    if pyproject.is_file():
        project_version = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("version")
    repository_root = _git_value(package_root, "rev-parse", "--show-toplevel")
    commit = _git_value(package_root, "rev-parse", "HEAD")
    dirty_output = _git_value(package_root, "status", "--porcelain")
    return {
        "repository_root": repository_root,
        "git_commit": commit,
        "git_dirty": None if dirty_output is None else bool(dirty_output),
        "runtime_package_root": str(package_root.resolve()),
        "runtime_project_version": project_version,
        "runtime_pyproject_sha256": (
            hashlib.sha256(pyproject.read_bytes()).hexdigest() if pyproject.is_file() else None
        ),
    }


def _release_receipt(
    source: Path,
    destination: Path,
    manifest: dict[str, str],
    backup: Path | None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "skill_name": SKILL_NAME,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "source": _source_version(source),
        "skill": {
            "source_root": str(source.resolve()),
            "installed_root": str(destination.resolve()),
            "manifest_sha256": _manifest_sha256(manifest),
            "files": manifest,
        },
        "backup_path": str(backup.resolve()) if backup is not None else None,
    }


def _write_release_receipt(
    codex_home: Path,
    source: Path,
    destination: Path,
    manifest: dict[str, str],
    backup: Path | None,
) -> Path:
    receipt = _release_receipt(source, destination, manifest, backup)
    path = codex_home.resolve() / "skill-receipts" / f"{SKILL_NAME}.json"
    payload = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _atomic_write(path, payload)
    return path


def _publish_staged_skill(staged_skill: Path, destination: Path) -> None:
    staged_skill.replace(destination)


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
            _write_release_receipt(codex_home, source, destination, source_manifest, None)
            return destination
        if not replace:
            raise RuntimeError(
                f"differing destination already exists: {destination}; rerun with --replace"
            )

    staging_root = Path(
        tempfile.mkdtemp(prefix=f".{SKILL_NAME}.stage-", dir=destination_parent)
    )
    staged_skill = staging_root / SKILL_NAME
    backup: Path | None = None
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

        try:
            _publish_staged_skill(staged_skill, destination)
            published_manifest = _file_manifest(destination)
            if published_manifest != source_manifest:
                raise RuntimeError("published manifest does not match source manifest")
            _write_release_receipt(
                codex_home, source, destination, published_manifest, backup,
            )
            return destination
        except Exception:
            if backup is not None and backup.exists():
                if destination.exists():
                    shutil.rmtree(destination, ignore_errors=True)
                _copy_tree(backup, destination)
            elif destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            raise
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
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(str(installed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
