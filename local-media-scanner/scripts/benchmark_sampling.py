"""Paired local extraction benchmark; no visual model or source mutations."""
import argparse
import json
import time
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scanner.config import SamplingConfig
from scanner.metadata import discover_videos, probe_video
from scanner.sampling import decode_probe_frames, select_representatives
import scanner.sampling as sampling


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=20)
    parser.add_argument('--optimized-only', action='store_true')
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    files = discover_videos(args.input)
    if not files:
        parser.error("no videos found")
    chosen = [files[i] for i in np.linspace(0, len(files)-1, min(args.count,len(files)), dtype=int)]
    benchmark_started = time.perf_counter()
    rows=[]
    original_run=sampling.subprocess.run
    for index, path in enumerate(chosen):
        metadata=probe_video(path)
        row={'file':str(path), 'source_size':path.stat().st_size, 'source_mtime_ns':path.stat().st_mtime_ns, 'metadata':metadata.model_dump(), 'measurements':{}}
        modes = ('auto',) if args.optimized_only else (('seek','auto') if index%2==0 else ('auto','seek'))
        outputs={}
        for mode in modes:
            calls=[]
            def counted(command, **kw):
                calls.append(command)
                return original_run(command, **kw)
            start=time.perf_counter()
            with patch.object(sampling.subprocess,'run',counted):
                frames=decode_probe_frames(path,metadata,args.output/f'{index:03d}'/mode,SamplingConfig(decode_strategy=mode, hardware_acceleration="none" if mode=="seek" else "auto"))
            elapsed=time.perf_counter()-start
            outputs[mode]=frames
            selected=select_representatives(frames,metadata.duration,'adaptive5')
            row['measurements'][mode]={'seconds':elapsed,'ffmpeg_calls':len(calls),'frames':len(frames),'selected_times':[f.timestamp for f in selected]}
        if not args.optimized_only:
            old,new=outputs['seek'],outputs['auto']
            row['same_target_times']=[f.timestamp for f in old]==[f.timestamp for f in new]
            row['mean_pixel_absolute_error']=float(np.mean([np.abs(a.image.astype(float)-b.image.astype(float)).mean() for a,b in zip(old,new)]))
        rows.append(row)
        report={'scope':'probe extraction only; '+('optimized full run' if args.optimized_only else 'paired alternating order')+'; warm filesystem cache possible','rows':rows,'external_model_calls':0}
        report['wall_seconds_so_far'] = time.perf_counter() - benchmark_started
        report['totals']={mode:{'seconds':sum(r['measurements'][mode]['seconds'] for r in rows),'ffmpeg_calls':sum(r['measurements'][mode]['ffmpeg_calls'] for r in rows)} for mode in modes}
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({'done':index+1,'file':path.name,**row['measurements'],'pixel_error':row.get('mean_pixel_absolute_error')},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
