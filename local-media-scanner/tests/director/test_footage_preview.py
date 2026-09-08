import json
from pathlib import Path
import subprocess
from types import SimpleNamespace as NS

import pytest

from director import footage_preview as preview
from director.delivery import FastModeSlot, FastModeTimeline
from director.project import ProjectConflict, _sha256_file


def fixture_plan(tmp_path, monkeypatch):
    items = []
    for name in ('a', 'b', 'rejected'):
        source = tmp_path / f'{name}.mp4'
        source.write_bytes(name.encode())
        ref = NS(material_id=name, relative_path=source.name, duration_seconds=4., fps=24.,
            source_sha256=_sha256_file(source), size_bytes=source.stat().st_size, mtime_ns=1, orientation='landscape')
        evidence = NS(model_dump=lambda **kw: {'status': 'measured'})
        items.append(NS(material=ref, observation_status='automatic', unknown_fields=['lighting'],
            assertions=[NS(field='duration_seconds', value=4., status='measured', evidence_refs=[evidence])]))
    monkeypatch.setattr(preview, '_metadata', lambda path: {'format': {'duration': '4'},
        'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 320, 'height': 180}]})
    timeline = FastModeTimeline(target_duration_seconds=4., music_asset_path='music.wav', slots=[
        FastModeSlot(slot_id=str(i), start=i*2., end=(i+1)*2., duration=2., section_role='intro', energy=.5,
            content_need='context', desired_motion='medium', placeholder_text='pending') for i in range(2)])
    sections = [NS(section_id=str(i), start=i*2., end=(i+1)*2., material_ids=[name, 'rejected'],
        material_gaps=['lighting remains unknown'], narrative_task='context') for i,name in enumerate(('a','b'))]
    treatment = NS(core_materials=['a'], candidate_materials=['b'], reject_suggestions=['rejected'], review_required=[])
    review = NS(status='completed', overrides=[])
    return timeline, sections, NS(items=items), treatment, review, tmp_path


def test_section_constraints_rejection_unknown_and_determinism(tmp_path, monkeypatch):
    args = fixture_plan(tmp_path, monkeypatch)
    report = preview.build_placements(*args)
    assert report['status'] == 'completed'
    assert [row['material_id'] for row in report['slots']] == ['a','b']
    assert all(row['unknown_fields'] == ['lighting'] for row in report['slots'])
    assert all(row['material_gaps'] for row in report['slots'])
    preview._validate_sources(report)
    args[2].items.reverse()
    assert report == preview.build_placements(*args)


@pytest.mark.parametrize('cause', ['missing', 'unknown_duration', 'excluded', 'short', 'outside_section'])
def test_gaps_are_partial_and_preserve_target(tmp_path, monkeypatch, cause):
    args = fixture_plan(tmp_path, monkeypatch)
    if cause == 'missing':
        monkeypatch.setattr(preview, '_metadata', lambda path: (_ for _ in ()).throw(OSError('missing')))
    elif cause == 'unknown_duration':
        args[2].items[0].assertions[0].status = 'unavailable'
    elif cause == 'excluded':
        args[4].overrides = [NS(material_id='a', force_exclude=True, bucket_override=None)]
    elif cause == 'short':
        args[0].slots[0].end = args[0].slots[0].duration = 5.
        args[0].slots[1].start, args[0].slots[1].end = 5., 7.
        args[0].target_duration_seconds = 7.
        args[1][0].end, args[1][1].start, args[1][1].end = 5., 5., 7.
    else:
        args[1][0].material_ids = []
    report = preview.build_placements(*args)
    assert report['status'] == 'partial'
    assert report['slots'][0]['placement'] is None
    assert len(report['slots']) == 2
    assert report['slots'][-1]['end'] == report['target_duration_seconds']


def test_timeline_gap_and_source_drift_block(tmp_path, monkeypatch):
    args = fixture_plan(tmp_path, monkeypatch)
    report = preview.build_placements(*args)
    (tmp_path/'a.mp4').write_bytes(b'changed')
    with pytest.raises(ProjectConflict, match='bytes drifted'):
        preview._validate_sources(report)
    args[0].slots[1].start += .1
    with pytest.raises(ProjectConflict, match='continuous'):
        preview.build_placements(*args)


def test_publish_no_overwrite_and_no_symlink(tmp_path):
    file = tmp_path/'report.json'
    preview._publish(file, b'first')
    preview._publish(file, b'first')
    with pytest.raises(ProjectConflict, match='differs'):
        preview._publish(file, b'changed')
    alias = tmp_path/'alias.json'
    alias.symlink_to(file)
    with pytest.raises(ProjectConflict, match='symlink'):
        preview._publish(alias, b'changed')
    assert file.read_bytes() == b'first'


def test_real_ffmpeg_preview_silent_sources_frame_rounding_and_receipt(tmp_path):
    video, music, output = tmp_path/'source.mp4', tmp_path/'music.wav', tmp_path/'preview.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=24',
        '-t','2','-c:v','libx264','-threads','1',str(video)],check=True)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
        '-t','2',str(music)],check=True)
    boundaries = [0., .53, 1.13, 2.]
    report = dict(target_duration_seconds=2., inputs={'music_sha256': _sha256_file(music)}, slots=[
        dict(start=start,end=end,source_sha256=_sha256_file(video),placement=dict(file=str(video),
            source_in=0.,source_out=end-start,source_duration=2.))
        for start,end in zip(boundaries,boundaries[1:])])
    receipt = preview._render(report,music,output,'portrait')
    assert receipt['status'] == 'completed'
    assert (receipt['width'],receipt['height']) == (720,1280)
    assert abs(receipt['duration_seconds']-2.) < 1/24
    assert receipt['sha256'] == _sha256_file(output)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(output),'-f','null','-'],check=True,capture_output=True)
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        preview._render(report,music,output,'portrait')
    assert output.read_bytes() == before


