from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "travel-director"
SKILL_FILE = SKILL_ROOT / "SKILL.md"
WORKFLOW_REF = SKILL_ROOT / "references" / "workflow.md"
OBSERVATION_REF = SKILL_ROOT / "references" / "visual-observation-contract.md"
RESOLVER = SKILL_ROOT / "scripts" / "resolve_workspace.py"
INSTALLER = SKILL_ROOT / "scripts" / "install.py"
QUICK_VALIDATOR = Path(
    "/Users/meimaodawang/.codex/skills/.system/skill-creator/scripts/quick_validate.py"
)


def _read_frontmatter(text: str) -> tuple[dict[str, str], str]:
    assert text.startswith("---\n")
    _, frontmatter_text, body = text.split("---\n", 2)
    frontmatter: dict[str, str] = {}
    for raw_line in frontmatter_text.strip().splitlines():
        key, value = raw_line.split(":", 1)
        frontmatter[key.strip()] = value.strip()
    return frontmatter, body


def _skill_text() -> str:
    return SKILL_FILE.read_text(encoding="utf-8")


def _workflow_text() -> str:
    return WORKFLOW_REF.read_text(encoding="utf-8")


def _observation_text() -> str:
    return OBSERVATION_REF.read_text(encoding="utf-8")


def _manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_skill_metadata_and_product_boundary():
    skill_text = _skill_text()
    frontmatter, body = _read_frontmatter(skill_text)

    assert frontmatter["name"] == "travel-director"
    assert "$travel-director" in skill_text
    assert "travel-director run" in skill_text
    assert "travel-director status" in skill_text
    assert "needs_visual_observation" in skill_text
    assert "needs_user_confirmation" in skill_text
    assert "waiting_for_music" in skill_text
    assert "completed" in skill_text
    assert "blocked" in skill_text
    assert "--response-file" in skill_text
    assert "external_call_count=0" in skill_text
    assert "Codex API" in skill_text

    excluded = (
        "init-visual-project",
        "record-visual-stage",
        "normalize-brief",
        "Ground Truth",
        "blind annotation",
        "evaluate-blind-annotation",
        "analyze-music",
        "render-project",
    )
    assert all(term not in body for term in excluded)


def test_skill_references_are_discoverable_and_keep_lab_commands_out():
    skill_text = _skill_text()
    workflow_text = _workflow_text()
    observation_text = _observation_text()

    assert WORKFLOW_REF.is_file()
    assert OBSERVATION_REF.is_file()
    assert RESOLVER.is_file()
    assert INSTALLER.is_file()

    for relative in (
        "references/workflow.md",
        "references/visual-observation-contract.md",
        "scripts/resolve_workspace.py",
    ):
        assert relative in skill_text

    assert '"kind": "brief"' in workflow_text
    assert '"kind": "visual"' in workflow_text
    assert "--response-file" in workflow_text
    assert "--no-models" in workflow_text
    assert "external_call_count=0" in workflow_text
    assert "waiting_for_music" in workflow_text
    assert "provide_music" in workflow_text

    excluded = (
        "record-visual-stage",
        "normalize-brief",
        "Ground Truth",
        "blind annotation",
        "evaluate-blind-annotation",
        "analyze-music",
        "render-project",
    )
    assert all(term not in workflow_text for term in excluded)

    assert "unsupported inference" in observation_text.lower()
    assert "allowed fields" in observation_text.lower()
    assert "external_call_count" in observation_text


