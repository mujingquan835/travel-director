# Local Media Scanner Experiments

## Project bootstrap — 2026-08-27

- Method: create a Python 3.12 `uv` project with a strict Pydantic Schema and developer-only CLI.
- Parameters: Schema `0.1.0`; no model dependency group installed.
- Timing: dependency installation is recorded in the execution log, not treated as scan time.
- Accuracy: not applicable; no media analysis has run.
- Failures: none retained at this stage.
- Decision: retain strict nullable fields and reject unknown/Editorial Role keys.
- Next: Experiment 01, ffprobe metadata.

## Experiment 01 — FFprobe Metadata — 2026-08-27

- Method: recursively discover supported video extensions, call ffprobe once per file, parse the first video stream, and calculate manifest totals without decoding frames.
- Parameters: FFmpeg/ffprobe 8.1.1; extensions MOV, MP4, M4V, AVI, MKV; source directory read-only.
- Test evidence: five metadata tests cover controlled H.264 duration/dimensions/FPS, recursive case-insensitive discovery, corrupt input, relative paths/totals, and the `--input` CLI contract.
- Real input: 272 videos; 2811.135857 seconds (46.8523 minutes); 20,330,842,680 bytes; 270 HEVC and 2 H.264; 266 landscape and 6 portrait after rotation-aware orientation.
- Timing: 10.08 seconds wall time for 272 sequential ffprobe calls on the M1 Pro; 6.34 seconds user CPU and 2.80 seconds system CPU. This is Metadata time only.
- Accuracy: controlled metadata fixture passed. Real manifest counts and aggregate duration/bytes match the independent read-only inventory performed before implementation.
- Failures: the first real CLI attempt was rejected before reading media because `input` was accidentally positional. A failing CLI test reproduced the issue; `--input` is now explicit. No real media file failed ffprobe.
- Decision: retain sequential ffprobe for the baseline because 10.08 seconds for 272 files is acceptable and easier to audit. Parallelism is unnecessary for V0.1 unless later profiling shows a material bottleneck.
- Next: Experiment 02, bounded probe frames and temporal3 versus adaptive5 representative selection.

## Experiment 02 — Sparse Representative Frames — 2026-08-27

- Method: compare fixed temporal anchors at 20/50/80 percent with an adaptive profile that adds the highest optical-flow and HSV-histogram-change candidates, then merges near-duplicate evidence.
- Parameters: probe count `min(24, ceil(duration_seconds * 2))`; probe max edge 320 px; representative max edge 720 px; at most five representatives; minimum time gap `max(0.25 seconds, duration * 0.08)`; dHash duplicate threshold 5 bits.
- Test evidence: seven tests cover bounded counts, exact temporal anchors, motion/scene candidates, perceptual de-duplication, real FFmpeg decoding, auditable CLI output, input-side seek, and explicit VideoToolbox selection.
- Real smoke set: shortest 0.265-second clip, median 6.085-second clip, and longest 117.755-second clip from the 272-file inventory.
- Failed baseline: one sequential software FFmpeg decode per video took 0.96, 8.14, and 71.53 seconds for temporal3; adaptive5 took 0.91, 7.56, and 73.15 seconds. Limiting saved frames did not avoid decoding most of the long 4K/60fps HEVC stream.
- Software fast-seek probe: one input-side seek per target reduced the longest clip to 19.14 seconds but increased the median clip to 14.07 seconds because 13 FFmpeg process startups dominated.
- Rejected probe: a multi-input single-process FFmpeg attempt produced image2 muxer termination errors and used 18.42 seconds CPU for only three timestamps; it was not retained.
- VideoToolbox evidence: sequential hardware decode of the longest clip still took 24.12 seconds. Combining explicit VideoToolbox with input-side sparse seek produced 0.75, 7.29, and 10.67 seconds for the three clips; the full adaptive smoke run took 18.93 seconds wall time.
- Frame results: shortest clip yielded one frame; median clip yielded three frames with temporal, motion, and scene-change reasons merged; longest clip yielded four frames, including one separate motion candidate. Probe counts were 1, 13, and the hard maximum 24.
- Accuracy: representative-frame semantic sufficiency is not claimed here; this experiment validates bounded extraction behavior and records candidate reasons. Ground Truth comparison occurs after the 30-video set is frozen.
- Failures: the original temporal3 path visually de-duplicated its three fixed anchors, invalidating the baseline. The test caught this; temporal3 now preserves all available time anchors, while adaptive5 may visually de-duplicate.
- Decision: retain input-side sparse seek for cross-platform correctness and explicit `videotoolbox` acceleration for the M1 Pro benchmark. Do not silently fall back between hardware and software modes. The median clip remains slower than desired and must be included in the final performance conclusion.
- Next: Experiment 03, raw blur/exposure/motion metrics on the same probe frames.

## Experiment 03 — Blur, Exposure, and Motion CV — 2026-08-27

- Method: compute per-frame Laplacian variance, Rec.709-like luminance, dark/bright clipping ratios, and adjacent-frame Farneback optical flow. Aggregate frame quality by median; normalize flow by image diagonal and time delta.
- Parameters: dark pixels <=5, bright pixels >=250; provisional underexposure requires median brightness <0.18 and dark ratio >0.35; provisional overexposure requires brightness >0.82 and bright ratio >0.20; mixed exposure requires both dark ratio >0.25 and bright ratio >0.15.
- Test evidence: seven tests cover blur monotonicity, brightness/clipping direction, explicit null calibrated scores, translated-motion direction, directional concentration, brightness flash response, and CLI output.
- Real smoke timing: three-video VideoToolbox CV profile took 13.28 seconds wall time. Per-video decode-plus-CV times were 0.28 seconds (0.265-second clip), 4.85 seconds (6.085-second clip), and 7.93 seconds (117.755-second clip). Representative 720 px thumbnail extraction is not included in this CV-only command.
- Real raw distributions: median Laplacian variance was 2156.60, 2103.18, and 1841.25; median brightness was 0.407, 0.464, and 0.679. All three received the provisional `normal` exposure label.
- Motion evidence: the sub-second clip has no adjacent-frame evidence and correctly remains unknown. The median clip raw motion was 0.0580 with directional ratio 0.782; the longest clip raw motion was 0.00467 with directional ratio 0.929. Directional consistency does not imply high motion intensity.
- Accuracy: synthetic directionality tests passed, but no real blur, exposure, or motion accuracy is claimed before Ground Truth. `blur_score`, `motion_intensity`, `motion_level`, `static_or_dynamic`, and `quality_score` remain null/unknown.
- Failure boundary: a single frame cannot support motion; the Scanner must preserve unavailable evidence instead of classifying it as static.
- Decision: retain all raw CV fields and provisional exposure evidence. Do not calibrate blur, motion levels, or combined quality on the three-video smoke set.
- Next: freeze a diverse 30-video manifest and human Ground Truth before any detector or SigLIP2 inference.
