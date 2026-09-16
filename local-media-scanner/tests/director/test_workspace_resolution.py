"""Resolver behavior in isolated checkouts, without author-machine paths."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[2] / 'skills/travel-director/scripts/resolve_workspace.py'


def package(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'director').mkdir()
    (root / 'pyproject.toml').write_text(
        '[project.scripts]\ntravel-scanner="scanner.cli:app"\ntravel-director="director.cli:app"\n'
    )
    return root


def invoke(tmp_path, cwd, *args, configured=None):
    script = tmp_path / 'installed/resolve_workspace.py'
    script.parent.mkdir(exist_ok=True)
    shutil.copy2(SOURCE, script)
    env = os.environ.copy()
    env.pop('TRAVEL_DIRECTOR_WORKSPACE', None)
    if configured is not None:
        env['TRAVEL_DIRECTOR_WORKSPACE'] = str(configured)
    return subprocess.run([sys.executable, str(script), *args], cwd=cwd,
                          env=env, capture_output=True, text=True)


@pytest.mark.parametrize('kind', ['explicit', 'environment'])
def test_invalid_configuration_never_falls_back(tmp_path, kind):
    valid = package(tmp_path / 'valid')
    missing = tmp_path / 'missing'
    args = ('--workspace', str(missing)) if kind == 'explicit' else ()
    result = invoke(tmp_path, valid, *args,
                    configured=valid if kind == 'explicit' else missing)
    assert result.returncode == 1
    assert result.stdout == ''
    assert str(missing) in result.stderr


@pytest.mark.parametrize('kind', ['explicit', 'environment', 'cwd'])
def test_repository_root_resolves_package(tmp_path, kind):
    repo = tmp_path / 'repo'
    expected = package(repo / 'local-media-scanner')
    args = ('--workspace', str(repo)) if kind == 'explicit' else ()
    result = invoke(tmp_path, repo, *args, configured=repo if kind == 'environment' else None)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected)


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True)


def worktrees(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init')
    git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
        'commit', '--allow-empty', '-m', 'fixture')
    children = []
    for name in ('first checkout', 'second'):
        child = tmp_path / name
        git(repo, 'worktree', 'add', '--detach', str(child))
        package(child / 'local-media-scanner')
        children.append(child)
    return repo, children


def test_multiple_fallback_worktrees_require_selection(tmp_path):
    repo, children = worktrees(tmp_path)
    result = invoke(tmp_path, repo)
    assert result.returncode == 1
    assert 'ambiguous' in result.stderr
    assert all(str(child / 'local-media-scanner') in result.stderr for child in children)


def test_current_checkout_wins_over_other_worktrees(tmp_path):
    _, children = worktrees(tmp_path)
    nested = children[1] / 'docs'
    nested.mkdir()
    result = invoke(tmp_path, nested)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(children[1] / 'local-media-scanner')


def test_no_workspace_does_not_search_author_machine(tmp_path):
    result = invoke(tmp_path, tmp_path)
    assert result.returncode == 1
    assert result.stdout == ''


def test_unique_registered_worktree_is_discovered(tmp_path):
    repo, children = worktrees(tmp_path)
    shutil.rmtree(children[1] / 'local-media-scanner')
    result = invoke(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(children[0] / 'local-media-scanner')


def test_explicit_workspace_overrides_invalid_environment(tmp_path):
    expected = package(tmp_path / 'selected')
    result = invoke(tmp_path, tmp_path, '--workspace', str(expected),
                    configured=tmp_path / 'missing')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected)


@pytest.mark.parametrize('value', ['', 'broken'])
def test_invalid_existing_configuration_fails(tmp_path, value):
    valid = package(tmp_path / 'valid')
    if value:
        broken = tmp_path / value
        broken.mkdir()
        (broken / 'pyproject.toml').write_text('not valid toml [')
        value = str(broken)
    result = invoke(tmp_path, valid, configured=value)
    assert result.returncode == 1
    assert 'TRAVEL_DIRECTOR_WORKSPACE' in result.stderr
    assert result.stdout == ''
