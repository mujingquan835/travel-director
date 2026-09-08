#!/usr/bin/env python3
"""Repository-contained validation for the travel-director Skill package."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
REQUIRED_PATHS = (
    "references/workflow.md",
    "references/visual-observation-contract.md",
    "scripts/install.py",
    "scripts/resolve_workspace.py",
)
REQUIRED_ENTRYPOINTS = (
    "$travel-director",
    "travel-director run",
    "travel-director status",
)


def _frontmatter(skill_file: Path) -> dict[str, str]:
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    try:
        _, raw, _ = text.split("---\n", 2)
    except ValueError as exc:
        raise ValueError("SKILL.md frontmatter is not closed") from exc
    result: dict[str, str] = {}
    for line in raw.strip().splitlines():
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {line}")
        key, value = (part.strip() for part in line.split(":", 1))
        if not key or not value or key in result:
            raise ValueError(f"invalid or duplicate frontmatter key: {key}")
        result[key] = value
    if set(result) != {"name", "description"}:
        raise ValueError("frontmatter must contain only name and description")
    return result


def _validate_links(root: Path) -> int:
    checked = 0
    for markdown in sorted(root.rglob("*.md")):
        for raw_target in LINK_PATTERN.findall(markdown.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith("#"):
                continue
            relative = Path(unquote(parsed.path))
            resolved = (markdown.parent / relative).resolve()
            if not resolved.is_relative_to(root) or not resolved.exists():
                raise ValueError(
                    f"broken or escaping local link in {markdown.relative_to(root)}: {target}"
                )
            checked += 1
    return checked


def validate_skill(root: Path) -> dict[str, object]:
    root = root.resolve()
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError("SKILL.md is missing")
    metadata = _frontmatter(skill_file)
    if metadata["name"] != root.name or not NAME_PATTERN.fullmatch(metadata["name"]):
        raise ValueError("frontmatter name must match the kebab-case Skill directory")
    if not 1 <= len(metadata["description"]) <= 1024:
        raise ValueError("description must contain 1 to 1024 characters")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("Skill package must not contain symlinks")
    for relative in REQUIRED_PATHS:
        if not (root / relative).is_file():
            raise ValueError(f"required Skill path is missing: {relative}")
    skill_text = skill_file.read_text(encoding="utf-8")
    for entrypoint in REQUIRED_ENTRYPOINTS:
        if entrypoint not in skill_text:
            raise ValueError(f"required Skill entrypoint is missing: {entrypoint}")
    links = _validate_links(root)
    files = sum(path.is_file() for path in root.rglob("*"))
    return {
        "schema_version": "1.0.0",
        "status": "valid",
        "skill_name": metadata["name"],
        "file_count": files,
        "validated_local_links": links,
        "validator": "repository-contained",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skill_root", nargs="?", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    try:
        result = validate_skill(Path(args.skill_root))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
