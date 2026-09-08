from itertools import permutations
from pathlib import Path

import pytest

from director.outro_builder import select_outro_sfx
from tests.director.test_delivery import sample_sfx_entries, sample_structure
from director.delivery import build_fast_mode_timeline


@pytest.mark.parametrize('behavior,role,name', [
    ('hard_stop', 'outro_hit', 'Deep Hit'),
    ('decay', 'outro_piano', 'Piano'),
    ('fade', 'outro_hit', 'Event Horizon'),
])
def test_outro_order_independent(behavior, role, name):
    source = sample_sfx_entries()[-1]
    entries = [source.model_copy(update={'role': role, 'name': name, 'relative_path': path})
               for path in ('z.wav', 'a.wav', 'b.wav')]
    assert {select_outro_sfx(behavior, list(order)) for order in permutations(entries)} == {'a.wav'}


def test_frozen_assets_survive_library_replacement_and_detect_damage(tmp_path, click_track):
    from director.sfx_assets import freeze_sfx_assets, validate_sfx_assets
    from director.project import ProjectConflict
    library = tmp_path / 'library'
    project = tmp_path / 'project'
    timeline = build_fast_mode_timeline(sample_structure(), 60, '/music.wav', sfx_entries=sample_sfx_entries())
    for entry in sample_sfx_entries():
        file = library / entry.relative_path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(click_track.read_bytes())
    frozen = freeze_sfx_assets(timeline, library, project)
    assert len(frozen.sfx_assets) == 3
    sources = validate_sfx_assets(frozen, project)
    assert set(sources) == {'hook_riser', 'hook_hit', 'outro'}
    for entry in sample_sfx_entries():
        (library / entry.relative_path).write_bytes(b'replaced')
    assert validate_sfx_assets(frozen, project) == sources
    sources['hook_hit'].write_bytes(b'damaged')
    with pytest.raises(ProjectConflict, match='SFX'):
        validate_sfx_assets(frozen, project)


def test_missing_source_blocks_freezing(tmp_path):
    from director.sfx_assets import freeze_sfx_assets
    timeline = build_fast_mode_timeline(sample_structure(), 60, '/music.wav', sfx_entries=sample_sfx_entries())
    with pytest.raises((OSError, ValueError)):
        freeze_sfx_assets(timeline, tmp_path / 'absent', tmp_path / 'project')


@pytest.mark.parametrize('damage', ['missing', 'changed'])
def test_runner_checks_frozen_bytes_on_resume(tmp_path, monkeypatch, click_track, damage):
    import json
    from types import SimpleNamespace
    from director.runner import run_travel_director
    from tests.director.test_creative_runner import reach_creative, snapshot
    from tests.director.test_runner import BRIEF, _submit_creative
    source, project, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, project, BRIEF, request)
    run_travel_director(source, BRIEF, project=project, music=click_track)
    library = tmp_path / 'effects'
    for entry in sample_sfx_entries():
        file = library / entry.relative_path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(click_track.read_bytes())
    monkeypatch.setattr('director.audio_catalog.resolve_audio_root', lambda: library)
    monkeypatch.setattr('director.audio_catalog.build_audio_catalog', lambda *args:
                        SimpleNamespace(sfx=sample_sfx_entries(), sfx_root=str(library)))
    result = run_travel_director(source, BRIEF, project=project, build_timeline=True)
    assert result.status == 'completed', result.message
    data = json.loads(Path(result.artifact_paths['timeline_delivery']).read_text())
    assert data['schema_version'] == '1.2.0'
    before = snapshot(project)
    for entry in sample_sfx_entries():
        (library / entry.relative_path).unlink()
    assert run_travel_director(source, BRIEF, project=project).status == 'completed'
    assert snapshot(project) == before
    frozen = project / data['sfx_assets'][0]['frozen_relative_path']
    if damage == 'missing':
        frozen.unlink()
    else:
        frozen.write_bytes(b'changed')
    damaged = snapshot(project)
    resumed = run_travel_director(source, BRIEF, project=project)
    assert resumed.status == 'blocked'
    assert 'SFX' in resumed.message
    assert snapshot(project) == damaged


def test_source_traversal_rejected(tmp_path):
    from director.sfx_assets import freeze_sfx_assets
    from director.project import ProjectConflict
    timeline = build_fast_mode_timeline(sample_structure(), 60, '/music.wav', sfx_entries=sample_sfx_entries())
    timeline.hook_plan.riser_path = '../outside.wav'
    with pytest.raises(ProjectConflict, match='outside library'):
        freeze_sfx_assets(timeline, tmp_path, tmp_path / 'project')
