"""Evidence-constrained footage placement and additive, BGM-only review previews."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

from director.clip_selector import ClipSelectionConfig, place_clips
from director.creative_direction import _context, load_creative
from director.project import ProjectConflict, _canonical_bytes, _sha256_bytes, _sha256_file
from director.schema import MaterialScanResult, MotionEvidence, PeopleEvidence, QualityEvidence, TimelineSlot
from director.visual_schema import ClipObservationBatch, DirectorReview, DirectorTreatment
from scanner.schema import SourceRecord, TechnicalMetadata


def _publish(path: Path, data: bytes) -> None:
    """Publish once; a retry may reuse identical bytes but never replace a delivery."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ProjectConflict(f"preview artifact is a symlink: {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent) as stream:
        stream.write(data)
        stream.flush()
        try:
            os.link(stream.name, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ProjectConflict(f"preview artifact differs: {path}")


def _source(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or not path.resolve().is_relative_to(root.resolve()):
        raise ProjectConflict(f"source escapes input root: {relative}")
    return path.resolve()


def _metadata(path: Path) -> dict:
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,codec_name,width,height', '-of', 'json', str(path)],
        check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def build_placements(timeline, sections, observations, treatment, review, input_root: Path) -> dict:
    """Keep unknown evidence unknown; only core/candidate, section-listed sources qualify."""
    if review.status != 'completed':
        raise ProjectConflict('director review must be completed before placement')
    allowed_ids = set(treatment.core_materials + treatment.candidate_materials)
    blocked_ids = set(treatment.reject_suggestions + treatment.review_required)
    for override in review.overrides:
        if override.force_exclude or override.bucket_override in {'reject_suggestion', 'review_required', 'redundant'}:
            allowed_ids.discard(override.material_id)
            blocked_ids.add(override.material_id)
        elif override.bucket_override in {'core', 'candidate'} or override.force_include:
            allowed_ids.add(override.material_id)
            blocked_ids.discard(override.material_id)
    allowed_ids -= blocked_ids
    by_id = {item.material.material_id: item for item in observations.items}
    if len(by_id) != len(observations.items):
        raise ProjectConflict('duplicate observation material IDs')
    materials = []
    source_ids = {}
    unavailable = {}
    requested = {mid for section in sections for mid in section.material_ids}
    for mid in sorted(requested & allowed_ids):
        obs = by_id.get(mid)
        if obs is None or obs.observation_status in {'abstained', 'unavailable'}:
            unavailable[mid] = 'observation unavailable'
            continue
        ref = obs.material
        values = {a.field: a.value for a in obs.assertions if a.status in {'measured', 'confirmed'} and a.evidence_refs}
        if values.get('duration_seconds') != ref.duration_seconds or ref.duration_seconds <= 0:
            unavailable[mid] = 'measured duration unavailable'
            continue
        source = _source(input_root, ref.relative_path)
        try:
            metadata = _metadata(source)
            video = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
            if abs(float(metadata['format']['duration']) - ref.duration_seconds) > 0.15:
                raise ProjectConflict(f'source duration drifted: {ref.relative_path}')
        except (OSError, subprocess.CalledProcessError, KeyError, StopIteration, ValueError):
            unavailable[mid] = 'source missing or unprobeable'
            continue
        materials.append(MaterialScanResult(
            file=str(source), source=SourceRecord(relative_path=ref.relative_path, size_bytes=ref.size_bytes, mtime_ns=ref.mtime_ns),
            technical=TechnicalMetadata(duration=ref.duration_seconds, width=video['width'], height=video['height'],
                fps=ref.fps, orientation=ref.orientation, codec=video['codec_name']),
            analysis_status='partial', quality_evidence=QualityEvidence(laplacian_variance_raw=values.get('laplacian_variance_raw')),
            motion_evidence=MotionEvidence(motion_intensity_raw=values.get('motion_intensity_raw'),
                motion_level_candidate=values.get('motion_level')),
            people_evidence=PeopleEvidence(),
        ))
        source_ids[str(source)] = mid
    slots, constraints, section_by_slot = [], {}, {}
    cursor = 0.0
    seen = set()
    for slot in timeline.slots:
        if slot.slot_id in seen or abs(slot.start-cursor) > 1e-5 or slot.end <= slot.start or abs(slot.duration-(slot.end-slot.start)) > 1e-5:
            raise ProjectConflict('timeline slots must be unique, ordered, continuous and positive')
        seen.add(slot.slot_id)
        cursor = slot.end
        slots.append(TimelineSlot(**{k: getattr(slot, k) for k in TimelineSlot.model_fields if k != 'schema_version'}))
        # Same midpoint policy as fast delivery; never borrow from unrelated sections.
        section = next((s for s in sections if s.start <= (slot.start+slot.end)/2 < s.end), None)
        section_by_slot[slot.slot_id] = section
        constraints[slot.slot_id] = {path for path, mid in source_ids.items() if section and mid in section.material_ids}
    if abs(cursor - timeline.target_duration_seconds) > 1e-5:
        raise ProjectConflict('timeline does not cover target duration')
    chosen = place_clips(slots, materials, ClipSelectionConfig(), use_recommended_ranges=False,
                         allowed_files_by_slot=constraints)
    by_slot = {p.slot_id: p for p in chosen}
    rows = []
    for slot in slots:
        section = section_by_slot[slot.slot_id]
        placement = by_slot.get(slot.slot_id)
        mid = source_ids[placement.file] if placement else None
        rows.append(dict(slot_id=slot.slot_id, start=slot.start, end=slot.end,
            section_id=section.section_id if section else None,
            narrative_task=section.narrative_task if section else slot.content_need,
            material_gaps=section.material_gaps if section else ['no matching creative section'],
            allowed_material_ids=section.material_ids if section else [],
            material_id=mid, placement=placement.model_dump(mode='json') if placement else None,
            source_sha256=by_id[mid].material.source_sha256 if mid else None,
            unknown_fields=by_id[mid].unknown_fields if mid else [],
            evidence_refs=[r.model_dump(mode='json') for a in by_id[mid].assertions for r in a.evidence_refs] if mid else [],
            reason='Selected within creative section using measured duration, motion and quality; in/out is an editing proposal, not an observed event boundary.' if placement else 'No eligible source long enough in this creative section; slot retained as a gap.'))
    return dict(schema_version='1.0.0', status=chosen.status, target_duration_seconds=cursor,
        audio_mode='bgm_only', framing='contain_pad', external_call_count=0,
        unavailable_materials=unavailable, slots=rows)


def _validate_sources(report: dict) -> None:
    checked = set()
    for row in report['slots']:
        placement = row['placement']
        if not placement:
            continue
        source = Path(placement['file'])
        if not (0 <= placement['source_in'] < placement['source_out'] <= placement['source_duration'] + 1e-6):
            raise ProjectConflict('placement exceeds source duration')
        if source not in checked:
            if not source.is_file() or _sha256_file(source) != row['source_sha256']:
                raise ProjectConflict(f'selected source bytes drifted: {source.name}')
            checked.add(source)


def _markdown(report: dict) -> bytes:
    lines = ['# 真实素材填槽审阅', '', f"状态：{report['status']}；目标：{report['target_duration_seconds']} 秒。",
        '入出点为剪辑提案，未声称由稀疏抽帧定位事件。未知字段仍未知。',
        '预览采用完整画面缩放加黑边；仅 BGM，Hook / Outro / 原声混音留待 R07。', '',
        '| 槽位 | 时间 | 素材 / 入出点 | 选择依据及放宽 | 素材缺口 |', '|---|---|---|---|---|']
    for row in report['slots']:
        p = row['placement']
        material = f"{Path(p['file']).name}: {p['source_in']:.3f}–{p['source_out']:.3f}s" if p else '空槽'
        reason = row['reason'] + (' Relaxed: ' + ', '.join(p['relaxed_constraints']) if p else '')
        cells = [row['slot_id'], f"{row['start']:.3f}–{row['end']:.3f}", material, reason, '; '.join(row['material_gaps'])]
        lines.append('| ' + ' | '.join(str(x).replace('|', '\\|').replace('\n', ' ') for x in cells) + ' |')
    return ('\n'.join(lines)+'\n').encode()


def _render(report: dict, music: Path, output: Path, orientation: str) -> dict:
    """Render serial bounded segments; cumulative frame boundaries prevent rounding drift."""
    from director.render import _probe, _dimensions
    width, height = _dimensions(orientation)
    fps = 24
    with tempfile.TemporaryDirectory(prefix='.render-', dir=output.parent) as temp:
        root = Path(temp)
        for index, row in enumerate(report['slots']):
            p = row['placement']
            frames = round(row['end']*fps)-round(row['start']*fps)
            if frames < 1:
                raise ProjectConflict('slot shorter than one preview frame')
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-threads', '2',
                '-ss', str(p['source_in']), '-i', p['file'], '-an', '-vf',
                f'scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration=0.05',
                '-frames:v', str(frames), '-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p',
                str(root / f'{index:04d}.mp4')], check=True, capture_output=True)
        manifest = root / 'segments.txt'
        manifest.write_text(''.join(f"file '{i:04d}.mp4'\n" for i in range(len(report['slots']))))
        rendered = root / 'preview.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-f', 'concat', '-safe', '1', '-i', str(manifest),
            '-i', str(music), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
            '-t', str(report['target_duration_seconds']), '-movflags', '+faststart', str(rendered)], check=True, capture_output=True)
        duration, w, h, vcodec, acodec = _probe(rendered)
        if abs(duration-report['target_duration_seconds']) > 1/fps+0.01 or (w,h,vcodec,acodec) != (width,height,'h264','aac'):
            raise ProjectConflict('preview duration/dimensions/codecs failed validation')
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-threads', '2',
            '-i', str(rendered), '-f', 'null', '-'], check=True, capture_output=True)
        _validate_sources(report)
        if _sha256_file(music) != report['inputs']['music_sha256']:
            raise ProjectConflict('music changed during render')
        os.link(rendered, output)
    return dict(status='completed', sha256=_sha256_file(output), duration_seconds=duration,
                width=w, height=h, video_codec=vcodec, audio_codec=acodec)


