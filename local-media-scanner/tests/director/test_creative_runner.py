from pathlib import Path
import json
import pytest

import director.runner as runner_module
from director.runner import inspect_travel_director, run_travel_director
from tests.director.test_runner import BRIEF, _prepared_scanner, _write_agent_result
from tests.director.test_runner import _submit_creative


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('damage', ['missing', 'drifted', 'nonempty'])
@pytest.mark.parametrize('phase', ['submit', 'resume', 'frozen', 'version'])
def test_external_ledger_checked_before_creative_or_music_writes(tmp_path, monkeypatch, click_track, damage, phase):
    from director.project import open_project, record_supporting_artifact, ProjectConflict
    source, project, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, project, BRIEF, request)
    if phase in ('frozen', 'version'):
        assert run_travel_director(source, BRIEF, project=project, music=click_track).status == 'waiting_for_timeline'
    paths = open_project(project)
    if damage == 'missing':
        paths.external_calls.unlink()
    elif damage == 'drifted':
        paths.external_calls.write_text('[{}]')
    else:
        record_supporting_artifact(paths, paths.external_calls, [{
            'provider': 'test', 'operation': 'test', 'authorized_at': '2026-09-06',
            'call_count': 1, 'output_status': 'succeeded',
        }], state_key='external_calls')
    before = snapshot(project)
    options = {}
    if phase == 'submit':
        options['creative_response'] = Path(request.actions[0].response_path)
    elif phase == 'frozen':
        options['music'] = click_track
    elif phase == 'version':
        other = tmp_path / 'other.wav'
        other.write_bytes(click_track.read_bytes() + b'\0\0')
        options.update(music=other, new_music_version=True)
    result = run_travel_director(source, BRIEF, project=project, **options)
    assert result.status == 'blocked', result.message
    assert snapshot(project) == before
    assert not list(tmp_path.glob('project-music-*'))
    with pytest.raises((ProjectConflict, ValueError)):
        inspect_travel_director(project)


def test_creative_revisions_retry_and_fresh_library(tmp_path, monkeypatch):
    import director.creative_direction as creative_module
    source, project, request = reach_creative(tmp_path, monkeypatch)
    first = _submit_creative(source, project, BRIEF, request)
    response = Path(request.actions[0].response_path)
    before = snapshot(project)
    repeated = run_travel_director(source, BRIEF, project=project, creative_response=response)
    assert repeated.status == first.status == 'waiting_for_music'
    assert snapshot(project) == before
    monkeypatch.setattr(creative_module, 'reference_library_sha256', lambda: 'a' * 64)
    stale = run_travel_director(source, BRIEF, project=project, creative_response=response)
    assert stale.status == 'blocked'
    assert snapshot(project) == before
    refreshed = run_travel_director(source, BRIEF, project=project)
    assert refreshed.status == 'needs_creative_direction'
    assert inspect_travel_director(project).run_state == 'needs_creative_direction'
    payload = json.loads(response.read_text())
    payload['source_hashes']['reference_library'] = 'a' * 64
    payload['user_preferences'].append('新的用户偏好')
    response.write_text(json.dumps(payload, ensure_ascii=False))
    updated = run_travel_director(source, BRIEF, project=project, creative_response=response)
    assert updated.status == 'waiting_for_music', updated.message
    assert len(list((project / 'creative/revisions').iterdir())) == 2
    for name, content in before.items():
        if '/revisions/' in name or name.startswith('visual/'):
            assert (project / name).read_bytes() == content


def test_creative_corrupted_record_blocks_append(tmp_path, monkeypatch):
    source, project, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, project, BRIEF, request)
    index = project / 'creative/current.json'
    index.write_text('{}')
    before = snapshot(project)
    result = run_travel_director(source, BRIEF, project=project,
                                creative_response=Path(request.actions[0].response_path))
    assert result.status == 'blocked'
    assert 'drifted' in result.message
    assert snapshot(project) == before


