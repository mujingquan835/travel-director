#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path


KNOWN_ROOT = Path("/Users/meimaodawang/Documents/旅行导演")


def _scripts_from_pyproject(pyproject_path: Path) -> dict[str, str]:
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    project = payload.get("project")
    if not isinstance(project, dict):
        return {}
    scripts = project.get("scripts")
    return scripts if isinstance(scripts, dict) else {}


def _is_valid_workspace(candidate: Path) -> bool:
    root = candidate.resolve()
    pyproject = root / "pyproject.toml"
    director_dir = root / "director"
    if not pyproject.is_file() or not director_dir.is_dir():
        return False
    scripts = _scripts_from_pyproject(pyproject)
    return {
        "travel-scanner",
        "travel-director",
    }.issubset(scripts)


def _git_root_from_cwd() -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    path = Path(result.stdout.strip())
    return path.resolve() if result.stdout.strip() else None


def _known_candidates() -> list[Path]:
    candidates: list[Path] = []
    for candidate in [
        KNOWN_ROOT / ".worktrees" / "local-media-scanner-v0.1" / "local-media-scanner",
        KNOWN_ROOT / "local-media-scanner",
        KNOWN_ROOT,
    ]:
        candidates.append(candidate)
    worktrees_root = KNOWN_ROOT / ".worktrees"
    if worktrees_root.is_dir():
        for child in sorted(worktrees_root.iterdir()):
            candidates.append(child / "local-media-scanner")
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            deduped.append(resolved)
    return deduped


def resolve_workspace(explicit: str | None) -> Path:
    ordered: list[Path] = []
    if explicit:
        ordered.append(Path(explicit))
    env_value = os.environ.get("TRAVEL_DIRECTOR_WORKSPACE")
    if env_value:
        ordered.append(Path(env_value))
    git_root = _git_root_from_cwd()
    if git_root is not None:
        ordered.append(git_root)
    ordered.extend(_known_candidates())

    seen: set[Path] = set()
    for raw_candidate in ordered:
        candidate = raw_candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if _is_valid_workspace(candidate):
            return candidate
    raise FileNotFoundError(
        "no valid travel-director workspace found; provide --workspace or set TRAVEL_DIRECTOR_WORKSPACE"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace")
    args = parser.parse_args()

    try:
        resolved = resolve_workspace(args.workspace)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(str(resolved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