def test_skill_passes_official_quick_validation():
    result = subprocess.run(
        ["uv", "run", "python", str(QUICK_VALIDATOR), str(SKILL_ROOT)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Skill is valid!" in result.stdout


def test_installer_copies_identical_tree(tmp_path):
    codex_home = tmp_path / "codex-home"
    subprocess.run(
        ["uv", "run", "python", str(INSTALLER), "--codex-home", str(codex_home)],
        cwd=REPO_ROOT,
        check=True,
    )

    destination = codex_home / "skills" / "travel-director"
    assert destination.is_dir()
    assert _manifest(SKILL_ROOT) == _manifest(destination)


def test_installer_refuses_different_existing_copy_without_replace(tmp_path):
    codex_home = tmp_path / "codex-home"
    destination = codex_home / "skills" / "travel-director"
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_text("different\n", encoding="utf-8")

    result = subprocess.run(
        ["uv", "run", "python", str(INSTALLER), "--codex-home", str(codex_home)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--replace" in result.stderr
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "different\n"


def test_installer_replace_creates_timestamped_backup(tmp_path):
    codex_home = tmp_path / "codex-home"
    destination = codex_home / "skills" / "travel-director"
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_text("different\n", encoding="utf-8")

    subprocess.run(
        ["uv", "run", "python", str(INSTALLER), "--codex-home", str(codex_home), "--replace"],
        cwd=REPO_ROOT,
        check=True,
    )

    backups = sorted(
        (codex_home / "skill-backups").glob("travel-director.backup-*")
    )
    assert len(backups) == 1
    assert (backups[0] / "SKILL.md").read_text(encoding="utf-8") == "different\n"
    assert not list((codex_home / "skills").glob("travel-director.backup-*"))
    assert _manifest(SKILL_ROOT) == _manifest(destination)


def test_installer_migrates_legacy_backups_out_of_skill_discovery(tmp_path):
    codex_home = tmp_path / "codex-home"
    subprocess.run(
        ["uv", "run", "python", str(INSTALLER), "--codex-home", str(codex_home)],
        cwd=REPO_ROOT,
        check=True,
    )
    legacy = codex_home / "skills" / "travel-director.backup-20260901-010203"
    legacy.mkdir()
    (legacy / "SKILL.md").write_text("legacy\n", encoding="utf-8")

    subprocess.run(
        ["uv", "run", "python", str(INSTALLER), "--codex-home", str(codex_home)],
        cwd=REPO_ROOT,
        check=True,
    )

    migrated = codex_home / "skill-backups" / legacy.name
    assert not legacy.exists()
    assert (migrated / "SKILL.md").read_text(encoding="utf-8") == "legacy\n"


def test_resolver_prefers_explicit_workspace(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                "name = \"candidate\"",
                "version = \"0.1.0\"",
                "[project.scripts]",
                "travel-scanner = \"scanner.cli:app\"",
                "travel-director = \"director.cli:app\"",
            ]
        ),
        encoding="utf-8",
    )
    (candidate / "director").mkdir()

    result = subprocess.run(
        ["uv", "run", "python", str(RESOLVER), "--workspace", str(candidate)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == str(candidate.resolve())


def test_resolver_uses_environment_when_explicit_missing(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                "name = \"candidate\"",
                "version = \"0.1.0\"",
                "[project.scripts]",
                "travel-scanner = \"scanner.cli:app\"",
                "travel-director = \"director.cli:app\"",
            ]
        ),
        encoding="utf-8",
    )
    (candidate / "director").mkdir()

    env = os.environ.copy()
    env["TRAVEL_DIRECTOR_WORKSPACE"] = str(candidate)
    result = subprocess.run(
        ["uv", "run", "python", str(RESOLVER)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == str(candidate.resolve())


def test_resolver_prefers_git_root_and_never_selects_main_when_invalid(tmp_path):
    invalid_root = tmp_path / "main"
    invalid_root.mkdir()
    subprocess.run(["git", "init"], cwd=invalid_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-b", "main"],
        cwd=invalid_root,
        check=True,
        capture_output=True,
    )
    (invalid_root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                "name = \"invalid\"",
                "version = \"0.1.0\"",
                "[project.scripts]",
                "travel-scanner = \"scanner.cli:app\"",
            ]
        ),
        encoding="utf-8",
    )

    valid_root = tmp_path / "feature"
    valid_root.mkdir()
    subprocess.run(["git", "init"], cwd=valid_root, check=True, capture_output=True)
    (valid_root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                "name = \"valid\"",
                "version = \"0.1.0\"",
                "[project.scripts]",
                "travel-scanner = \"scanner.cli:app\"",
                "travel-director = \"director.cli:app\"",
            ]
        ),
        encoding="utf-8",
    )
    (valid_root / "director").mkdir()

    result = subprocess.run(
        ["uv", "run", "python", str(RESOLVER)],
        cwd=valid_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == str(valid_root.resolve())
    assert result.stdout.strip() != str(invalid_root.resolve())
