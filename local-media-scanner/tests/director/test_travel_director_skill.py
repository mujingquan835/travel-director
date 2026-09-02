from __future__ import annotations

import hashlib
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


def _index_or_fail(text: str, needle: str) -> int:
    index = text.find(needle)
    assert index >= 0, needle
    return index


def _manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_skill_frontmatter_and_entrypoint_contract():
    skill_text = _skill_text()
    frontmatter, body = _read_frontmatter(skill_text)

    assert frontmatter["name"] == "travel-director"
    assert "$travel-director" in skill_text
    assert "每批最多 10" in skill_text
    assert "超过 5 个字段" in skill_text
    assert "超过 3 条素材" in skill_text
    assert "external_call_count=0" in skill_text
    assert not re.search(r"^model\s*:", skill_text, re.MULTILINE)
    assert "Codex API" in skill_text and "不得调用" in skill_text

    for phrase in (
        "Resolve and validate the authoritative workspace",
        "Get the source directory and the user's natural-language description",
        "Run local Scanner preparation",
        "Read at most 10 contact sheets per batch",
        "If vision is unavailable, skip agent assertions",
        "Normalize the Brief",
        "Merge observations and route review",
        "Import confirmation JSON with hash validation",
        "Build intent decisions, project coverage, DirectorTreatment, DirectorReview, and exactly three music prompts",
        "Return compact results and clickable artifact paths",
    ):
        assert phrase in body


def test_skill_links_and_reference_invariants():
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
        "scripts/install.py",
    ):
        assert relative in skill_text

    assert "automatic" in workflow_text
    assert "assisted" in workflow_text
    assert "blocked" in workflow_text
    assert "three music prompts" in workflow_text
    assert "one final response" in workflow_text
    assert "--project" in workflow_text
    assert "visual/drafts/" in workflow_text
    assert "record-visual-stage" in workflow_text
    assert "prepare-visual-review may return `none`, `chat`, or `local_page`" in workflow_text
    assert "never opens the browser" in workflow_text
    assert "--no-models" in workflow_text
    assert "RepresentativeFrame(path,timestamp)" in workflow_text

    assert "unsupported inference" in observation_text.lower()
    assert "allowed fields" in observation_text.lower()
    assert "external_call_count" in observation_text
    assert "validate-agent-batch" in workflow_text


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


def test_workflow_reference_lists_required_commands():
    workflow_text = _workflow_text()

    for command in (
        "uv run travel-director init-visual-project --project-id <project-id> --raw-brief <raw-brief.json> --run-root <run-root>",
        "uv run travel-scanner inspect --input <source-directory> --output <project>/visual/scanner/input_manifest.json",
        "uv run travel-scanner scan --manifest <project>/visual/scanner/input_manifest.json --run-id scanner-v1 --runs-dir <project>/visual/scanner/runs --sampling-profile adaptive5 --device auto --no-models",
        "uv run travel-director build-scanner-observations --scanner-result <project>/visual/scanner/runs/scanner-v1/scanner_result.json --scanner-manifest <project>/visual/scanner/input_manifest.json --output <project>/visual/scanner_only.json",
        "uv run travel-director build-frame-map --scanner-result <project>/visual/scanner/runs/scanner-v1/scanner_result.json --scanner-observations <project>/visual/scanner_only.json --scanner-run-dir <project>/visual/scanner/runs/scanner-v1 --output <project>/visual/material_frame_map.json",
        "uv run travel-director prepare-agent-batches --frame-map <project>/visual/material_frame_map.json --output-dir <project>/visual/agent_batches",
    ):
        assert command in workflow_text


def test_workflow_reference_orders_brief_before_merge_and_review():
    workflow_text = _workflow_text()

    brief_section = _index_or_fail(workflow_text, "## Brief Normalization And Confirmation")
    review_section = _index_or_fail(workflow_text, "## Review Routing")
    normalize_brief = _index_or_fail(
        workflow_text,
        "uv run travel-director normalize-brief --brief <project>/brief.json --output <project>/visual/drafts/intent_brief.json",
    )
    merge_batches = _index_or_fail(
        workflow_text,
        "uv run travel-director merge-agent-batches --project <project> --scanner-observations <project>/visual/scanner_only.json --manifest <project>/visual/agent_batches/manifest.json --result-dir <project>/visual/agent_batches/results --output <project>/visual/drafts/clip_observations.merged.json",
    )

    assert brief_section < review_section
    assert normalize_brief < merge_batches


def test_workflow_reference_includes_manual_director_review_command_sequence():
    workflow_text = _workflow_text()

    render_review = _index_or_fail(
        workflow_text,
        "uv run travel-director render-director-review --treatment <project>/visual/director_treatment.json --output <project>/visual/review/director_review.html",
    )
    validate_review = _index_or_fail(
        workflow_text,
        "uv run travel-director validate-director-review --treatment <project>/visual/director_treatment.json --review <project>/visual/review/director_review.json",
    )
    record_review = _index_or_fail(
        workflow_text,
        "uv run travel-director record-visual-stage --project <project> --stage director_review --artifact <project>/visual/review/director_review.json",
    )

    assert render_review < validate_review < record_review