def test_runner_partial_and_cli_entry(tmp_path, monkeypatch, click_track):
    from tests.director.test_timeline_revision import prepared
    from tests.director.test_runner import BRIEF
    from tests.director.test_creative_runner import snapshot
    from director.runner import run_travel_director
    from director.cli import app
    from typer.testing import CliRunner
    source, project = prepared(tmp_path,monkeypatch,click_track)
    before = snapshot(project/'delivery')
    monkeypatch.setattr(preview, '_render', lambda *a: pytest.fail('partial must not render'))
    result = run_travel_director(source,BRIEF,project=project,build_preview=True)
    assert result.status == 'blocked', result.message
    assert 'partial' in result.message
    report = json.loads(Path(result.artifact_paths['placement_json']).read_text())
    assert report['status'] == 'partial'
    assert all(row['placement'] is None for row in report['slots'])
    assert snapshot(project/'delivery') == before
    saved = snapshot(project)
    repeated = CliRunner().invoke(app,['run','--input',str(source),'--brief',BRIEF,'--project',str(project),'--place-footage'])
    assert repeated.exit_code == 0, repeated.output
    assert json.loads(repeated.output)['current_stage'] == 'footage_placement'
    assert snapshot(project) == saved


def test_render_failure_retry_reuse_and_corruption(tmp_path, monkeypatch, click_track):
    from tests.director.test_timeline_revision import prepared
    from director.project import open_project
    source, project = prepared(tmp_path, monkeypatch, click_track)
    report = preview.build_placements(*fixture_plan(tmp_path, monkeypatch))
    monkeypatch.setattr(preview, 'build_placements', lambda *a: report)
    calls = []
    def render(report, music, output, orientation):
        calls.append(output)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, ['ffmpeg'], stderr=b'interrupted render')
        output.write_bytes(b'encoded preview')
        return dict(status='completed', sha256=_sha256_file(output), duration_seconds=4.,
                    width=720, height=1280, video_codec='h264', audio_codec='aac')
    monkeypatch.setattr(preview, '_render', render)
    monkeypatch.setattr('director.render._probe', lambda path: (4.,720,1280,'h264','aac'))
    paths = open_project(project)
    failed = preview.build_footage_preview(paths,source,render=True)
    assert failed['status'] == 'failed' and 'interrupted' in failed['error']
    assert Path(failed['placement_json']).exists()
    done = preview.build_footage_preview(paths,source,render=True)
    assert done['status'] == 'completed'
    assert preview.build_footage_preview(paths,source,render=True) == done
    assert len(calls) == 2
    receipt = Path(done['preview_receipt'])
    receipt.write_text(receipt.read_text().replace('bgm_only', 'full_mix'))
    with pytest.raises(ProjectConflict, match='drifted'):
        preview.build_footage_preview(paths,source,render=True)
