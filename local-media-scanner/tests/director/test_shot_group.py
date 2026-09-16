"""Paired review evidence must survive group construction and actual FCPXML export."""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.director.test_shot_review import project, prepare, compact, write
from director.shot_review import submit_shot_review
from director.shot_group import build_shot_group, inspect_shot_group
from director.fcpxml_delivery import export_fcpxml_decision
from director.cli import app


@pytest.fixture
def reviewed(project,tmp_path):
    request,payload=prepare(project,tmp_path)
    data=compact(payload['packets'][0])
    item=data['items'][0]
    item['subject_motion']=dict(value='left_to_right',confidence=.7,evidence_frames=list(range(12)),reason='Synthetic contract fixture')
    frames=payload['packets'][0]['frames']
    a,b=frames[5]['source_time'],frames[6]['source_time']
    item['action_description']='Synthetic event for contract validation'
    item['action_accent']=dict(time_seconds=(a+b)/2,uncertainty_seconds=(b-a)/2,
                               confidence=.7,evidence_frames=[5,6],reason='Observed bracket fixture')
    response=tmp_path/'review.json';write(response,data)
    submit_shot_review(request,response)
    return request,frames,item


def plan(reviewed):
    request,frames,item=reviewed
    # Two selected source intervals in the same reviewed file are valid distinct shots.
    return dict(project_name='Local pair',canvas=dict(width=160,height=90,fps=25),
        shots=[dict(shot_id='a',review_request=str(request),candidate_id='shot-000',
                    source_in=frames[0]['source_time'],source_out=item['action_accent']['time_seconds'],
                    function='context',reason='First local interval',gain=0),
               dict(shot_id='b',review_request=str(request),candidate_id='shot-000',
                    source_in=frames[9]['source_time'],source_out=frames[11]['source_time'],
                    function='detail',reason='Second local interval',gain=0)],
        connections=[dict(left_shot_id='a',right_shot_id='b',status='intentional_cut',
                         relationship='hard_cut',reason='Deliberate ellipsis, not claimed seamless',
                         left=dict(field='action_accent',evidence_frames=[5,6]),
                         right=dict(field='frames',evidence_frames=[8,9,10]))])


def build(reviewed,tmp_path,data=None):
    path=tmp_path/'group-plan.json';write(path,data or plan(reviewed))
    result=build_shot_group(path,tmp_path/'group')
    return result,path


def test_group_inherits_uncertainty_and_exports_review_bound_clips(reviewed,tmp_path):
    result,_=build(reviewed,tmp_path)
    assert result['status']=='shot_group_validated'
    group=json.loads(Path(result['group_path']).read_text())
    left=group['connections'][0]['left']
    assert left['uncertainty_seconds']==reviewed[2]['action_accent']['uncertainty_seconds']
    assert left['time_seconds']==reviewed[2]['action_accent']['time_seconds']
    exported=export_fcpxml_decision(Path(result['decision_path']),tmp_path/'package')
    receipt=json.loads(exported.receipt_path.read_text())
    assert receipt['shot_group']['status']=='shot_group_validated'
    assert receipt['shot_group']['connections'][0]['left']['uncertainty_seconds']==left['uncertainty_seconds']
    assert receipt['video_segments']==2
    assert (tmp_path/'package/shot_group.json').exists()
    assert inspect_shot_group(Path(result['group_path']))['status']=='shot_group_validated'


@pytest.mark.parametrize('change',['out_of_range','wrong_adjacency','missing_connection','unknown_motion','missing_frames','outside_anchor','nan'])
def test_invalid_group_is_rejected_before_publication(reviewed,tmp_path,change):
    data=plan(reviewed)
    if change=='out_of_range':data['shots'][0]['source_in']=0
    if change=='wrong_adjacency':data['connections'][0]['left_shot_id']='b'
    if change=='missing_connection':data['connections']=[]
    if change=='unknown_motion':
        edge=data['connections'][0];edge['status']='supported';edge['relationship']='motion_match'
        edge['left']=dict(field='camera_motion',evidence_frames=[])
        edge['right']=dict(field='camera_motion',evidence_frames=[])
    if change=='missing_frames':data['connections'][0]['right']['evidence_frames']=[999]
    if change=='outside_anchor':data['connections'][0]['left']=dict(field='frames',evidence_frames=[0,1])
    if change=='nan':data['shots'][0]['source_in']=float('nan')
    path=tmp_path/'bad.json';write(path,data)
    with pytest.raises(ValueError):build_shot_group(path,tmp_path/'bad-group')
    assert not (tmp_path/'bad-group').exists()