def test_analysis_failure_retries_frozen_asset(tmp_path, monkeypatch, click_track):
    import director.audio_import as audio_module
    source, project, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, project, BRIEF, request)
    real_analyze = audio_module.analyze_music
    def fail(*args):
        raise RuntimeError('temporary analysis failure')
    monkeypatch.setattr(audio_module, 'analyze_music', fail)
    failed = run_travel_director(source, BRIEF, project=project, music=click_track)
    assert failed.status == 'blocked'
    frozen = snapshot(project / 'generation')
    monkeypatch.setattr(audio_module, 'analyze_music', real_analyze)
    retried = run_travel_director(source, BRIEF, project=project, music=click_track)
    assert retried.status == 'waiting_for_timeline', retried.message
    for name, content in frozen.items():
        assert (project / 'generation' / name).read_bytes() == content


def test_analysis_retry_checks_creative_integrity_before_writing(tmp_path, monkeypatch, click_track):
    import director.audio_import as audio_module
    source, project, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, project, BRIEF, request)
    real_analyze = audio_module.analyze_music
    def fail(*args):
        raise RuntimeError('temporary failure')
    monkeypatch.setattr(audio_module, 'analyze_music', fail)
    assert run_travel_director(source, BRIEF, project=project, music=click_track).status == 'blocked'
    (project / 'creative/current.json').write_text('{}')
    before = snapshot(project)
    monkeypatch.setattr(audio_module, 'analyze_music', real_analyze)
    result = run_travel_director(source, BRIEF, project=project, music=click_track)
    assert result.status == 'blocked'
    assert snapshot(project) == before


def reach_creative(tmp_path, monkeypatch):
    source = tmp_path / "input"
    source.mkdir()
    (source / "clip.mov").write_bytes(b"local source")
    project = tmp_path / "project"
    monkeypatch.setattr(runner_module, "_prepare_local_scanner", _prepared_scanner)
    first = run_travel_director(source, BRIEF, project=project)
    _write_agent_result(Path(first.actions[0].result_path), source)
    return source, project, run_travel_director(source, BRIEF, project=project)


def test_visual_completion_requires_creative_direction_without_automatic_prompts(tmp_path, monkeypatch):
    source, project, result = reach_creative(tmp_path, monkeypatch)
    assert result.status == "needs_creative_direction"
    assert result.music_prompts == []
    assert result.actions[0].kind == "draft_creative_direction"
    assert Path(result.actions[0].result_path).is_file()
    assert not (project / "visual/music_style_recommendations.json").exists()
    assert not (project / "visual/final_summary.json").exists()
    before = (project / "project_state.json").read_bytes()
    assert inspect_travel_director(project).run_state == "needs_creative_direction"
    assert run_travel_director(source, BRIEF, project=project).status == "needs_creative_direction"
    assert (project / "project_state.json").read_bytes() == before


def test_music_cannot_skip_missing_creative_plan(tmp_path, monkeypatch, click_track):
    source, project, _ = reach_creative(tmp_path, monkeypatch)
    result = run_travel_director(source, BRIEF, project=project, music=click_track)
    assert result.status == "blocked"
    assert "creative" in result.message
    assert not (project / "generation/music_asset.json").exists()


@pytest.mark.parametrize('child_damage', [None, 'external_calls.json', 'visual/clip_observations.json'])
def test_new_music_version_preserves_parent_and_reuses_evidence(tmp_path, monkeypatch, click_track, child_damage):
    import wave
    source, project, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, project, BRIEF, request)
    assert run_travel_director(source, BRIEF, project=project, music=click_track).status == 'waiting_for_timeline'
    before = snapshot(project)
    other = tmp_path / 'other.wav'
    with wave.open(str(click_track), 'rb') as original:
        params, frames = original.getparams(), original.readframes(original.getnframes())
    with wave.open(str(other), 'wb') as changed:
        changed.setparams(params)
        changed.writeframes(frames + b'\0\0' * params.nchannels * 100)
    def no_scan(*args):
        raise AssertionError('must reuse evidence without scanning')
    monkeypatch.setattr(runner_module, '_prepare_local_scanner', no_scan)
    blocked = run_travel_director(source, BRIEF, project=project, music=other)
    assert blocked.status == 'blocked'
    version = run_travel_director(source, BRIEF, project=project, music=other, new_music_version=True)
    assert version.status == 'waiting_for_timeline', version.message
    child = Path(version.project_path)
    assert child != project
    assert snapshot(project) == before
    assert (child / 'visual/clip_observations.json').read_bytes() == before['visual/clip_observations.json']
    if child_damage:
        (child / child_damage).write_text('{}')
    child_before = snapshot(child)
    retry = run_travel_director(source, BRIEF, project=project, music=other, new_music_version=True)
    if child_damage:
        assert retry.status == 'blocked'
        assert snapshot(child) == child_before
        return
    assert retry.project_path == version.project_path
    assert retry.status == 'waiting_for_timeline'
    assert snapshot(child) == child_before
    assert inspect_travel_director(child).run_state == 'waiting_for_timeline'


