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
