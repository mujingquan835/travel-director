"""Regression guard for corrected R06: planning only, never media editing."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from director.music_visual_guide import build_guide, record_guide
from director.project import ProjectConflict, open_project
from director.runner import run_travel_director
from tests.director.test_runner import BRIEF
from tests.director.test_timeline_revision import prepared
from tests.director.test_creative_runner import snapshot
from tests.director.test_delivery import sample_structure


def direction():
    return NS(target_duration_seconds=60., sections=[
        NS(section_id='part-1', start=0., end=60., narrative_task='进入与探索',
           visual_plan='环境建立后观察人物动作', climax=True, material_gaps=['缺少收束画面'],
           music_change='推进后收束', sfx_plan=['局部留白'])
    ])


def test_guidance_preserves_uncertainty_and_never_assigns_clips():
    music = sample_structure()
    music.confidence = .2
    guide = build_guide(direction(), music)
    row = guide['sections'][0]
    assert '待试听' in row['pacing_suggestion']
    assert row['material_gaps'] == ['缺少收束画面']
    assert row['picture_suggestion'] == '环境建立后观察人物动作'
    assert guide['music_edited'] is guide['footage_edited'] is False
    serialized = json.dumps(guide)
    for key in ('source_in', 'source_out', 'placement', 'selected_material', 'preview.mp4'):
        assert key not in serialized
    assert row['beat_references'] == [t for t in music.beats_seconds if 0 <= t < 60]


def test_local_fast_cuts_are_proposals_with_evidence():
    from director.schema import MusicStructureSection
    music = sample_structure()
    music.confidence = .9
    music.sections = [MusicStructureSection(start=0,end=60,role='climax',energy=.9,confidence=.9)]
    guide = build_guide(direction(),music)
    assert '可尝试局部快切' in guide['sections'][0]['pacing_suggestion']
    assert '试听复核' in guide['sections'][0]['suggestion_reason']


def test_brief_breath_does_not_slow_entire_creative_section():
    from director.schema import MusicStructureSection
    music = sample_structure()
    music.confidence = .9
    music.sections = [MusicStructureSection(start=0,end=59,role='intro',energy=.8,confidence=.9),
                      MusicStructureSection(start=59,end=60,role='breath',energy=.2,confidence=.9)]
    row = build_guide(direction(),music)['sections'][0]
    assert '分别试听' in row['pacing_suggestion']
    assert '尚不支持高潮对应' in row['suggestion_reason']


@pytest.mark.parametrize('failure', ['gap', 'too_long'])
def test_invalid_coverage_blocks(failure):
    plan = direction()
    if failure == 'gap':
        plan.sections[0].start = 1
    else:
        plan.target_duration_seconds = 1000
    with pytest.raises(ProjectConflict):
        build_guide(plan,sample_structure())


@pytest.mark.parametrize('flag', ['place_footage','build_preview'])
def test_retired_runner_flags_block_before_any_work(tmp_path,monkeypatch,flag):
    monkeypatch.setattr('director.runner._media_inventory', lambda *a: pytest.fail('no inventory or writes'))
    before = snapshot(tmp_path)
    result = run_travel_director(tmp_path,BRIEF,project=tmp_path,**{flag:True})
    assert result.status == 'blocked'
    assert 'retired' in result.message and '--build-guide' in result.message
    assert snapshot(tmp_path) == before


def test_retired_module_cannot_render():
    from director.footage_preview import build_footage_preview
    with pytest.raises(ProjectConflict,match='retired'):
        build_footage_preview(None,None,render=True)


def test_guide_runner_no_media_calls_preserves_history_and_reuses(tmp_path,monkeypatch,click_track):
    source,project = prepared(tmp_path,monkeypatch,click_track)
    historical = project/'previews'/'old'/'preview.mp4'
    historical.parent.mkdir(parents=True)
    historical.write_bytes(b'preserve historical rejected artifact')
    before = snapshot(project)
    def forbidden(*a,**kw):
        pytest.fail('planning must not scan, analyze, select clips or process media')
    monkeypatch.setattr('subprocess.run',forbidden)
    monkeypatch.setattr('director.clip_selector.place_clips',forbidden)
    monkeypatch.setattr('director.audio_import.analyze_music',forbidden)
    monkeypatch.setattr('director.runner._prepare_local_scanner',forbidden)
    result = run_travel_director(source,BRIEF,project=project,build_guide=True)
    assert result.status == 'completed',result.message
    assert result.current_stage == 'music_visual_guidance'
    guide = Path(result.artifact_paths['music_visual_guide'])
    assert guide.is_file()
    for name,data in before.items():
        assert (project/name).read_bytes() == data
    added = set(snapshot(project))-set(before)
    assert len(added)==3 and all(name.startswith('guidance/') for name in added)
    saved = snapshot(project)
    assert run_travel_director(source,BRIEF,project=project,build_guide=True).artifact_paths == result.artifact_paths
    assert snapshot(project)==saved
    guide.write_text('corrupted')
    with pytest.raises(ProjectConflict,match='differs'):
        record_guide(open_project(project))


def test_cli_new_and_retired_flags(tmp_path,monkeypatch):
    from typer.testing import CliRunner
    from typer.main import get_command
    from director.cli import app
    seen = {}
    def run(*a,**kw):
        seen.update(kw)
        return NS(model_dump_json=lambda **k:'{}')
    monkeypatch.setattr('director.runner.run_travel_director',run)
    cli=CliRunner()
    assert cli.invoke(app,['run','--input',str(tmp_path),'--brief',BRIEF,'--build-guide']).exit_code==0
    assert seen['build_guide']
    parameters = {
        option: parameter
        for parameter in get_command(app).commands['run'].params
        for option in parameter.opts
    }
    assert parameters['--build-guide'].hidden is False
    assert parameters['--build-preview'].hidden is True
