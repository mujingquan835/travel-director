#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


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


def _package_at(path: Path) -> Path | None:
    root = path.expanduser().resolve()
    for candidate in (root, root / "local-media-scanner"):
        if _is_valid_workspace(candidate):
            return candidate.resolve()
    return None


def _configured_package(value: str, source: str) -> Path:
    package = _package_at(Path(value)) if value.strip() else None
    if package is None:
        raise FileNotFoundError(f"invalid {source}: {value!r}; expected a package or repository root; no fallback performed")
    return package


def _registered_worktrees(git_root: Path | None) -> list[Path]:
    if git_root is None:
        return []
    try:
        result = subprocess.run(
            ["git", "-C", str(git_root), "worktree", "list", "--porcelain", "-z"],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [Path(field[len("worktree "):]) for field in result.stdout.split("\0")
            if field.startswith("worktree ")]


def resolve_workspace(explicit: str | None) -> Path:
    # An installed Skill is bound to the runtime published by its installer.
    # Never substitute the current checkout just because it has CLI entrypoints.
    script = Path(__file__).resolve()
    home = script.parents[3]
    receipt_path = home / "skill-receipts" / "travel-director.json"
    if script.parents[2].name == "skills" and not (home / "pyproject.toml").is_file() and not receipt_path.is_file():
        raise ValueError("installed Skill receipt missing; reinstall intended release; no fallback performed")
    if script.parents[2].name == "skills" and receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if Path(receipt["skill"]["installed_root"]).resolve() == script.parents[1]:
            for name, digest in receipt["skill"]["files"].items():
                file = script.parents[1] / name
                if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                    raise ValueError("installed Skill differs from receipt; reinstall intended release")
            binding = receipt["source"]
            configured = explicit if explicit is not None else os.environ.get("TRAVEL_DIRECTOR_WORKSPACE")
            package = _configured_package(
                configured if configured is not None else binding["runtime_package_root"],
                "installed runtime binding",
            )
            expected = binding.get("runtime_files")
            if not expected:
                raise ValueError("installed receipt lacks runtime hashes; reinstall Skill from the intended runtime")
            actual = {
                p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in ("director", "scanner")
                for p in sorted((package / folder).rglob("*.py"))
            }
            if actual != expected:
                raise ValueError("runtime differs from installed Skill binding; reinstall after validation; no fallback performed")
            return package
    if explicit is not None:
        return _configured_package(explicit, "--workspace")
    env_value = os.environ.get("TRAVEL_DIRECTOR_WORKSPACE")
    if env_value is not None:
        return _configured_package(env_value, "TRAVEL_DIRECTOR_WORKSPACE")
    git_root = _git_root_from_cwd()
    current = _package_at(git_root if git_root is not None else Path.cwd())
    if current is not None:
        return current

    # Only discover related checkouts and the package containing this script.
    # No author-machine paths or preferred branch names are embedded here.
    candidates = set()
    for root in [*_registered_worktrees(git_root), *Path(__file__).resolve().parents]:
        package = _package_at(root)
        if package is not None:
            candidates.add(package)
    if len(candidates) == 1:
        return candidates.pop()
    if len(candidates) > 1:
        choices = "\n".join(str(path) for path in sorted(candidates))
        raise FileNotFoundError(
            f"ambiguous travel-director workspaces; select --workspace explicitly:\n{choices}"
        )
    raise FileNotFoundError(
        "no valid travel-director workspace found; provide --workspace or set TRAVEL_DIRECTOR_WORKSPACE"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace")
    args = parser.parse_args()

    try:
        resolved = resolve_workspace(args.workspace)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(str(resolved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
