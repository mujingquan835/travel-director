"""Phrase proposals, listening provenance and immutable source-to-project edits."""
import json
from pathlib import Path

import pytest

from tests.director.test_shot_review import write
from tests.director.test_shot_group import reviewed, project, plan as group_plan
from director.shot_group import build_shot_group
from director.project import create_visual_project
from director.visual_schema import RawCreativeBrief
from director.audio_import import freeze_and_analyze_music
from director.music_adaptation import build_music_adaptation, inspect_music_adaptation
from director.fcpxml_delivery import export_fcpxml_decision


@pytest.fixture
def fixture(tmp_path,click_track,reviewed):
    music=create_visual_project(tmp_path/'music-projects','music',RawCreativeBrief(raw_description='Fixture music test'))
    freeze_and_analyze_music(music,click_track)
    gp=tmp_path/'group-plan.json';write(gp,group_plan(reviewed))
    group=build_shot_group(gp,tmp_path/'group')
    base=Path(group['decision_path']);duration=json.loads(base.read_text())['canvas']['duration_seconds']
    return music,base,duration


def plan(fixture):
    music,base,d=fixture
    return dict(music_project=str(music.root),base_decision=str(base),revision_reason='Initial source mapping',
        listening=[],phrases=[dict(phrase_id='p1',source_in=10,source_out=12,
            label='Candidate phrase',status='candidate',basis='editorial_proposal',listening_id=None,reason='Unheard fixture proposal')],
        mapping=[dict(segment_id='a',kind='music',source_in=10,source_out=10.4,project_in=0,project_out=.4,phrase_id='p1',gain=.4,reason='Opening excerpt'),
                 dict(segment_id='pause',kind='silence',source_in=None,source_out=None,project_in=.4,project_out=.6,phrase_id=None,gain=0,reason='Intentional music pause, source sound remains'),
                 dict(segment_id='b',kind='music',source_in=10.6,source_out=10.6+d-.6,project_in=.6,project_out=d,phrase_id='p1',gain=.4,reason='Continue selected excerpt')],
        events=[dict(event_id='resume',kind='turn',project_time=.6,segment_id='b',source_time=10.6,
                     status='proposed',listening_id=None,reason='Return from pause')],
        ending=dict(treatment='cut',reason='Deliberate excerpt end; not claiming a musical cadence',listening_id=None),
        pacing=[dict(mode='hold',shot_ids=['a'],event_id=None,action_field=None,
                     reason='Hold the action through music instead of one cut per beat')])


def build(fixture,tmp_path,data=None,parent=None,name='adapt'):
    p=tmp_path/(name+'-plan.json');write(p,data or plan(fixture))
    return build_music_adaptation(p,tmp_path/name,parent=parent)


def test_mapping_and_pause_materialize_without_moving_picture(fixture,tmp_path):
    result=build(fixture,tmp_path)
    assert result['listening_status']=='not_listened'
    assert result['status']=='music_adaptation_validated'
    doc=json.loads(Path(result['adaptation_path']).read_text())
    assert doc['automatic_hints']['interpretation']=='unconfirmed_candidates'
    assert doc['plan']['phrases'][0]['status']=='candidate'
    decision=json.loads(Path(result['decision_path']).read_text())
    original=json.loads(fixture[1].read_text())
    assert [x for x in decision['clips'] if x['kind']=='video']==original['clips']
    tracks=[x for x in decision['clips'] if x['kind']=='music']
    assert len(tracks)==2 and tracks[1]['timeline_in']==.6
    export=export_fcpxml_decision(Path(result['decision_path']),tmp_path/'package')
    receipt=json.loads(export.receipt_path.read_text())
    assert receipt['music_adaptation']['listening_status']=='not_listened'
    assert (tmp_path/'package/music_adaptation.json').exists()


@pytest.mark.parametrize('mutation',['auto_confirm','no_listen','range','gap','speed','event','missing_phrase','nan'])
def test_invalid_claims_or_mapping_fail_without_writes(fixture,tmp_path,mutation):
    data=plan(fixture)
    if mutation=='auto_confirm':data['phrases'][0].update(status='confirmed',basis='automatic_energy')
    if mutation=='no_listen':data['phrases'][0].update(status='confirmed',basis='listening')
    if mutation=='range':data['mapping'][0]['source_in']=70
    if mutation=='gap':data['mapping'][1]['project_in']=.5
    if mutation=='speed':data['mapping'][0]['source_out']=10.8
    if mutation=='event':data['events'][0]['source_time']=11.5
    if mutation=='missing_phrase':data['mapping'][0]['phrase_id']='absent'
    if mutation=='nan':data['mapping'][0]['gain']=float('nan')
    with pytest.raises(ValueError):build(fixture,tmp_path,data)
    assert not (tmp_path/'adapt').exists()


def test_confirmed_phrase_requires_covering_listening_record(fixture,tmp_path):
    data=plan(fixture)
    data['listening']=[dict(listening_id='listen',source_in=10,source_out=12,reviewer='fixture-user',
                            method='user_report',note='Fixture listening testimony',reviewed_at='2026-09-10T10:00:00+08:00')]
    data['phrases'][0].update(status='confirmed',basis='listening',listening_id='listen')
    r=build(fixture,tmp_path,data)
    assert r['listening_status']=='source_ranges_reviewed'
    data['listening'][0]['source_out']=10.5
    with pytest.raises(ValueError,match='cover'):build(fixture,tmp_path,data,name='invalid')