def build_footage_preview(paths, input_root: Path, *, render: bool = False) -> dict:
    from director.audio_import import load_music_evidence
    from director.timeline_delivery_store import validate_timeline_delivery
    timeline = validate_timeline_delivery(paths)
    hashes, artifacts = _context(paths)
    creative = load_creative(paths, validate_sources=False)
    music_evidence = load_music_evidence(paths)
    if creative is None or music_evidence is None:
        raise ProjectConflict('preview requires verified creative and frozen music')
    asset, structure = music_evidence
    if structure.duration_seconds + 1e-6 < timeline.target_duration_seconds:
        raise ProjectConflict('BGM is shorter than target; preview cannot silently truncate')
    observations = ClipObservationBatch.model_validate(artifacts['clip_observations'])
    report = build_placements(timeline, creative[0].sections, observations,
        DirectorTreatment.model_validate(artifacts['director_treatment']),
        DirectorReview.model_validate(artifacts['director_review']), input_root)
    music = paths.root / asset.frozen_relative_path
    report['inputs'] = dict(source_artifact_hashes=hashes,
        timeline_receipt_sha256=_sha256_file(paths.root/'delivery/receipt.json'),
        creative_sha256=_sha256_bytes(_canonical_bytes(creative[0].model_dump(mode='json'))),
        music_sha256=_sha256_file(music), orientation=creative[1].orientation,
        algorithm_hashes={name: _sha256_file(Path(__file__).with_name(name)) for name in ['footage_preview.py', 'clip_selector.py', 'render.py']})
    _validate_sources(report)
    payload = _canonical_bytes(report)
    root = paths.root / 'previews' / _sha256_bytes(payload)[:20]
    if root.is_symlink() or (paths.root/'previews').is_symlink():
        raise ProjectConflict('preview directory must not be redirected')
    _publish(root/'placements.json', payload)
    _publish(root/'placements.md', _markdown(report))
    result = dict(status=report['status'], placement_json=str(root/'placements.json'),
                  placement_markdown=str(root/'placements.md'), audio_mode='bgm_only', external_call_count=0)
    if not render or report['status'] != 'completed':
        return result
    output, receipt_path = root/'preview.mp4', root/'receipt.json'
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        from director.render import _probe, _dimensions
        if receipt_path.is_symlink() or output.is_symlink() or not output.is_file():
            raise ProjectConflict('preview receipt or output missing or redirected')
        try:
            duration, w, h, vcodec, acodec = _probe(output)
        except (subprocess.CalledProcessError, OSError, ValueError, KeyError, StopIteration) as exc:
            raise ProjectConflict('existing preview cannot be probed') from exc
        expected = dict(status='completed', sha256=_sha256_file(output), duration_seconds=duration,
            width=w, height=h, video_codec=vcodec, audio_codec=acodec,
            placements_sha256=_sha256_bytes(payload), audio_mode='bgm_only', external_call_count=0)
        if receipt != expected or (w,h) != _dimensions(creative[1].orientation) or abs(duration-report['target_duration_seconds']) > 1/24+0.01 or (vcodec,acodec) != ('h264','aac'):
            raise ProjectConflict('preview receipt or output drifted')
    else:
        if output.exists():
            raise ProjectConflict('preview exists without receipt; preserve it and inspect before retry')
        try:
            receipt = _render(report, music, output, creative[1].orientation)
        except (subprocess.CalledProcessError, OSError, KeyError, StopIteration) as exc:
            message = str(exc)
            if isinstance(exc, subprocess.CalledProcessError):
                message = (exc.stderr or b'').decode(errors='replace')[-2000:]
            return {**result, 'status': 'failed', 'error': message}
        receipt.update(placements_sha256=_sha256_bytes(payload), audio_mode='bgm_only', external_call_count=0)
        _publish(receipt_path, _canonical_bytes(receipt))
    return {**result, 'preview': str(output), 'preview_receipt': str(receipt_path), 'render': receipt}
