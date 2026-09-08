from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
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
REPOSITORY_VALIDATOR = SKILL_ROOT / "scripts" / "validate.py"
QUICK_VALIDATOR = (
    Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    / "skills"
    / ".system"
    / "skill-creator"
    / "scripts"
    / "quick_validate.py"
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


def _load_installer_module():
    spec = importlib.util.spec_from_file_location("travel_director_skill_installer", INSTALLER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    assert "--music" in skill_text
    assert "waiting_for_timeline" in skill_text
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
    assert REPOSITORY_VALIDATOR.is_file()

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


def test_repository_validator_is_self_contained_and_passes():
    env = os.environ.copy()
    env["CODEX_HOME"] = str(REPO_ROOT / "does-not-exist")
    result = subprocess.run(
        ["uv", "run", "python", str(REPOSITORY_VALIDATOR), str(SKILL_ROOT)],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "valid"
    assert report["validator"] == "repository-contained"
    assert report["validated_local_links"] >= 3


def test_repository_validator_rejects_broken_local_reference(tmp_path):
    copy = tmp_path / "travel-director"
    import shutil
    shutil.copytree(SKILL_ROOT, copy)
    with (copy / "SKILL.md").open("a", encoding="utf-8") as output:
        output.write("\n[broken](references/missing.md)\n")
    result = subprocess.run(
        ["uv", "run", "python", str(copy / "scripts" / "validate.py"), str(copy)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "broken or escaping local link" in result.stderr


def test_optional_official_quick_validation_when_available():
    if not QUICK_VALIDATOR.is_file():
        pytest.skip(
            "optional official Codex validator is unavailable; "
            "repository-contained Skill validation remains mandatory"
        )
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
    receipt = json.loads(
        (codex_home / "skill-receipts" / "travel-director.json").read_text(encoding="utf-8")
    )
    assert receipt["skill_name"] == "travel-director"
    assert receipt["skill"]["files"] == _manifest(destination)
    expected_manifest_hash = hashlib.sha256(
        json.dumps(receipt["skill"]["files"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert receipt["skill"]["manifest_sha256"] == expected_manifest_hash
    assert receipt["source"]["runtime_project_version"] == "0.1.0"
    assert receipt["source"]["git_commit"] == subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


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
    receipt = json.loads(
        (codex_home / "skill-receipts" / "travel-director.json").read_text(encoding="utf-8")
    )
    assert receipt["backup_path"] == str(backups[0].resolve())


def test_installer_restores_previous_copy_when_publish_fails(tmp_path, monkeypatch):
    installer = _load_installer_module()
    codex_home = tmp_path / "codex-home"
    destination = codex_home / "skills" / "travel-director"
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_text("previous version\n", encoding="utf-8")

    def fail_publish(*_args):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(installer, "_publish_staged_skill", fail_publish)
    with pytest.raises(OSError, match="publication failure"):
        installer.install_skill(codex_home, replace=True)
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "previous version\n"
    backups = list((codex_home / "skill-backups").glob("travel-director.backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "SKILL.md").read_text(encoding="utf-8") == "previous version\n"
    assert not (codex_home / "skill-receipts" / "travel-director.json").exists()


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


def test_ci_runs_mandatory_repository_validation_and_publishes_receipt():
    workflow = (REPO_ROOT.parent / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "uv run pytest -q" in workflow
    assert workflow.count("git diff --check") == 2
    assert "scripts/validate.py skills/travel-director" in workflow
    assert "scripts/install.py --codex-home" in workflow
    assert "Official quick validator is not installed" in workflow
    assert "skill-receipts/travel-director.json" in workflow
    action_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
    assert action_lines
    assert all(re.search(r"uses: [^@]+@[0-9a-f]{40}(?:\s|$)", line) for line in action_lines)


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
