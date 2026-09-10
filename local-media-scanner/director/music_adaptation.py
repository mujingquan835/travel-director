"""Immutable music edit maps, honest listening provenance, and downstream binding."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from director.audio_import import load_music_evidence
from director.project import open_project, _sha256_file, _atomic_write, _canonical_bytes
from director.music_adaptation_schema import MusicAdaptationPlan


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path,value):
    _atomic_write(path,_canonical_bytes(value))


def _diff(before,after,path=''):
    if before==after:
        return []
    if isinstance(before,dict) and isinstance(after,dict) and set(before)==set(after):
        return [item for key in sorted(before) for item in _diff(before[key],after[key],path+'/'+key)]
    if isinstance(before,list) and isinstance(after,list) and len(before)==len(after):
        return [item for i,(a,b) in enumerate(zip(before,after)) for item in _diff(a,b,path+'/'+str(i))]
    return [dict(path=path or '/',before=before,after=after)]


def _resolve(plan):
    from director.fcpxml_delivery import FcpxmlEditDecision
    from director.shot_group import validate_group_export
    paths=open_project(plan.music_project.resolve())
    evidence=load_music_evidence(paths)
    if evidence is None:
        raise ValueError('music adaptation requires already selected and frozen project music')
    asset,structure=evidence
    source=(paths.root/asset.frozen_relative_path).resolve()
    base=FcpxmlEditDecision.model_validate_json(plan.base_decision.read_text(encoding='utf-8'))
    if base.music_adaptation is not None:
        raise ValueError('use the original picture base plus --parent; do not chain derived music EDLs as bases')
    group=validate_group_export(base)
    duration=base.canvas.duration_seconds
    listeners={x.listening_id:x for x in plan.listening}
    def listened(key,start,end):
        record=listeners.get(key)
        if record is None or record.source_in>start+1e-6 or record.source_out<end-1e-6:
            raise ValueError('listening record must cover the claimed source interval')
    for record in plan.listening:
        if record.source_out>asset.duration_seconds:
            raise ValueError('listening range exceeds frozen source')
    phrases={x.phrase_id:x for x in plan.phrases}
    for phrase in plan.phrases:
        if phrase.source_out>asset.duration_seconds:
            raise ValueError('phrase exceeds frozen music duration')
        if phrase.listening_id is not None:
            listened(phrase.listening_id,phrase.source_in,phrase.source_out)
    cursor=0
    music_clips=[]
    for mapping in plan.mapping:
        if abs(mapping.project_in-cursor)>1e-6:
            raise ValueError('mapping must cover project continuously; represent pauses explicitly as silence')
        cursor=mapping.project_out
        if mapping.kind=='music':
            if mapping.source_out>asset.duration_seconds:
                raise ValueError('mapped source interval exceeds frozen music')
            if mapping.phrase_id is not None:
                phrase=phrases.get(mapping.phrase_id)
                if phrase is None or phrase.source_in>mapping.source_in+1e-6 or phrase.source_out<mapping.source_out-1e-6:
                    raise ValueError('mapped segment must lie within its referenced phrase')
            music_clips.append(dict(kind='music',source_path=str(source),track='music-adaptation',
                                    timeline_in=mapping.project_in,source_in=mapping.source_in,
                                    duration=round(mapping.project_out-mapping.project_in,6),gain=mapping.gain))
    if abs(cursor-duration)>1e-6:
        raise ValueError('music map duration must equal the picture project duration')
    segments={x.segment_id:x for x in plan.mapping}
    for event in plan.events:
        segment=segments.get(event.segment_id)
        if segment is None or not segment.project_in<=event.project_time<=segment.project_out:
            raise ValueError('music event must lie in its mapped segment')
        if segment.kind=='music':
            expected=segment.source_in+event.project_time-segment.project_in
            if event.source_time is None or abs(expected-event.source_time)>1e-6:
                raise ValueError('music event source/project time mapping differs')
            if event.status=='listened':
                listened(event.listening_id,event.source_time,event.source_time)
        elif event.source_time is not None or event.status=='listened' or event.listening_id is not None:
            raise ValueError('inserted music pause is an editorial action, not a heard source event')
        if event.status=='proposed' and event.listening_id is not None:
            raise ValueError('proposed event must not pretend to be listened')
    final=plan.mapping[-1]
    if plan.ending.treatment=='source_end':
        if final.kind!='music' or abs(final.source_out-asset.duration_seconds)>1e-6:
            raise ValueError('source_end requires reaching the actual frozen music end')
    if plan.ending.treatment=='silence' and final.kind!='silence':
        raise ValueError('silence ending requires an explicit final music-silence interval')
    if plan.ending.treatment in ('cut','fade') and final.kind!='music':
        raise ValueError('cut/fade ending requires a final music segment')
    if plan.ending.listening_id is not None:
        if final.kind!='music':
            raise ValueError('inserted silence has no source listening record')
        listened(plan.ending.listening_id,final.source_in,final.source_out)
    pacing=[]
    events={x.event_id:x for x in plan.events}
    shots={x['shot_id']:x for x in group['shots']} if group else {}
    for choice in plan.pacing:
        if not group or not set(choice.shot_ids).issubset(shots):
            raise ValueError('picture pacing must reference known bound shot-group IDs')
        if choice.event_id is not None and choice.event_id not in events:
            raise ValueError('pacing references an unknown music event')
        item=choice.model_dump(mode='json')
        if choice.mode=='local_fast_cut':
            ordered=[x['shot_id'] for x in group['shots']]
            indices=[ordered.index(x) for x in choice.shot_ids]
            if indices!=list(range(indices[0],indices[0]+len(indices))):
                raise ValueError('fast-cut scope must be a contiguous ordered local group')
        if choice.mode=='internal_action':
            shot=shots[choice.shot_ids[0]]
            review=group['reviews'][shot['review_request']]
            observed=next(x['observation'] for x in _read(review['result_path'])['items']
                          if x['observation']['candidate_id']==shot['candidate_id'])
            moment=observed[choice.action_field]
            if moment is None:
                raise ValueError('internal action must be known in the fine review')
            time=shot['timeline_in']+moment['time_seconds']-shot['source_in']
            if not shot['timeline_in']<time<shot['timeline_in']+shot['duration']:
                raise ValueError('reviewed action is not inside the selected shot')
            uncertainty=moment['uncertainty_seconds']
            event=events[choice.event_id]
            if not shot['timeline_in']<event.project_time<shot['timeline_in']+shot['duration']:
                raise ValueError('music response event must fall inside the held shot')
            item['action_evidence']=dict(review_request=shot['review_request'],candidate_id=shot['candidate_id'],
                field=choice.action_field,source_time=moment['time_seconds'],
                timeline_time=time,uncertainty_seconds=uncertainty,
                evidence_frames=moment['evidence_frames'],
                alignment='within_observation_window' if abs(event.project_time-time)<=uncertainty else 'outside_observation_window',
                offset_seconds=round(event.project_time-time,6))
        pacing.append(item)
    # Automatic structure is included as a separate, explicitly unconfirmed view.
    hints=dict(interpretation='unconfirmed_candidates',bpm=structure.bpm,
               beat_times=structure.beats_seconds,downbeat_candidates=structure.downbeats_seconds,
               section_candidates=[s.model_dump(mode='json') for s in structure.sections],
               source_ending_candidate=structure.ending.model_dump(mode='json'),
               warning='Energy/position sections and every-fourth-beat markers are not confirmed phrases or downbeats; source ending does not imply target ending.')
    decision=base.model_dump(mode='json')
    decision['clips']=[c.model_dump(mode='json') for c in base.clips if c.kind!='music']+music_clips
    decision['music_adaptation']=None
    if base.sound_design is None:
        decision.pop('sound_design', None)
    if any(c['kind']!='music' and c['track']=='music-adaptation' for c in decision['clips']):
        raise ValueError('reserved music-adaptation track conflicts with existing audio/video')
    FcpxmlEditDecision.model_validate(decision)
    covered=[]
    for segment in plan.mapping:
        if segment.kind!='music':
            continue
        cursor=segment.source_in
        for record in sorted(plan.listening,key=lambda x:x.source_in):
            if record.source_in<=cursor+1e-6:
                cursor=max(cursor,record.source_out)
        covered.append(cursor>=segment.source_out-1e-6)
    listening_status=('not_listened' if not plan.listening else
                      'source_ranges_reviewed' if covered and all(covered) else 'partial_source_review')
    return dict(schema_version='1.0.0',status='needs_audio_processing' if plan.ending.treatment=='fade' else 'music_adaptation_validated',
                listening_status=listening_status,
                mix_listening_status='not_reviewed',
                plan=plan.model_dump(mode='json'),
                frozen_music=dict(project_path=str(paths.root),path=str(source),sha256=asset.source_sha256,
                                  asset_sha256=_sha256_file(paths.generated_music),analysis_sha256=_sha256_file(paths.music_structure)),
                base_decision_sha256=_sha256_file(plan.base_decision),automatic_hints=hints,
                resolved_pacing=pacing,decision=decision,external_call_count=0)


def _bound_decision(doc,path,digest):
    return {**doc['decision'],'music_adaptation':dict(path=str(path),sha256=digest)}


def _lineage(parent,plan,seen):
    if parent is None:
        return None,[]
    parent=parent.resolve()
    inspect_music_adaptation(parent,_seen=seen)
    document=_read(parent)
    if Path(document['plan']['music_project']).resolve()!=plan.music_project.resolve():
        raise ValueError('adaptation revisions retain frozen music project; use music replacement workflow for a new track')
    return dict(path=str(parent),sha256=_sha256_file(parent)),_diff(document['plan'],plan.model_dump(mode='json'))


def build_music_adaptation(plan_path: Path,output_dir: Path,parent: Path | None=None):
    plan=MusicAdaptationPlan.model_validate_json(plan_path.read_text(encoding='utf-8'))
    output_dir=output_dir.expanduser().resolve()
    path=output_dir/'adaptation.json'
    doc=_resolve(plan)
    linkage,changes=_lineage(parent,plan,{path})
    doc.update(parent=linkage,changes=changes)
    if output_dir.exists():
        if not path.is_file() or _read(path)!=doc:
            raise ValueError('immutable adaptation differs; use a new output and --parent for a revision')
        return inspect_music_adaptation(path)
    output_dir.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.music-adaptation-',dir=output_dir.parent) as temporary:
        staging=Path(temporary)
        _write(staging/'adaptation.json',doc)
        digest=_sha256_file(staging/'adaptation.json')
        decision_hash=None
        if doc['status']=='music_adaptation_validated':
            _write(staging/'edit_decision.json',_bound_decision(doc,path,digest))
            decision_hash=_sha256_file(staging/'edit_decision.json')
        _write(staging/'receipt.json',dict(adaptation_sha256=digest,decision_sha256=decision_hash))
        staging.rename(output_dir)
    return inspect_music_adaptation(path)


def inspect_music_adaptation(path: Path,_seen=None):
    path=path.resolve();seen=set(_seen or ())
    if path in seen or len(seen)>50:
        raise ValueError('cyclic or excessive music revision lineage')
    seen.add(path)
    doc=_read(path);receipt=_read(path.parent/'receipt.json')
    if receipt['adaptation_sha256']!=_sha256_file(path):
        raise ValueError('music adaptation hash differs from receipt')
    plan=MusicAdaptationPlan.model_validate(doc['plan'])
    expected=_resolve(plan)
    parent=doc.get('parent')
    if parent is not None and _sha256_file(Path(parent['path']))!=parent['sha256']:
        raise ValueError('music parent revision hash differs')
    linkage,changes=_lineage(Path(parent['path']) if parent else None,plan,seen)
    expected.update(parent=linkage,changes=changes)
    if expected!=doc:
        raise ValueError('music adaptation evidence or revision diff changed')
    decision=path.parent/'edit_decision.json'
    if doc['status']=='music_adaptation_validated':
        if receipt['decision_sha256']!=_sha256_file(decision) or _read(decision)!=_bound_decision(doc,path,receipt['adaptation_sha256']):
            raise ValueError('music adaptation EDL differs from immutable receipt')
    elif decision.exists() or receipt['decision_sha256'] is not None:
        raise ValueError('pending audio processing must not have an exportable EDL')
    return dict(status=doc['status'],listening_status=doc['listening_status'],mix_listening_status=doc['mix_listening_status'],
                adaptation_path=str(path),decision_path=str(decision) if decision.exists() else None,
                parent=doc['parent'],change_count=len(doc['changes']),external_call_count=0)


def validate_music_adaptation_export(decision):
    binding=decision.music_adaptation
    if binding is None:
        return None
    path=binding.path.resolve()
    if not path.is_file() or _sha256_file(path)!=binding.sha256:
        raise ValueError('bound music adaptation is missing or changed')
    if inspect_music_adaptation(path)['status']!='music_adaptation_validated':
        raise ValueError('music adaptation needs audio processing before export')
    doc=_read(path);expected=doc['decision']
    actual=decision.model_dump(mode='json')
    for kind in ('video','music'):
        if [x for x in actual['clips'] if x['kind']==kind]!=[x for x in expected['clips'] if x['kind']==kind]:
            raise ValueError('music adaptation picture/music EDL changed; create a revision')
    if any(actual[k]!=expected[k] for k in ('canvas','project_name','shot_group')):
        raise ValueError('music adaptation canvas or picture binding changed')
    return doc
