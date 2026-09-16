"""Temporal evidence must be bounded, source-bound and separate from coarse tags."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from director.cli import app
from director.shot_review import prepare_shot_review, submit_shot_review, inspect_shot_review


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def project(tmp_path):
    source = tmp_path / 'media' / 'moving.mp4'
    source.parent.mkdir()
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=160x90:rate=25:duration=4',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    root = tmp_path / 'project'
    material = dict(material_id=f'sha256:{digest}', relative_path=source.name,
                    source_sha256=digest, size_bytes=source.stat().st_size,
                    mtime_ns=source.stat().st_mtime_ns, duration_seconds=4,
                    fps=25, orientation='landscape')
    write(root / 'visual/scanner_only.json', {'schema_version':'0.2.0',
          'mode':'scanner_only', 'status':'partial', 'items':[
              {'material':material, 'provider':'scanner_only', 'observation_status':'automatic'}]})
    write(root / 'visual/run_contract.json', {'input_root':str(source.parent),
          'media':[{'relative_path':source.name,'source_sha256':digest}]})
    return root, source, material


def selection(material, **changes):
    return {'items':[dict(material_id=material['material_id'], source_in=0.8,
                         source_out=2.8, reason='Check selected action connection',
                         purpose='selected', **changes)]}


def unknown():
    return {'value':None, 'confidence':None, 'evidence_frames':[], 'reason':'Not discernible'}


def compact(packet):
    frames = packet['frames']
    return {'items':[{
        'candidate_id':packet['candidate_id'], 'source_in':frames[0]['source_time'],
        'source_out':frames[-1]['source_time'], 'range_confidence':0.8,
        'range_evidence_frames':[0,len(frames)-1], 'range_reason':'Observed usable interval',
        'shot_scale':unknown(), 'subject_position':unknown(),
        'camera_motion':unknown(), 'subject_motion':unknown(),
        'action_description':None,
        'action_start':None, 'action_accent':None, 'action_end':None,
        'action_unknown_reason':'No primary action established',
    }]}


def prepare(project, tmp_path):
    root, _, material = project
    path = tmp_path / 'selection.json'
    write(path, selection(material))
    reply = prepare_shot_review(root, path)
    request = Path(reply['request_path'])
    return request, json.loads(request.read_text())


def test_prepare_samples_real_source_pts_and_reuses_cache(project, tmp_path, monkeypatch):
    request, payload = prepare(project, tmp_path)
    frames = payload['packets'][0]['frames']
    assert 10 <= len(frames) <= 17
    assert all(.8 <= f['source_time'] < 2.8 for f in frames)
    assert all(abs(f['source_time'] * 25-round(f['source_time']*25)) < .001 for f in frames)
    coarse = (project[0] / 'visual/scanner_only.json').read_bytes()
    import director.shot_review as module
    monkeypatch.setattr(module, '_extract_frames', lambda *a: pytest.fail('cache decoded again'))
    second = prepare_shot_review(project[0], tmp_path / 'selection.json')
    assert second['request_path'] == str(request)
    assert second['cache_hit'] is True
    assert (project[0] / 'visual/scanner_only.json').read_bytes() == coarse


def test_compact_expands_hash_evidence_and_is_immutable(project, tmp_path):
    request, payload = prepare(project, tmp_path)
    response = tmp_path / 'response.json'
    data = compact(payload['packets'][0])
    write(response, data)
    result = submit_shot_review(request, response)
    saved = json.loads(Path(result['result_path']).read_text())
    assert saved['request_sha256'] == hashlib.sha256(request.read_bytes()).hexdigest()
    assert saved['items'][0]['evidence']['frames'][0]['sha256']
    assert inspect_shot_review(request)['status'] == 'shot_review_validated'
    assert submit_shot_review(request, response)['result_path'] == result['result_path']
    data['items'][0]['range_reason'] = 'Different decision'
    write(response, data)
    with pytest.raises(ValueError, match='immutable'):
        submit_shot_review(request, response)


@pytest.mark.parametrize('change', ['unknown_material','out_of_bounds','duplicate','too_long'])
def test_reject_invalid_selection_before_decode(project, tmp_path, change, monkeypatch):
    data = selection(project[2])
    if change == 'unknown_material': data['items'][0]['material_id'] = 'sha256:'+'0'*64
    if change == 'out_of_bounds': data['items'][0]['source_out'] = 4.5
    if change == 'duplicate': data['items'] *= 2
    if change == 'too_long': data['items'][0]['source_out'] = 10
    path = tmp_path / 'invalid.json'
    write(path, data)
    import director.shot_review as module
    monkeypatch.setattr(module, '_extract_frames', lambda *a: pytest.fail('invalid selection decoded'))
    with pytest.raises(ValueError): prepare_shot_review(project[0], path)


@pytest.mark.parametrize('change', ['sparse_motion','precise_event','range','missing_candidate','nan'])
def test_reject_unsupported_temporal_observations(project, tmp_path, change):
    request, payload = prepare(project, tmp_path)
    data = compact(payload['packets'][0])
    item = data['items'][0]
    if change == 'sparse_motion':
        item['camera_motion'] = dict(value='pan_right',confidence=.8,
                                     evidence_frames=[0,8],reason='Sparse guess')
    if change == 'precise_event':
        item['action_description']='A turn'
        item['action_accent']=dict(time_seconds=1.44,uncertainty_seconds=0,
                                   confidence=.8,evidence_frames=[3,4],reason='Exact guess')
    if change == 'range': item['source_out']=3.5
    if change == 'missing_candidate': data['items']=[]
    if change == 'nan': item['range_confidence']=float('nan')
    response = tmp_path / 'bad.json'
    write(response,data)
    with pytest.raises(ValueError): submit_shot_review(request,response)


@pytest.mark.parametrize('target', ['source','frame','sheet'])
def test_tampered_evidence_is_not_reused(project, tmp_path, target):
    request,payload=prepare(project,tmp_path)
    packet=payload['packets'][0]
    path = project[1] if target=='source' else request.parent / (
        packet['frames'][0]['path'] if target=='frame' else packet['sheets'][0]['path'])
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='hash|source'):
        inspect_shot_review(request)


def test_cli_exposes_prepare_submit_inspect(project,tmp_path):
    path=tmp_path/'selection.json'
    write(path,selection(project[2]))
    runner=CliRunner()
    reply=runner.invoke(app,['prepare-shot-review','--project',str(project[0]),'--selection',str(path)])
    assert reply.exit_code==0,reply.output
    request=Path(json.loads(reply.output)['request_path'])
    data=json.loads(request.read_text())
    response=tmp_path/'response.json'
    write(response,compact(data['packets'][0]))
    reply=runner.invoke(app,['submit-shot-review','--request',str(request),'--observations',str(response)])
    assert reply.exit_code==0,reply.output
    assert json.loads(reply.output)['external_call_count']==0


def test_non_frame_aligned_seek_preserves_source_time(project,tmp_path):
    data=selection(project[2])
    data['items'][0]['source_in']=.83
    path=tmp_path/'selection.json'
    write(path,data)
    result=prepare_shot_review(project[0],path)
    request=json.loads(Path(result['request_path']).read_text())
    times=[f['source_time'] for f in request['packets'][0]['frames']]
    assert times[0] == pytest.approx(.84,abs=.0001)
    assert all(abs(t*25-round(t*25))<.001 for t in times)


def test_dense_motion_and_bracketed_action_are_saved(project,tmp_path):
    request,payload=prepare(project,tmp_path)
    packet=payload['packets'][0]
    data=compact(packet)
    item=data['items'][0]
    item['subject_motion']=dict(value='left_to_right',confidence=.75,
                                evidence_frames=[0,1,2,3],reason='Synthetic contract assertion')
    first,last=[packet['frames'][i]['source_time'] for i in [2,3]]
    item['action_description']='Synthetic contract action, not a visual truth claim'
    item['action_accent']=dict(time_seconds=(first+last)/2,
                               uncertainty_seconds=(last-first)/2,
                               confidence=.7,evidence_frames=[2,3],reason='Bracketed observation')
    response=tmp_path/'response.json'
    write(response,data)
    saved=submit_shot_review(request,response)
    assert saved['status']=='shot_review_validated'


def test_untouched_template_cannot_masquerade_as_review(project,tmp_path):
    request,_=prepare(project,tmp_path)
    with pytest.raises(ValueError,match='template'):
        submit_shot_review(request,request.parent/'response.template.json')


def test_changed_upstream_invalidates_saved_evidence(project,tmp_path):
    request,_=prepare(project,tmp_path)
    path=project[0]/'visual/scanner_only.json'
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='upstream hash'):
        inspect_shot_review(request)


def test_coarse_contract_still_excludes_temporal_fields():
    from director.agent_batches import AGENT_VISUAL_FIELDS
    assert len(AGENT_VISUAL_FIELDS)==8
    assert not {'source_in','source_out','camera_motion','action_accent'} & set(AGENT_VISUAL_FIELDS)


def test_variable_rate_samples_use_real_pts(tmp_path):
    from director.shot_review import _extract_frames
    source=tmp_path/'variable.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                    'testsrc2=size=160x90:rate=25:duration=3',
                    '-vf',"select='not(mod(n,2))+not(mod(n,5))'",'-fps_mode','vfr',
                    '-c:v','libx264',str(source)],check=True)
    payload=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
          '-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(source)]))
    pts=[float(x['best_effort_timestamp_time']) for x in payload['frames']]
    frames=_extract_frames(source,.83,2.63,tmp_path/'frames')
    assert all(min(abs(t-f.source_time) for t in pts)<1e-5 for f in frames)
    assert frames[0].source_time >= .83


def test_failed_decode_publishes_no_partial_bundle(project,tmp_path,monkeypatch):
    import director.shot_review as module
    path=tmp_path/'selection.json'
    write(path,selection(project[2]))
    def fail(*args): raise ValueError('decode failed')
    monkeypatch.setattr(module,'_extract_frames',fail)
    with pytest.raises(ValueError,match='decode failed'):
        prepare_shot_review(project[0],path)
    assert list((project[0]/'visual/shot_reviews').iterdir())==[]


def test_result_tampering_is_detected(project,tmp_path):
    request,payload=prepare(project,tmp_path)
    response=tmp_path/'response.json'
    write(response,compact(payload['packets'][0]))
    result=submit_shot_review(request,response)
    path=Path(result['result_path'])
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='receipt hash'):
        inspect_shot_review(request)


def test_total_request_budget_and_unknown_fields_rejected():
    from director.shot_review_schema import ShotSelection
    items=[dict(material_id='sha256:'+'0'*64,source_in=i*8,source_out=(i+1)*8,
                purpose='selected',reason='Budget test') for i in range(6)]
    with pytest.raises(ValueError,match='40 seconds'): ShotSelection(items=items)
    with pytest.raises(ValueError): ShotSelection(items=[{**items[0],'best_guess':True}])
