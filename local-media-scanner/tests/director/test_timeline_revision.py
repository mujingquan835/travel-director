import json
from pathlib import Path

import pytest

from director.runner import run_travel_director
from tests.director.test_creative_runner import reach_creative, snapshot
from tests.director.test_runner import BRIEF, _submit_creative


def prepared(tmp_path, monkeypatch, click_track):
    monkeypatch.setenv('TRAVEL_DIRECTOR_AUDIO_ROOT', str(tmp_path / 'absent'))
    source, parent, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, parent, BRIEF, request)
    result = run_travel_director(source, BRIEF, project=parent, music=click_track, build_timeline=True)
    assert result.status == 'completed', result.message
    return source, parent


def test_revision_reuses_evidence_and_is_idempotent(tmp_path, monkeypatch, click_track):
    source, parent = prepared(tmp_path, monkeypatch, click_track)
    before = snapshot(parent)
    def forbidden(*args, **kwargs):
        raise AssertionError('must reuse analysis')
    monkeypatch.setattr('director.audio_import.analyze_music', forbidden)
    monkeypatch.setattr('director.runner._prepare_local_scanner', forbidden)
    result = run_travel_director(source, BRIEF, project=parent, new_timeline_revision=True)
    assert result.status == 'completed', result.message
    child = Path(result.project_path)
    assert child != parent
    assert snapshot(parent) == before
    for name in ('music_structure.json', 'visual/clip_observations.json', 'generation/music_asset.json'):
        assert (child / name).read_bytes() == before[name]
    timeline = json.loads((child / 'delivery/fast_mode_timeline.json').read_text())
    assert Path(timeline['music_asset_path']).is_relative_to(child)
    saved = snapshot(child)
    repeated = run_travel_director(source, BRIEF, project=parent, new_timeline_revision=True)
    assert repeated.project_path == str(child)
    assert repeated.status == 'completed'
    assert snapshot(child) == saved
    assert snapshot(parent) == before
    receipt = json.loads((child / 'delivery/receipt.json').read_text())
    state = json.loads((child / 'project_state.json').read_text())
    assert receipt['timeline_revision_sha256'] == state['completed_artifact_hashes']['timeline_revision']


@pytest.mark.parametrize('target', ['parent', 'child'])
def test_corruption_blocks_revision(tmp_path, monkeypatch, click_track, target):
    source, parent = prepared(tmp_path, monkeypatch, click_track)
    if target == 'child':
        result = run_travel_director(source, BRIEF, project=parent, new_timeline_revision=True)
        destination = Path(result.project_path)
        file = destination / 'timeline_revision.json'
    else:
        destination = parent
        file = parent / 'delivery/timeline_delivery.md'
    file.write_text('corrupted')
    before = snapshot(destination)
    result = run_travel_director(source, BRIEF, project=parent, new_timeline_revision=True)
    assert result.status == 'blocked'
    assert snapshot(destination) == before


def test_failed_build_retries_without_reanalysis(tmp_path, monkeypatch, click_track):
    source, parent = prepared(tmp_path, monkeypatch, click_track)
    before = snapshot(parent)
    import director.delivery as delivery
    original = delivery.build_fast_mode_timeline
    def fail(*args, **kwargs):
        raise RuntimeError('interrupted build')
    monkeypatch.setattr(delivery, 'build_fast_mode_timeline', fail)
    failed = run_travel_director(source, BRIEF, project=parent, new_timeline_revision=True)
    assert failed.status == 'blocked'
    child = Path(failed.project_path)
    assert child != parent
    assert not (child / 'delivery/receipt.json').exists()
    monkeypatch.setattr(delivery, 'build_fast_mode_timeline', original)
    done = run_travel_director(source, BRIEF, project=parent, new_timeline_revision=True)
    assert done.status == 'completed', done.message
    assert done.project_path == str(child)
    assert snapshot(parent) == before


def test_algorithm_version_changes_revision_identity(tmp_path, monkeypatch, click_track):
    source, parent = prepared(tmp_path, monkeypatch, click_track)
    first = run_travel_director(source, BRIEF, project=parent, new_timeline_revision=True)
    monkeypatch.setattr('director.timeline_revision.ALGORITHM_VERSION', 'next-algorithm')
    second = run_travel_director(source, BRIEF, project=parent, new_timeline_revision=True)
    assert second.status == 'completed', second.message
    assert first.project_path != second.project_path


def test_cli_revision_flag(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from types import SimpleNamespace
    from director.cli import app
    seen = {}
    def run(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(model_dump_json=lambda **kwargs: '{}')
    monkeypatch.setattr('director.runner.run_travel_director', run)
    result = CliRunner().invoke(app, ['run', '--input', str(tmp_path), '--brief', 'trip',
                                     '--project', str(tmp_path), '--new-timeline-revision'])
    assert result.exit_code == 0, result.output
    assert seen['new_timeline_revision'] is True


def test_interrupted_receipt_is_not_completed(tmp_path, monkeypatch, click_track):
    source, parent = prepared(tmp_path, monkeypatch, click_track)
    before = snapshot(parent)
    import director.timeline_delivery_store as store
    original = store.record_supporting_artifact
    def interrupt(*args, **kwargs):
        if kwargs.get('state_key') == 'timeline_delivery_receipt':
            raise OSError('receipt interrupted')
        return original(*args, **kwargs)
    monkeypatch.setattr(store, 'record_supporting_artifact', interrupt)
    result = run_travel_director(source, BRIEF, project=parent, new_timeline_revision=True)
    assert result.status == 'blocked'
    monkeypatch.setattr(store, 'record_supporting_artifact', original)
    resumed = run_travel_director(source, BRIEF, project=parent, new_timeline_revision=True)
    # Preserve existing fail-closed receipt policy; no automatic repair of a partial delivery.
    assert resumed.status == 'blocked'
    assert snapshot(parent) == before


def test_revision_rejects_simultaneous_music_import(tmp_path, monkeypatch, click_track):
    source, parent = prepared(tmp_path, monkeypatch, click_track)
    before = snapshot(parent)
    result = run_travel_director(source, BRIEF, project=parent, music=click_track, new_timeline_revision=True)
    assert result.status == 'blocked'
    assert snapshot(parent) == before
