"""Bounded local temporal evidence and immutable session-authored shot observations."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from director.project import _atomic_write, _canonical_bytes, _sha256_bytes, _sha256_file
from director.shot_review_schema import (
    CompactShotReview, HashedReviewFile, ReviewFrame, ShotPacket,
    ShotReviewRequest, ShotSelection,
)
from director.visual_schema import ClipObservationBatch


RECIPE = 'dense-pts-v1-8fps-640px'
UPSTREAM = ('visual/run_contract.json', 'visual/scanner_only.json')
JUDGMENT_VALUES = {
    'shot_scale': {'extreme_wide', 'wide', 'medium', 'close', 'extreme_close', 'changing'},
    'subject_position': {'upper_left', 'upper_center', 'upper_right', 'middle_left',
                         'center', 'middle_right', 'lower_left', 'lower_center',
                         'lower_right', 'changing'},
    'camera_motion': {'static', 'pan_left', 'pan_right', 'tilt_up', 'tilt_down',
                      'push_in', 'pull_out', 'track_left', 'track_right',
                      'roll_clockwise', 'roll_counterclockwise', 'mixed'},
    'subject_motion': {'static', 'left_to_right', 'right_to_left', 'up', 'down',
                       'toward_camera', 'away_from_camera', 'clockwise',
                       'counterclockwise', 'mixed'},
}


def _read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path: Path, value):
    _atomic_write(path, _canonical_bytes(value))


def _source(root: Path, material) -> Path:
    path = (root / material.relative_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('source is missing or escapes input root')
    if path.stat().st_size != material.size_bytes or _sha256_file(path) != material.source_sha256:
        raise ValueError(f'source hash changed: {material.relative_path}')
    return path


def _identity(project: Path, input_root: Path, upstream: dict, selection: ShotSelection):
    return _sha256_bytes(_canonical_bytes(dict(
        project_path=str(project), input_root=str(input_root), upstream_hashes=upstream,
        selection=selection.model_dump(mode='json'), recipe=RECIPE,
    )))


def _extract_frames(source: Path, start: float, end: float, folder: Path) -> list[ReviewFrame]:
    """One local decode for this interval; retain selected decoder PTS, not fps-grid guesses.

    FFmpeg accurate input seek subtracts the seek offset from output PTS. With no
    setpts/fps synthesis, source-relative timestamps are seek offset + showinfo PTS.
    Selection keeps the first available frame, then frames at least 1/8s apart.
    """
    folder.mkdir(parents=True)
    # End is absolute in the post-seek PTS domain. trim=duration would count
    # from the first decoded frame and overshoot on non-frame-aligned/VFR seeks.
    filters = (f"trim=start=0:end={end-start:.9f},"
               "select='isnan(prev_selected_t)+gte(t-prev_selected_t,0.125)',"
               "scale=640:640:force_original_aspect_ratio=decrease,setsar=1,showinfo")
    process = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostdin', '-nostats', '-ss', f'{start:.9f}',
         '-i', str(source), '-map', '0:v:0', '-an', '-sn', '-dn', '-vf', filters,
         '-fps_mode', 'vfr', '-q:v', '3', str(folder / 'frame-%04d.jpg')],
        capture_output=True, text=True, timeout=90, check=False,
    )
    if process.returncode:
        raise ValueError(f'local frame extraction failed: {process.stderr[-1500:]}')
    times = [float(value) + start for value in re.findall(
        r'\[Parsed_showinfo_[^\]]+\].*?\bn:\s*\d+\s+pts:.*?pts_time:([\d.eE+\-]+)', process.stderr)]
    paths = sorted(folder.glob('frame-*.jpg'))
    if not paths or len(paths) != len(times):
        raise ValueError('decoder timestamp/frame count mismatch')
    if any(t < start-1e-5 or t >= end+1e-5 for t in times):
        raise ValueError('decoded frame lies outside requested source interval')
    return [ReviewFrame(path=f'{folder.name}/{path.name}', sha256=_sha256_file(path),
                        source_time=round(t, 6)) for path, t in zip(paths, times)]


def _sheets(root: Path, frames: list[ReviewFrame], prefix: str) -> list[HashedReviewFile]:
    """Twelve ordered frames per sheet; global frame IDs match compact evidence indices."""
    outputs = []
    for offset in range(0, len(frames), 12):
        batch = frames[offset:offset+12]
        canvas = Image.new('RGB', (960, ((len(batch)+2)//3)*210), 'white')
        draw = ImageDraw.Draw(canvas)
        for i, frame in enumerate(batch):
            x, y = i % 3 * 320, i // 3 * 210
            with Image.open(root / frame.path) as source:
                picture = source.convert('RGB')
            picture.thumbnail((312, 180))
            canvas.paste(picture, (x+(320-picture.width)//2, y+(180-picture.height)//2))
            picture.close()
            draw.text((x+5, y+186), f'#{offset+i} source {frame.source_time:.3f}s', fill='black')
        output = root / f'{prefix}-sheet-{offset//12:02d}.jpg'
        canvas.save(output, quality=90)
        canvas.close()
        outputs.append(HashedReviewFile(path=output.name, sha256=_sha256_file(output)))
    return outputs


def prepare_shot_review(project: Path, selection_path: Path) -> dict:
    project = project.expanduser().resolve()
    selection = ShotSelection.model_validate_json(selection_path.read_text(encoding='utf-8'))
    contract = _read(project / UPSTREAM[0])
    coarse = ClipObservationBatch.model_validate_json((project / UPSTREAM[1]).read_text(encoding='utf-8'))
    input_root = Path(contract['input_root']).resolve()
    materials = {item.material.material_id: item.material for item in coarse.items}
    membership = {x['relative_path']: x['source_sha256'] for x in contract['media']}
    sources = {}
    for candidate in selection.items:
        material = materials.get(candidate.material_id)
        if material is None or membership.get(material.relative_path) != material.source_sha256:
            raise ValueError('candidate is not a known project material')
        if candidate.source_out > material.duration_seconds:
            raise ValueError('candidate interval exceeds source duration')
        if material.material_id not in sources:
            sources[material.material_id] = _source(input_root, material)
    upstream = {name: _sha256_file(project / name) for name in UPSTREAM}
    key = _identity(project, input_root, upstream, selection)
    root = project / 'visual/shot_reviews'
    destination = root / key
    request_path = destination / 'request.json'
    if destination.exists():
        reply = inspect_shot_review(request_path)
        return {**reply, 'cache_hit': True}
    root.mkdir(parents=True, exist_ok=True)
    # Publish the complete immutable evidence bundle only after all decodes succeed.
    with tempfile.TemporaryDirectory(prefix='.preparing-', dir=root) as temporary:
        staging = Path(temporary)
        packets = []
        for index, candidate in enumerate(selection.items):
            candidate_id = f'shot-{index:03d}'
            frames = _extract_frames(sources[candidate.material_id], candidate.source_in,
                                     candidate.source_out, staging / candidate_id)
            packets.append(ShotPacket(
                candidate_id=candidate_id, candidate=candidate,
                material=materials[candidate.material_id], frames=frames,
                sheets=_sheets(staging, frames, candidate_id),
            ))
        # Detect changing sources/upstream while extraction was in progress.
        for material_id in sources:
            _source(input_root, materials[material_id])
        if upstream != {name: _sha256_file(project / name) for name in UPSTREAM}:
            raise ValueError('upstream observations changed during preparation')
        request = ShotReviewRequest(request_id=key, project_path=str(project), input_root=str(input_root),
                                    upstream_hashes=upstream, selection=selection, packets=packets)
        _write(staging / 'request.json', request.model_dump(mode='json'))
        _write(staging / 'preparation.json', {'request_sha256': _sha256_file(staging / 'request.json')})
        _write(staging / 'response.schema.json', CompactShotReview.model_json_schema())
        _write(staging / 'response.template.json', {'items': [_unknown_item(p.candidate_id) for p in packets]})
        staging.rename(destination)
    return {**inspect_shot_review(request_path), 'cache_hit': False}


def _unknown_item(candidate_id: str) -> dict:
    return dict(candidate_id=candidate_id, source_in=None, source_out=None, range_confidence=None,
                range_evidence_frames=[], range_reason='REPLACE: explain unknown usable range',
                **{field: dict(value=None, confidence=None, evidence_frames=[],
                               reason='REPLACE: explain uncertainty') for field in JUDGMENT_VALUES},
                action_description=None, action_start=None, action_accent=None, action_end=None,
                action_unknown_reason='REPLACE: explain unobserved action moments')


def _load_verified(request_path: Path) -> ShotReviewRequest:
    request_path = request_path.resolve()
    request = ShotReviewRequest.model_validate_json(request_path.read_text(encoding='utf-8'))
    if _read(request_path.parent / 'preparation.json')['request_sha256'] != _sha256_file(request_path):
        raise ValueError('request hash changed')
    project = Path(request.project_path).resolve()
    if request_path != project / 'visual/shot_reviews' / request.request_id / 'request.json':
        raise ValueError('request path is not its reserved project path')
    if request.request_id != _identity(project, Path(request.input_root), request.upstream_hashes, request.selection):
        raise ValueError('request identity mismatch')
    if set(request.upstream_hashes) != set(UPSTREAM):
        raise ValueError('request upstream membership mismatch')
    for name, digest in request.upstream_hashes.items():
        if _sha256_file(project / name) != digest:
            raise ValueError('upstream hash changed; prepare a new review')
    if len(request.selection.items) != len(request.packets):
        raise ValueError('packet membership mismatch')
    checked_sources = set()
    for index, (candidate, packet) in enumerate(zip(request.selection.items, request.packets)):
        if packet.candidate != candidate or packet.candidate_id != f'shot-{index:03d}' or packet.material.material_id != candidate.material_id:
            raise ValueError('candidate packet mismatch')
        if candidate.material_id not in checked_sources:
            _source(Path(request.input_root).resolve(), packet.material)
            checked_sources.add(candidate.material_id)
        times = [f.source_time for f in packet.frames]
        if times != sorted(set(times)) or times[0] < candidate.source_in-1e-5 or times[-1] >= candidate.source_out+1e-5:
            raise ValueError('invalid source timestamps')
        for evidence in [*packet.frames, *packet.sheets]:
            path = (request_path.parent / evidence.path).resolve()
            if not path.is_relative_to(request_path.parent) or not path.is_file() or _sha256_file(path) != evidence.sha256:
                raise ValueError('review evidence hash mismatch or escaped path')
    return request


def _times(packet: ShotPacket, indices: list[int], minimum: int = 1, dense: bool = False):
    if len(indices) < minimum or indices != sorted(set(indices)) or any(i < 0 or i >= len(packet.frames) for i in indices):
        raise ValueError('frame evidence must contain ordered, unique valid frame indices')
    times = [packet.frames[i].source_time for i in indices]
    if dense and (any(b != a+1 for a, b in zip(indices, indices[1:]))
                  or any(b-a > .251 for a,b in zip(times,times[1:]))):
        raise ValueError('motion/action claims require consecutive dense temporal evidence')
    return times


def _validate_observations(request: ShotReviewRequest, compact: CompactShotReview):
    packets = {p.candidate_id: p for p in request.packets}
    if len(compact.items) != len(packets) or {x.candidate_id for x in compact.items} != set(packets):
        raise ValueError('review must cover each requested candidate exactly once')
    for item in compact.items:
        packet = packets[item.candidate_id]
        lower, upper = packet.candidate.source_in, packet.candidate.source_out
        if item.source_in is not None:
            if not lower <= item.source_in < item.source_out <= upper:
                raise ValueError('proposed source range exceeds observed interval')
            times = _times(packet, item.range_evidence_frames, 2)
            if abs(times[0]-item.source_in) > .251 or abs(times[-1]-item.source_out) > .251:
                raise ValueError('proposed range needs frame evidence at both boundaries')
        for field, allowed in JUDGMENT_VALUES.items():
            observation = getattr(item, field)
            if observation.value is None:
                continue
            if observation.value not in allowed:
                raise ValueError(f'unsupported {field} value')
            temporal = field in ('camera_motion', 'subject_motion') or observation.value == 'changing'
            _times(packet, observation.evidence_frames, 3 if temporal else 1, temporal)
        for name in ('action_start', 'action_accent', 'action_end'):
            moment = getattr(item, name)
            if moment is None:
                continue
            times = _times(packet, moment.evidence_frames, 2, True)
            if not lower <= moment.time_seconds <= upper or not times[0] <= moment.time_seconds <= times[-1]:
                raise ValueError('action moment lies outside temporal evidence')
            # A dense still sequence supports a bracket, not invented frame accuracy.
            if (moment.time_seconds-moment.uncertainty_seconds > times[0]+1e-6
                    or moment.time_seconds+moment.uncertainty_seconds < times[-1]-1e-6):
                raise ValueError('action uncertainty must cover its observed frame bracket')
        reasons = [item.range_reason, item.action_unknown_reason or '',
                   *[getattr(item, f).reason for f in JUDGMENT_VALUES]]
        if any('REPLACE:' in reason for reason in reasons):
            raise ValueError('replace template uncertainty reasons with actual observations')


def _result_payload(request_path, request, compact):
    packets = {p.candidate_id:p for p in request.packets}
    return dict(schema_version='1.0.0', status='shot_review_validated',
                provider='invoking_agent', external_call_count=0,
                request_sha256=_sha256_file(request_path), items=[
                    dict(observation=x.model_dump(mode='json'),
                         material=packets[x.candidate_id].material.model_dump(mode='json'),
                         evidence=packets[x.candidate_id].model_dump(mode='json')) for x in compact.items])


def submit_shot_review(request_path: Path, observations_path: Path) -> dict:
    request_path = request_path.resolve()
    request = _load_verified(request_path)
    compact = CompactShotReview.model_validate_json(observations_path.read_text(encoding='utf-8'))
    _validate_observations(request, compact)
    payload = _result_payload(request_path, request, compact)
    destination = request_path.parent / 'results'
    if destination.exists():
        if _read(destination / 'observations.json') != payload:
            raise ValueError('immutable review differs; prepare a new selection/reason for a revision')
    else:
        with tempfile.TemporaryDirectory(prefix='.result-', dir=request_path.parent) as temporary:
            staging = Path(temporary)
            _write(staging / 'observations.json', payload)
            _write(staging / 'receipt.json', {'result_sha256': _sha256_file(staging / 'observations.json'),
                                             'request_sha256': _sha256_file(request_path)})
            staging.rename(destination)
    return inspect_shot_review(request_path)


def inspect_shot_review(request_path: Path) -> dict:
    request_path = request_path.resolve()
    request = _load_verified(request_path)
    result_path = request_path.parent / 'results/observations.json'
    status = 'needs_shot_observation'
    if result_path.exists():
        receipt = _read(result_path.parent / 'receipt.json')
        if receipt != dict(result_sha256=_sha256_file(result_path), request_sha256=_sha256_file(request_path)):
            raise ValueError('result receipt hash mismatch')
        payload = _read(result_path)
        compact = CompactShotReview.model_validate({'items':[x['observation'] for x in payload['items']]})
        _validate_observations(request, compact)
        if payload != _result_payload(request_path, request, compact):
            raise ValueError('result evidence does not match request')
        status = 'shot_review_validated'
    return dict(status=status, request_path=str(request_path),
                result_path=str(result_path) if result_path.exists() else None,
                response_template=str(request_path.parent / 'response.template.json'),
                response_schema=str(request_path.parent / 'response.schema.json'),
                candidates=[dict(candidate_id=p.candidate_id, source_in=p.candidate.source_in,
                                 source_out=p.candidate.source_out, frame_count=len(p.frames),
                                 sheets=[str(request_path.parent / s.path) for s in p.sheets]) for p in request.packets],
                external_call_count=0)