def test_unresolved_connection_saves_plan_but_has_no_exportable_decision(reviewed,tmp_path):
    data=plan(reviewed)
    edge=data['connections'][0];edge['status']='needs_review';edge['relationship']='motion_match'
    edge['left']=dict(field='camera_motion',evidence_frames=[])
    edge['right']=dict(field='camera_motion',evidence_frames=[])
    result,_=build(reviewed,tmp_path,data)
    assert result['status']=='needs_connection_review'
    assert result['decision_path'] is None
    assert not (tmp_path/'group/edit_decision.json').exists()


@pytest.mark.parametrize('change',['reorder','trim','offset','path','remove','canvas'])
def test_export_rejects_edl_drift_before_creating_package(reviewed,tmp_path,change):
    result,_=build(reviewed,tmp_path)
    decision=Path(result['decision_path']);data=json.loads(decision.read_text())
    if change=='reorder':data['clips'].reverse()
    if change=='trim':data['clips'][0]['source_in']+=.02
    if change=='offset':data['clips'][1]['timeline_in']+=.01;data['canvas']['duration_seconds']+=.01
    if change=='path':data['clips'][0]['source_path']=str(tmp_path/'other.mp4')
    if change=='remove':data['clips'].pop()
    if change=='canvas':data['canvas']['fps']=30
    path=tmp_path/'changed.json';write(path,data)
    with pytest.raises(ValueError):export_fcpxml_decision(path,tmp_path/'package')
    assert not (tmp_path/'package').exists()


def test_export_rechecks_underlying_review_evidence(reviewed,tmp_path):
    result,_=build(reviewed,tmp_path)
    path=reviewed[0].parent/reviewed[1][0]['path']
    path.write_bytes(path.read_bytes()+b'corrupt')
    with pytest.raises(ValueError,match='hash'):
        export_fcpxml_decision(Path(result['decision_path']),tmp_path/'package')
    assert not (tmp_path/'package').exists()


def test_group_is_immutable_and_cli_inspection_works(reviewed,tmp_path):
    result,path=build(reviewed,tmp_path)
    assert build_shot_group(path,tmp_path/'group')['group_path']==result['group_path']
    data=plan(reviewed);data['connections'][0]['reason']='different revision';write(path,data)
    with pytest.raises(ValueError,match='immutable'):build_shot_group(path,tmp_path/'group')
    reply=CliRunner().invoke(app,['inspect-shot-group','--group',result['group_path']])
    assert reply.exit_code==0,reply.output
    assert json.loads(reply.output)['external_call_count']==0


@pytest.mark.parametrize('count',[2,3,4])
def test_two_to_four_shots_have_contiguous_edl_and_complete_pairs(reviewed,tmp_path,count):
    data=plan(reviewed)
    base=data['shots'][0]
    frames=reviewed[1]
    data['shots']=[{**base,'shot_id':f's{i}','source_in':frames[1]['source_time'],
                   'source_out':frames[10]['source_time']} for i in range(count)]
    data['connections']=[dict(left_shot_id=f's{i}',right_shot_id=f's{i+1}',
        status='supported',relationship='motion_match',reason='Synthetic identical observed direction',
        left=dict(field='subject_motion',evidence_frames=[9,10,11]),
        right=dict(field='subject_motion',evidence_frames=[0,1,2])) for i in range(count-1)]
    result,_=build(reviewed,tmp_path,data)
    decision=json.loads(Path(result['decision_path']).read_text())
    assert len(decision['clips'])==count
    for a,b in zip(decision['clips'],decision['clips'][1:]):
        assert a['timeline_in']+a['duration']==pytest.approx(b['timeline_in'],abs=1e-6)


def test_audio_additions_keep_group_binding(reviewed,tmp_path):
    result,_=build(reviewed,tmp_path)
    path=tmp_path/'with-audio.json';data=json.loads(Path(result['decision_path']).read_text())
    import wave
    audio=tmp_path/'tone.wav'
    with wave.open(str(audio),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000)
        output.writeframes(b'\0\0'*16000)
    data['clips'].append(dict(kind='sfx',source_path=str(audio),
                             track='sfx',timeline_in=0,source_in=0,duration=.2,gain=.3))
    write(path,data)
    result=export_fcpxml_decision(path,tmp_path/'package')
    assert result.audio_segments==1
    assert json.loads(result.receipt_path.read_text())['shot_group']['status']=='shot_group_validated'


def test_group_snapshot_mutation_is_rejected(reviewed,tmp_path):
    result,_=build(reviewed,tmp_path)
    path=Path(result['group_path']);data=json.loads(path.read_text())
    data['connections'][0]['left']['uncertainty_seconds']=0;write(path,data)
    with pytest.raises(ValueError,match='hash'):
        export_fcpxml_decision(Path(result['decision_path']),tmp_path/'package')


def test_cannot_narrow_action_uncertainty_in_plan(reviewed,tmp_path):
    data=plan(reviewed);data['connections'][0]['left']['uncertainty_seconds']=0
    path=tmp_path/'plan.json';write(path,data)
    with pytest.raises(ValueError):build_shot_group(path,tmp_path/'group')
