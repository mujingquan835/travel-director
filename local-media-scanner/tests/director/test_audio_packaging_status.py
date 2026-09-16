import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from director.delivery import build_fast_mode_timeline
from director.export.markdown import render_fast_mode_markdown
from director.outro_builder import OutroConfig
from director.runner import run_travel_director
from tests.director.test_delivery import sample_structure, sample_sfx_entries
from tests.director.test_creative_runner import reach_creative, snapshot
from tests.director.test_runner import BRIEF, _submit_creative


def build(**kwargs):
    return build_fast_mode_timeline(sample_structure(), 60, '/music.wav', **kwargs)


def test_missing_role_is_reported_without_invented_fade():
    timeline = build(sfx_entries=sample_sfx_entries()[1:])
    report = timeline.audio_packaging['hook']
    assert report.status == 'no_match'
    assert 'riser' in report.reason
    md = render_fast_mode_markdown(timeline)
    assert report.reason in md
    assert '原曲直接淡入' not in md


def test_disabled_outro_distinct_from_no_match():
    timeline = build(sfx_entries=[], outro_config=OutroConfig(enable_auto_outro=False))
    assert timeline.audio_packaging['outro'].status == 'disabled'
    assert timeline.audio_packaging['hook'].status == 'no_match'


def test_unprovided_library_is_unavailable():
    timeline = build()
    assert all(x.status == 'unavailable' for x in timeline.audio_packaging.values())


def test_ready_no_match_and_deferred_outro():
    assert build(sfx_entries=sample_sfx_entries()).audio_packaging['outro'].status == 'ready'
    assert build(sfx_entries=sample_sfx_entries()[:2]).audio_packaging['outro'].status == 'no_match'
    timeline = build_fast_mode_timeline(sample_structure(), 30, '/music.wav', sfx_entries=sample_sfx_entries())
    assert timeline.audio_packaging['outro'].status == 'deferred'
    assert timeline.audio_packaging['outro'].reason in render_fast_mode_markdown(timeline)


def test_legacy_delivery_does_not_invent_status():
    from director.delivery import FastModeTimeline
    data = build().model_dump()
    data.pop('audio_packaging')
    data['schema_version'] = '1.0.0'
    legacy = FastModeTimeline.model_validate(data)
    assert legacy.audio_packaging is None
    assert '历史交付未记录音效状态' in render_fast_mode_markdown(legacy)


def test_invalid_audio_config_does_not_fall_back(tmp_path, monkeypatch):
    from director.audio_catalog import AudioCatalogUnavailable, resolve_audio_root
    monkeypatch.delenv('TRAVEL_DIRECTOR_AUDIO_ROOT', raising=False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    config = tmp_path / '.config/travel-director/audio.toml'
    config.parent.mkdir(parents=True)
    config.write_text('bad [ toml')
    with pytest.raises(AudioCatalogUnavailable, match='Audio configuration unavailable'):
        resolve_audio_root()


def test_cli_forwards_required_sfx(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from director.cli import app
    received = {}
    def run(*args, **kwargs):
        received.update(kwargs)
        return SimpleNamespace(model_dump_json=lambda **kwargs: '{}')
    monkeypatch.setattr('director.runner.run_travel_director', run)
    result = CliRunner().invoke(app, ['run', '--input', str(tmp_path), '--brief', 'trip',
        '--build-timeline', '--require-sfx', 'hook', '--require-sfx', 'outro'])
    assert result.exit_code == 0, result.output
    assert received['require_sfx'] == ('hook', 'outro')


def test_missing_ffprobe_is_resource_failure(tmp_path, monkeypatch):
    from director.audio_catalog import AudioCatalogUnavailable, scan_sfx_catalog
    (tmp_path / 'hit.wav').write_bytes(b'audio')
    def fail(*args, **kwargs):
        raise FileNotFoundError('ffprobe')
    monkeypatch.setattr('director.audio_catalog.subprocess.run', fail)
    with pytest.raises(AudioCatalogUnavailable, match='ffprobe is required'):
        scan_sfx_catalog(tmp_path)


@pytest.mark.parametrize('builder', ['build_hook_plan', 'build_outro_plan'])
def test_programming_error_is_not_optional_omission(monkeypatch, builder):
    def fail(*args, **kwargs):
        raise RuntimeError('packaging bug')
    monkeypatch.setattr('director.delivery.' + builder, fail)
    with pytest.raises(RuntimeError, match='packaging bug'):
        build(sfx_entries=sample_sfx_entries())


@pytest.mark.parametrize('failure', ['missing', 'no_match', 'bug', 'required'])
def test_runner_packaging_results(tmp_path, monkeypatch, click_track, failure):
    source, project, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, project, BRIEF, request)
    run_travel_director(source, BRIEF, project=project, music=click_track)
    monkeypatch.setenv('TRAVEL_DIRECTOR_AUDIO_ROOT', str(tmp_path / 'absent'))
    if failure in ('no_match', 'bug'):
        monkeypatch.setattr('director.audio_catalog.resolve_audio_root', lambda: tmp_path)
        def catalog(*args):
            if failure == 'bug':
                raise RuntimeError('catalog bug')
            return SimpleNamespace(sfx=[])
        monkeypatch.setattr('director.audio_catalog.build_audio_catalog', catalog)
    before = snapshot(project)
    options = {'require_sfx': ('hook',)} if failure == 'required' else {}
    result = run_travel_director(source, BRIEF, project=project, build_timeline=True, **options)
    if failure in ('bug', 'required'):
        assert result.status == 'blocked'
        assert ('catalog bug' if failure == 'bug' else 'hook') in result.message
        assert snapshot(project) == before
    else:
        assert result.status == 'completed'
        payload = json.loads(Path(result.artifact_paths['timeline_delivery']).read_text())
        report = payload['audio_packaging']['hook']
        assert report['status'] == ('unavailable' if failure == 'missing' else 'no_match')
        assert report['reason'] in result.message
        assert report['reason'] in Path(result.artifact_paths['timeline_markdown']).read_text()
        resumed = run_travel_director(source, BRIEF, project=project)
        assert resumed.message == result.message
        before = snapshot(project)
        required = run_travel_director(source, BRIEF, project=project, build_timeline=True, require_sfx=('hook',))
        assert required.status == 'blocked'
        assert snapshot(project) == before
