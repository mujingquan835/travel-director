"""Isolated draft-writing experiment; does not certify Jianying compatibility."""
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pyJianYingDraft as draft

ROOT = Path(__file__).resolve().parent
NAME = 'TD-P0-12s-code-20260909-v2'
OUTPUT = ROOT / 'drafts'


def _require_dir(env_name: str) -> Path:
    raw = os.environ.get(env_name)
    if not raw:
        raise SystemExit(
            f"Set {env_name} to a local directory before running this historical experiment script."
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"{env_name} is not a directory: {path}")
    return path


FOOTAGE = _require_dir("TRAVEL_DIRECTOR_FOOTAGE_DIR")
AUDIO_ROOT = _require_dir("TRAVEL_DIRECTOR_AUDIO_ROOT")
# Optional: absolute path to a frozen music wav used by the original trial.
MUSIC = Path(
    os.environ.get(
        "TRAVEL_DIRECTOR_EXPERIMENT_MUSIC",
        str(
            ROOT.parents[1]
            / "local-media-scanner/prototype/runs/travel-project-70811bf416/generation/assets/music-bd40015805a4621c.wav"
        ),
    )
).expanduser().resolve()
SPECS = [
    ('main_video', FOOTAGE / '2026_02_06_18_40_27_IMG_0235.MOV', 0, 1, 4, 0),
    ('main_video', FOOTAGE / '2026_02_07_13_24_51_IMG_0364.MOV', 4, 1, 4, 0),
    ('main_video', FOOTAGE / '2026_02_07_21_24_44_IMG_0504.MOV', 8, 2, 4, 0),
    ('music', MUSIC, 0, 0, 12, .35),
    ('whoosh', AUDIO_ROOT / '音效/风声/CZG_Whoosh_007.wav', 0, 0, 2.16, .8),
    ('subdrop', AUDIO_ROOT / '音效/上升音效/CZG_SubDrop_001.wav', 7.6, 0, 2.94, .75),
]

def us(seconds):
    return round(seconds * 1_000_000)

def main():
    started = time.monotonic()
    manifest = []
    for track, path, start, source, length, gain in SPECS:
        assert path.is_file(), path
        info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))
        duration = float(info['format']['duration'])
        assert source + length <= duration + .001, (path, duration)
        manifest.append(dict(track=track, path=str(path), target_start=start, source_start=source,
                             duration=length, gain=gain, source_duration=duration, size=path.stat().st_size))
    OUTPUT.mkdir(exist_ok=True)
    script = draft.DraftFolder(str(OUTPUT)).create_draft(NAME, 1920, 1080, fps=30, allow_replace=False)
    script.append_tracks([draft.TrackSpec(draft.TrackType.video, 'main_video')] +
                         [draft.TrackSpec(draft.TrackType.audio, n) for n in ('music', 'whoosh', 'subdrop')])
    for track, path, start, source, length, gain in SPECS:
        cls = draft.VideoSegment if track == 'main_video' else draft.AudioSegment
        clip = cls(str(path), draft.trange(us(start), us(length)),
                   source_timerange=draft.trange(us(source), us(length)), volume=gain)
        script.add_segment(clip, track)
    script.save()
    target = OUTPUT / NAME
    content = json.loads((target / 'draft_content.json').read_text())
    content['id'] = str(uuid.uuid4()).upper()
    content['name'] = NAME
    (target / 'draft_content.json').write_text(json.dumps(content, ensure_ascii=False, indent=2))
    meta_path = target / 'draft_meta_info.json'
    meta = json.loads(meta_path.read_text())
    meta.update(draft_id=content['id'], draft_name=NAME, draft_fold_path=str(target),
                draft_root_path=str(OUTPUT), tm_duration=us(12))
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    # Read serialized output independently: assert actual references and timings.
    assert content['duration'] == us(12)
    assert content['fps'] == 30
    assert content['canvas_config']['width'] == 1920 and content['canvas_config']['height'] == 1080
    tracks = content['tracks']
    assert len(tracks) == 4
    materials = {m['id']: m for group in content['materials'].values() if isinstance(group, list)
                 for m in group if isinstance(m, dict) and 'id' in m}
    actual = []
    for track in tracks:
        for seg in track['segments']:
            mat = materials[seg['material_id']]
            assert Path(mat['path']).is_file()
            actual.append((track['name'], mat['path'], seg['target_timerange']['start'],
                           seg['source_timerange']['start'], seg['target_timerange']['duration'], seg['volume']))
            assert seg['source_timerange']['duration'] == seg['target_timerange']['duration']
    expected = [(t, str(p), us(s), us(i), us(d), v) for t,p,s,i,d,v in SPECS]
    assert sorted(actual) == sorted(expected), (actual, expected)
    receipt = dict(status='draft_generated', structural_checks='passed',
                   jianying_open_edit_save='not_tested', client='macOS Jianying 11.4.0',
                   generator_commit=subprocess.check_output(['git', '-C', str(ROOT/'vendor/pyJianYingDraft'), 'rev-parse', 'HEAD'], text=True).strip(),
                   duration_seconds=12, tracks=4, video_segments=3, audio_segments=3,
                   media_model_calls=0, scan_count=0, elapsed_seconds=round(time.monotonic()-started, 3),
                   draft_path=str(target), media=manifest,
                   artifact_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.glob('*.json')})
    (ROOT/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('media','artifact_sha256')}, ensure_ascii=False))

if __name__ == '__main__':
    main()