def test_new_music_version_requires_music_and_frozen_parent(tmp_path, monkeypatch, click_track):
    source, project, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, project, BRIEF, request)
    for music in (None, click_track):
        result = run_travel_director(source, BRIEF, project=project, music=music, new_music_version=True)
        assert result.status == 'blocked'


def test_unfrozen_legacy_augments_without_changing_visual_artifacts(tmp_path, monkeypatch):
    from tests.director.test_skill_summary import completed_project
    from director.project import open_project
    from director.skill_summary import write_skill_run_summary
    from director.creative_direction import import_creative
    from director.visual_schema import BriefConfirmation
    from tests.director.test_creative_schema import build_creative_payload
    project = completed_project(tmp_path)
    write_skill_run_summary(project)
    before = snapshot(project / 'visual')
    paths = open_project(project)
    def no_scan(*args):
        raise AssertionError('legacy must not rescan')
    monkeypatch.setattr(runner_module, '_prepare_local_scanner', no_scan)
    result = runner_module._advance_run(paths, tmp_path)
    assert result.status == 'needs_creative_direction'
    request = json.loads(Path(result.actions[0].result_path).read_text())
    treatment = json.loads(paths.director_treatment.read_text())
    payload = build_creative_payload(source_hashes=request['source_hashes'],
        brief=BriefConfirmation.model_validate(request['brief']),
        material_ids=set(treatment['core_materials']))
    response = tmp_path / 'creative.json'
    response.write_text(json.dumps(payload))
    import_creative(paths, response)
    assert runner_module._advance_run(paths, tmp_path).status == 'waiting_for_music'
    assert snapshot(project / 'visual') == before


@pytest.mark.parametrize('legacy', [True, False])
def test_frozen_projects_ignore_reference_upgrade_without_mutation(tmp_path, monkeypatch, click_track, legacy):
    from director.project import open_project
    from director.audio_import import freeze_and_analyze_music
    import director.creative_direction as creative_module
    if legacy:
        from tests.director.test_skill_summary import completed_project
        from director.skill_summary import write_skill_run_summary
        project = completed_project(tmp_path)
        write_skill_run_summary(project)
    else:
        source, project, request = reach_creative(tmp_path, monkeypatch)
        _submit_creative(source, project, BRIEF, request)
    paths = open_project(project)
    freeze_and_analyze_music(paths, click_track)
    before = snapshot(project)
    monkeypatch.setattr(creative_module, 'reference_library_sha256', lambda: 'b' * 64)
    assert runner_module._advance_run(paths, tmp_path).status == 'waiting_for_timeline'
    assert inspect_travel_director(project).run_state == 'waiting_for_timeline'
    assert snapshot(project) == before


def test_advance_to_completed_with_build_timeline(tmp_path, monkeypatch, click_track):
    source, project, request = reach_creative(tmp_path, monkeypatch)
    _submit_creative(source, project, BRIEF, request)
    frozen = run_travel_director(source, BRIEF, project=project, music=click_track)
    assert frozen.status == 'waiting_for_timeline'
    assert inspect_travel_director(project).run_state == 'waiting_for_timeline'

    completed = run_travel_director(source, BRIEF, project=project, build_timeline=True)
    assert completed.status == 'completed', completed.message
    assert completed.current_stage == 'timeline_delivery'
    assert 'timeline_delivery' in completed.artifact_paths
    assert 'timeline_markdown' in completed.artifact_paths
    assert Path(completed.artifact_paths['timeline_delivery']).is_file()
    assert Path(completed.artifact_paths['timeline_markdown']).is_file()

    # Status check confirms completed
    assert inspect_travel_director(project).run_state == 'completed'

    # Resuming without build_timeline preserves completed state
    resumed = run_travel_director(source, BRIEF, project=project)
    assert resumed.status == 'completed'

