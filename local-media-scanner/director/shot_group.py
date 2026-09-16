"""Resolve paired fine-review evidence into a bound local EDL; no new decoding."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from director.project import _atomic_write, _canonical_bytes, _sha256_file
from director.shot_group_schema import ShotGroupPlan
from director.shot_review import inspect_shot_review, _times
from director.shot_review_schema import ShotPacket


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path, data):
    _atomic_write(path, _canonical_bytes(data))


def _anchor(anchor, item, selected_time, pending):
    observation = item['observation']
    packet = ShotPacket.model_validate(item['evidence'])
    field = anchor.field
    claimed = observation.get(field) if field != 'frames' else None
    available = field == 'frames' or (claimed is not None and (
        field.startswith('action_') or claimed.get('value') is not None))
    if not available:
        if anchor.evidence_frames:
            raise ValueError('unknown fine-review field cannot carry invented evidence')
        if not pending:
            raise ValueError('connection refers to an unknown fine-review field')
        return dict(field=field, available=False, evidence_frames=[],
                    selected_source_time=selected_time, time_seconds=None,
                    uncertainty_seconds=None, source_window=None, value=None)
    if field.startswith('action_'):
        if anchor.evidence_frames != claimed['evidence_frames']:
            raise ValueError('action anchor must inherit the original complete evidence bracket')
        times = _times(packet, anchor.evidence_frames, 2, True)
        center = claimed['time_seconds']
        uncertainty = claimed['uncertainty_seconds']
        window = [center-uncertainty, center+uncertainty]
        value = observation['action_description']
    else:
        temporal = field in ('camera_motion', 'subject_motion') or (
            claimed is not None and claimed.get('value') == 'changing')
        times = _times(packet, anchor.evidence_frames, 3 if temporal else 2, True)
        if claimed is not None and not set(anchor.evidence_frames).issubset(claimed['evidence_frames']):
            raise ValueError('connection evidence is not supported by its fine-review judgment')
        # Carry a sampled time window, not a newly asserted precise event.
        window = [times[0], times[-1]]
        center = (window[0]+window[1])/2
        uncertainty = (window[1]-window[0])/2
        value = claimed['value'] if claimed is not None else None
    if not pending and not window[0]-1e-6 <= selected_time <= window[1]+1e-6:
        raise ValueError('chosen cut is outside its inherited evidence window')
    return dict(field=field, available=True, value=value,
                evidence_frames=[dict(index=i, **packet.frames[i].model_dump(mode='json')) for i in anchor.evidence_frames],
                selected_source_time=selected_time, time_seconds=center,
                uncertainty_seconds=uncertainty, source_window=window)


def _resolve(plan: ShotGroupPlan):
    reviews = {}
    shots = []
    cursor = 0.0
    project_paths = set()
    for shot in plan.shots:
        request_path = shot.review_request.resolve()
        if str(request_path) not in reviews:
            checked = inspect_shot_review(request_path)
            if checked['status'] != 'shot_review_validated':
                raise ValueError('shot group requires a submitted fine review')
            payload = _read(checked['result_path'])
            request = _read(request_path)
            reviews[str(request_path)] = dict(
                request_sha256=_sha256_file(request_path),
                result_path=checked['result_path'], result_sha256=_sha256_file(Path(checked['result_path'])),
                request=request, payload=payload,
            )
        review = reviews[str(request_path)]
        project_paths.add(review['request']['project_path'])
        candidates = {x['observation']['candidate_id']:x for x in review['payload']['items']}
        item = candidates.get(shot.candidate_id)
        if item is None:
            raise ValueError('shot candidate is absent from fine review')
        observed = item['observation']
        if observed['source_in'] is None or not (
            observed['source_in'] <= shot.source_in < shot.source_out <= observed['source_out']):
            raise ValueError('shot range exceeds the reviewed usable range or range is unknown')
        source = (Path(review['request']['input_root']) / item['material']['relative_path']).resolve()
        duration = round(shot.source_out-shot.source_in, 6)
        shots.append(dict(shot_id=shot.shot_id, review_request=str(request_path),
                          candidate_id=shot.candidate_id, function=shot.function, reason=shot.reason,
                          material_id=item['material']['material_id'], source_sha256=item['material']['source_sha256'],
                          source_path=str(source), source_in=shot.source_in, source_out=shot.source_out,
                          timeline_in=cursor, duration=duration, gain=shot.gain, item=item))
        cursor = round(cursor+duration, 6)
    if len(project_paths) != 1:
        raise ValueError('local shot group cannot mix different projects')
    connections = []
    for index, connection in enumerate(plan.connections):
        a, b = shots[index:index+2]
        pending = connection.status == 'needs_review'
        left = _anchor(connection.left, a['item'], a['source_out'], pending)
        right = _anchor(connection.right, b['item'], b['source_in'], pending)
        if connection.status == 'supported':
            if connection.relationship == 'motion_match':
                if (left['field'] != right['field'] or left['field'] not in ('camera_motion','subject_motion')
                        or left['value'] != right['value'] or left['value'] == 'mixed'):
                    raise ValueError('motion match requires known comparable matching directions on both sides')
            if connection.relationship == 'action_match' and not all(
                x['field'].startswith('action_') for x in (left,right)):
                raise ValueError('action match must cite observed action moments on both sides')
            if connection.relationship == 'visual_match' and not all(
                x['field'] in ('shot_scale','subject_position') for x in (left,right)):
                raise ValueError('visual match must cite known visual judgments on both sides')
        # Source-to-timeline translation retains each side's uncertainty. The exact
        # executed cut is an editorial choice, never a claim of exact perception.
        for anchor, shot in ((left,a),(right,b)):
            anchor['timeline_window'] = ([round(shot['timeline_in']+x-shot['source_in'],6)
                                           for x in anchor['source_window']]
                                          if anchor['source_window'] is not None else None)
            anchor['review_request'] = shot['review_request']
            anchor['candidate_id'] = shot['candidate_id']
        connections.append(dict(left_shot_id=a['shot_id'],right_shot_id=b['shot_id'],
                                status=connection.status,relationship=connection.relationship,
                                reason=connection.reason,cut_time=b['timeline_in'],left=left,right=right))
    return dict(schema_version='1.0.0',
                status='needs_connection_review' if any(x.status=='needs_review' for x in plan.connections) else 'shot_group_validated',
                plan=plan.model_dump(mode='json'), duration_seconds=cursor,
                shots=[{k:v for k,v in shot.items() if k!='item'} for shot in shots],
                connections=connections,
                reviews={key:{k:v for k,v in value.items() if k not in ('request','payload')}
                         for key,value in reviews.items()}, external_call_count=0)


def _decision(group, group_path, group_sha256):
    return dict(schema_version='0.1.0',project_name=group['plan']['project_name'],
                canvas={**group['plan']['canvas'],'duration_seconds':group['duration_seconds']},
                clips=[dict(kind='video',source_path=s['source_path'],track='main',
                            timeline_in=s['timeline_in'],source_in=s['source_in'],duration=s['duration'],gain=s['gain'])
                       for s in group['shots']],
                shot_group=dict(path=str(group_path),sha256=group_sha256))


def build_shot_group(plan_path: Path, output_dir: Path) -> dict:
    plan = ShotGroupPlan.model_validate_json(plan_path.read_text(encoding='utf-8'))
    group = _resolve(plan)
    output_dir = output_dir.expanduser().resolve()
    group_path = output_dir / 'group.json'
    if output_dir.exists():
        if not group_path.is_file() or _read(group_path) != group:
            raise ValueError('immutable shot group differs; use a new output directory for revisions')
        return inspect_shot_group(group_path)
    output_dir.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.shot-group-',dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        _write(staging / 'group.json',group)
        group_sha256 = _sha256_file(staging / 'group.json')
        decision_sha256 = None
        if group['status'] == 'shot_group_validated':
            _write(staging / 'edit_decision.json',_decision(group,group_path,group_sha256))
            decision_sha256 = _sha256_file(staging / 'edit_decision.json')
        _write(staging / 'receipt.json',dict(group_sha256=group_sha256,decision_sha256=decision_sha256))
        staging.rename(output_dir)
    return inspect_shot_group(group_path)


def inspect_shot_group(group_path: Path) -> dict:
    group_path = group_path.resolve()
    receipt = _read(group_path.parent / 'receipt.json')
    if receipt['group_sha256'] != _sha256_file(group_path):
        raise ValueError('shot group receipt hash mismatch')
    group = _read(group_path)
    current = _resolve(ShotGroupPlan.model_validate(group['plan']))
    if group != current:
        raise ValueError('shot group evidence differs from pinned fine review')
    decision_path = group_path.parent / 'edit_decision.json'
    if group['status'] == 'shot_group_validated':
        if receipt['decision_sha256'] != _sha256_file(decision_path) or _read(decision_path) != _decision(group,group_path,receipt['group_sha256']):
            raise ValueError('generated group decision differs from receipt')
    elif decision_path.exists() or receipt['decision_sha256'] is not None:
        raise ValueError('unresolved group must not contain an exportable decision')
    return dict(status=group['status'],group_path=str(group_path),
                decision_path=str(decision_path) if decision_path.exists() else None,
                shot_count=len(group['shots']),connection_count=len(group['connections']),
                duration_seconds=group['duration_seconds'],external_call_count=0)


def validate_group_export(decision) -> dict | None:
    """Called by the existing exporter before any package is created."""
    if decision.shot_group is None:
        return None
    binding = decision.shot_group
    path = binding.path.expanduser().resolve()
    if not path.is_file() or binding.sha256 != _sha256_file(path):
        raise ValueError('bound shot group is missing or hash differs')
    checked = inspect_shot_group(path)
    if checked['status'] != 'shot_group_validated':
        raise ValueError('unresolved connection blocks export')
    group = _read(path)
    expected = _decision(group,path,binding.sha256)
    videos = [clip.model_dump(mode='json') for clip in decision.clips if clip.kind=='video']
    for clip in videos:
        clip['source_path'] = str(Path(clip['source_path']).resolve())
    if (videos != expected['clips'] or decision.canvas.model_dump(mode='json') != expected['canvas']
            or decision.project_name != expected['project_name']):
        raise ValueError('EDL video order, source ranges, timing or canvas differs from bound shot group')
    return group