def test_revision_preserves_parent_and_records_before_after(fixture,tmp_path):
    first=build(fixture,tmp_path)
    parent=Path(first['adaptation_path']);before=parent.read_bytes()
    data=plan(fixture);data['revision_reason']='Adjust opening gain';data['mapping'][0]['gain']=.2
    child=build(fixture,tmp_path,data,parent=parent,name='revision')
    document=json.loads(Path(child['adaptation_path']).read_text())
    assert parent.read_bytes()==before
    assert document['parent']['path']==str(parent)
    diff=document['changes'];assert any(x['path']=='/mapping/0/gain' and x['before']==.4 and x['after']==.2 for x in diff)
    assert inspect_music_adaptation(parent)['status']=='music_adaptation_validated'


def test_unimplemented_fade_is_saved_as_plan_not_exported(fixture,tmp_path):
    data=plan(fixture);data['ending']['treatment']='fade'
    r=build(fixture,tmp_path,data)
    assert r['status']=='needs_audio_processing'
    assert r['decision_path'] is None


def test_fast_cut_requires_local_multiple_shots_and_reason(fixture,tmp_path):
    data=plan(fixture);data['pacing'][0]['mode']='local_fast_cut'
    with pytest.raises(ValueError):build(fixture,tmp_path,data)


def test_export_rejects_music_drift_and_frozen_source_changes(fixture,tmp_path):
    r=build(fixture,tmp_path)
    data=json.loads(Path(r['decision_path']).read_text());data['clips'][-1]['source_in']+=.1
    changed=tmp_path/'changed.json';write(changed,data)
    with pytest.raises(ValueError,match='music'):export_fcpxml_decision(changed,tmp_path/'package')
    assert not (tmp_path/'package').exists()
    frozen=next((fixture[0].root/'generation/assets').glob('*'));frozen.write_bytes(frozen.read_bytes()+b'changed')
    with pytest.raises((ValueError,RuntimeError)):inspect_music_adaptation(Path(r['adaptation_path']))


def test_internal_action_inherits_timing_without_cutting_shot(fixture,reviewed,tmp_path):
    gp=group_plan(reviewed);gp['shots'][0]['source_out']=2.08
    gp['connections'][0]['left']=dict(field='frames',evidence_frames=[7,8,9])
    path=tmp_path/'held-plan.json';write(path,gp)
    result=build_shot_group(path,tmp_path/'held')
    d=json.loads(Path(result['decision_path']).read_text())['canvas']['duration_seconds']
    new_fixture=(fixture[0],Path(result['decision_path']),d)
    data=plan(new_fixture)
    data['events'][0].update(project_time=.88,source_time=10.88)
    data['pacing']=[dict(mode='internal_action',shot_ids=['a'],event_id='resume',
                         action_field='action_accent',reason='Action inside the held shot responds to music')]
    r=build(new_fixture,tmp_path,data)
    doc=json.loads(Path(r['adaptation_path']).read_text())
    cue=doc['resolved_pacing'][0]['action_evidence']
    assert cue['timeline_time']==pytest.approx(.88)
    assert cue['uncertainty_seconds']==reviewed[2]['action_accent']['uncertainty_seconds']
    assert cue['alignment']=='within_observation_window'
    assert len([x for x in doc['decision']['clips'] if x['kind']=='video'])==2


def test_unknown_action_cannot_become_music_response(fixture,tmp_path):
    data=plan(fixture);data['pacing']=[dict(mode='internal_action',shot_ids=['a'],event_id='resume',
        action_field='action_end',reason='Attempt unknown end')]
    with pytest.raises(ValueError,match='known'):build(fixture,tmp_path,data)


def test_excerpt_cannot_claim_original_song_ending(fixture,tmp_path):
    data=plan(fixture);data['ending']['treatment']='source_end'
    with pytest.raises(ValueError,match='actual frozen music end'):build(fixture,tmp_path,data)


def test_reordering_music_is_valid_and_base_remains_frozen(fixture,tmp_path):
    data=plan(fixture);data['mapping'][0].update(source_in=11,source_out=11.4)
    before=fixture[1].read_bytes()
    result=build(fixture,tmp_path,data)
    doc=json.loads(Path(result['adaptation_path']).read_text())
    assert doc['plan']['mapping'][0]['source_in']>doc['plan']['mapping'][2]['source_in']
    assert fixture[1].read_bytes()==before


def test_immutable_retry_and_cli_inspection(fixture,tmp_path):
    from typer.testing import CliRunner
    from director.cli import app
    first=build(fixture,tmp_path)
    assert build(fixture,tmp_path)==first
    data=plan(fixture);data['revision_reason']='Different reason'
    with pytest.raises(ValueError,match='immutable'):build(fixture,tmp_path,data)
    result=CliRunner().invoke(app,['inspect-music-adaptation','--adaptation',first['adaptation_path']])
    assert result.exit_code==0,result.output
    assert json.loads(result.output)['listening_status']=='not_listened'


def test_parent_drift_blocks_child_reuse(fixture,tmp_path):
    first=build(fixture,tmp_path);parent=Path(first['adaptation_path'])
    data=plan(fixture);data['revision_reason']='Child'
    child=build(fixture,tmp_path,data,parent,name='child')
    parent.write_bytes(parent.read_bytes()+b' ')
    with pytest.raises(ValueError,match='parent revision hash'):
        inspect_music_adaptation(Path(child['adaptation_path']))


def test_partial_listening_does_not_imply_whole_source_review(fixture,tmp_path):
    data=plan(fixture);data['listening']=[dict(listening_id='some',source_in=10,source_out=10.2,
        reviewer='test',method='user_report',note='Only short opening heard',reviewed_at='2026-09-10T10:00:00+08:00')]
    assert build(fixture,tmp_path,data)['listening_status']=='partial_source_review'
