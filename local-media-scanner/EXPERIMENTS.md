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

## Experiment 04 — Frozen 30-video Ground Truth — 2026-08-27

- Method: build a deterministic model-free candidate set from metadata rarity strata, render midpoint contact cards, then inspect 3–5 adaptive sparse frames per clip before writing human labels. No detector, CLIP, or SigLIP output was available during annotation.
- Parameters: seed 20260827; 30 clips selected from 272; VideoToolbox adaptive5 review profile; compact V0.1 scene and material-role taxonomies; nullable labels for unreadable footage.
- Selected set: 476.327695 seconds (7.94 minutes), 2,983,893,228 bytes; 28 landscape and 2 portrait; two clips under 3 seconds, 22 clips from 3–30 seconds, and six clips over 30 seconds.
- Review extraction timing: 238.08 seconds accumulated decode/extract time for 30 clips. The result contains 111 representative frames: three clips with one frame, three with three frames, 17 with four frames, and seven with five frames.
- Annotation evidence: `ground_truth.json` validates as 30 unique items and matches all 30 manifest filenames exactly. The root and `benchmark/ground_truth.json` copies are byte-identical.
- Failures: one horse-show clip carries a `-90` Display Matrix although its encoded landscape pixels are visually upright with `-noautorotate`. Default FFmpeg autorotation therefore produces sideways content. This is retained as a source metadata/content conflict requiring manual review, not "fixed" by disabling autorotation globally. One near-black one-second clip and one severely obstructed vertical clip are `unusable` and intentionally abstain on content and shot scale.
- Accuracy: this is reference creation, not a model accuracy result. Dense crowd counts and distant age classes remain approximate and are documented in annotation notes.
- Decision: retain the frozen set and explicit abstentions. Do not use this same 30-clip set to tune thresholds and then report the tuned score as an unbiased generalization result.
- Next: evaluate a lightweight local person/object detector without modifying the frozen labels.

## Experiment 05 — Lightweight COCO Detector — 2026-08-27

- Method: run Torchvision `ssdlite320_mobilenet_v3_large` with default COCO V1 weights on each 320 px adaptive representative frame, batch size one, score threshold 0.5, and CPU inference. Video decode remains local with explicit VideoToolbox acceleration.
- Dependencies: torch 2.13.0, torchvision 0.28.0, transformers 5.16.1; MPS is built and available but was not used for this CPU detector baseline. Installing the vision dependency group increased the project virtual environment from 183 MB to 808 MB; the shared uv cache measured 2.5 GB after installation.
- Model asset: 13.4 MiB at `.cache/models/torchvision/checkpoints/ssdlite320_mobilenet_v3_large_coco-a79551df.pth`; SHA-256 `a79551df90c79834bcd3bb3845ef9d966b5449a3a9b2833ae8404778ca5d65d2`.
- Test evidence: five detector tests cover per-frame people counts, threshold filtering, object ordering, empty-frame negative evidence, and CLI evidence serialization. The full suite passes 35 tests.
- Cold five-video smoke: 82.11 seconds wall time including a slow 13.4 MiB weight download; the run JSON measured 53.01 seconds model download/load and 81.44 seconds total. External process peak RSS was 710,443,008 bytes.
- Warm five-video smoke: 30.33 seconds wall time; run JSON measured 1.84 seconds model load, 29.62 seconds total, 27.78 seconds combined per-item decode plus inference, and 2.71 seconds detector inference across 18 representative frames. Observed in-process RSS was 404,750,336 bytes; external maximum RSS was 711,213,056 bytes.
- People result against frozen Ground Truth: all five `people_present` labels matched. Maximum detected counts were 0, 2, 0, 0, 1 versus human estimates 0, 4, 0, 0, 2, so the detector systematically undercounted partially visible/background people; count MAE on this small smoke set is 0.6.
- Object result: cars were supported in three of four night-road frames and people in two of three parking frames. The detector produced no object above threshold for illuminated storefront/gate footage, and misclassified a three-wheel vehicle as `airplane` with score 0.768.
- Failure boundary: COCO detection is useful evidence for `people_present`, rough lower-bound people count, person geometry, cars, and common objects. It is not reliable for travel-specific signs, gates, architecture, exact crowds, or unrestricted `main_objects`.
- Decision: retain SSDLite as a lightweight independent detector, but never treat its people count as exact and never use its COCO object list as the complete scene description. Keep raw per-frame detections for fusion and ablation.
- Full 30-video warm run: 182.54 seconds wall time for 115 representative frames and 478 probe frames. JSON timing measured 1.31 seconds model load, 17.73 seconds detector inference, and 180.57 seconds total; external maximum RSS was 720,338,944 bytes. Sparse decode and FFmpeg process startup, not detector inference, dominated elapsed time.
- Full-set `people_present`: 28 evaluable clips after two Ground Truth abstentions; coverage 0.933, accuracy 0.786, precision 0.867, recall 0.765, and F1 0.813 (TP 13, FP 2, TN 9, FN 4). False negatives included a fountain crowd, metadata-conflicted horse show, distant stage performance, and cooking hands; two architectural scenes produced false people detections.
- Full-set people count: maximum per-frame count MAE was 6.14 with a 0.607 undercount rate. Dense crowds make the field not reliable as an exact count; retain it only as lower-bound evidence.
- Full-set `main_objects`: exact match 0.033, micro precision 0.364, and micro recall 0.125 under exact compact-label comparison. COCO coverage is structurally inadequate for architecture, signage, costumes, stages, food context, and other travel-specific objects.
- Revised decision after the 30-video run: `people_present` remains a useful candidate evidence source, not a reliable standalone field. Exact `people_count_estimate` and unrestricted `main_objects` are not reliable enough for V0.1 from SSDLite alone.
- Next: add SigLIP2 zero-shot evidence on CPU and MPS without changing the frozen Ground Truth.

## Experiment 06 — Full 30-video Traditional CV Profile — 2026-08-27

- Method: run the Experiment 03 raw quality and optical-flow measurements on all frozen 30 videos using adaptive5 probes and explicit VideoToolbox decoding. No learned vision model or Ground Truth value enters the raw calculation.
- Timing: 162.20 seconds wall time; 68.45 seconds user CPU, 36.29 seconds system CPU, 720,093,184 bytes external maximum RSS, and 161.13 seconds summed per-item elapsed time.
- Raw distributions across videos: Laplacian variance min/median/p90/max 92.37/1681.67/3372.73/5361.78; brightness 0.120/0.505/0.654/0.686; motion intensity 0.00004/0.01897/0.05673/0.06499; directional ratio 0.322/0.656/0.914/0.998; luma-change p90 0.051/0.459/0.609/0.792.
- Exposure pilot result: the provisional rules matched 20 of 30 human labels (0.667 accuracy). Most errors were mixed-light scenes classified as normal; two underexposed clips were also classified as normal. The thresholds do not yet support a reliable final `exposure_status`.
- Motion pilot result: raw optical flow did not order the human labels monotonically. Human-high clips had median 0.0105, human-medium clips 0.0263, and the two human-low clips 0.0584. Sparse inter-frame flow is confounded by subject motion, camera motion, temporal spacing, and scene changes.
- Failure boundary: these are same-set pilot comparisons, not unbiased calibrated accuracy. `blur_score`, `motion_intensity`, `motion_level`, `static_or_dynamic`, and `quality_score` remain null/unknown until an independently defensible mapping exists.
- Decision: retain raw Laplacian, brightness, clipping, optical-flow, directional, and luma-change evidence. Do not convert raw motion to low/medium/high with a single threshold in V0.1; report the categorical field as not reliable enough unless a later method materially improves separation.
- Next: complete the pinned SigLIP2 download and compare semantic and Shot Scale evidence on the unchanged 30-video Ground Truth.

## Experiment 07 — Pinned SigLIP2 Zero-shot Evidence — 2026-08-28

- Method: download `google/siglip2-base-patch16-224` at immutable revision `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`; encode adaptive5 representative frames and versioned English prompt ensembles for Scene, Shot Scale, people type, action, and compact objects. Aggregate frame winners at video level without modifying Ground Truth.
- Model asset: official `model.safetensors` is 1,500,800,904 bytes with verified SHA-256 `612923381c76ec5a9bed335d1c48827e3f2e506ac31b044b63b2031fadee6a0b`. The Hugging Face cache measured 1.7 GB including abandoned partial-download files; those residual files are not model evidence.
- Loader failures and fix: the repository name contains SigLIP2 but its config resolves as `SiglipConfig` to `SiglipModel`. Forcing `Siglip2Model` produced patch/position-embedding dimension mismatches. The official cached model card uses `AutoModel`; a regression test now enforces config-driven loading. Transformers 5.16 also returns `BaseModelOutputWithPooling` from `get_image_features`/`get_text_features`; a second regression test selects the 768-dimensional `pooler_output` while retaining Tensor compatibility.
- Remaining warning: Transformers 5.16 reports legacy BOS/EOS IDs outside a 32k vocabulary during config construction. Local inference succeeds, but the warning is retained as unresolved compatibility evidence rather than hidden.
- CPU/MPS one-video smoke: both completed on four representative frames. CPU measured 2.60 seconds load, 1.35 seconds model inference, 11.84 seconds JSON total, and 1.58 GB external peak RSS. MPS measured 4.07 seconds load, 3.47 seconds inference, 15.35 seconds total, 0.99 GB external peak RSS, and 1.50 GB MPS allocated memory after the run.
- CPU/MPS five-video comparison: CPU measured 2.73 seconds model inference and 30.32 seconds total; MPS measured 1.89 seconds inference and 30.73 seconds total. All per-frame top-1 labels matched, with maximum absolute score difference `4.33e-7`. Decode/process startup dominates total time, so this set does not show an end-to-end MPS speed advantage.
- Full 30-video MPS run: 172.66 seconds external wall time; JSON measured 4.32 seconds model load, 6.16 seconds model inference, and 170.86 seconds total. External peak RSS was 988,020,736 bytes; observed process RSS in JSON was 769,163,264 bytes and MPS allocated memory was 1,500,884,480 bytes.
- Scene result: 28 evaluable clips, ungated top-1 accuracy 0.464. Predictions overused `other` for 13 clips, including many theme-park performances and buildings. Median winning margin was 0.014. The provisional 0.08 margin gate abstained on all 28 clips, proving that threshold incompatible with these cosine-score distributions.
- Shot Scale result: 28 evaluable clips, ungated top-1 accuracy 0.536. Predictions contained 9 wide, 8 medium, and 11 close, but no close_up or aerial. All four human close_up clips were missed; aerial had no Ground Truth support. Median winning margin was 0.0047 and the provisional gate abstained on every clip.
- People-type result: among 17 clips with defensible age labels, the single top-1 prediction appeared in the human label set for 16/17 clips. This aggregate is class-imbalanced: adult support was 17 and child support only 3; child precision was 0.50 and recall 0.333. Child/adult is therefore only candidate evidence, not a reliable V0.1 field.
- Action result: exact accuracy was 0/27. The fixed prompt classes omit many observed actions in Ground Truth, including camera pan/tilt, stage performance, driving, boarding, group pose, cooking, and specific watching/interaction events. This is a taxonomy and visual-evidence mismatch, not a threshold-only problem.
- Object result: one aggregated top object appeared in the human object set for 18/30 clips, but one-label micro recall over all human objects was only 0.188. The nine prompt classes covered only 0.365 of human object labels; exact unrestricted `main_objects` remains structurally unsupported.
- Decision: retain pinned SigLIP2 raw per-frame embeddings/scores as candidate evidence and retain explicit CPU/MPS selection. Do not emit confident Scene, Shot Scale, Action, child/adult, or unrestricted object fields from the current zero-shot prompts alone. Do not tune the same 30 labels until a favorable score appears; report the pilot limitations and use geometry/detector fusion only where independent evidence exists.
- Next: evaluate conservative fusion, especially person-geometry Shot Scale, and preserve abstentions when semantic evidence is weak.

## Experiment 08 — Shot Scale Fusion and Material Role Rules — 2026-08-28

- Method: replay the saved 30-video SSDLite person boxes and SigLIP2 Shot Scale scores without rerunning either model. Compare the provisional SigLIP margin gate, maximum detected-person height geometry, and geometry-plus-SigLIP fusion against the unchanged Ground Truth.
- Geometry parameters: maximum person height per frame divided by decoded frame height; median across frames; `<=0.35` wide, `0.35–0.70` medium, `>0.70` close. Geometry cannot emit close_up or aerial. The two metadata-portrait clips use the actual autorotated 320 px frame height; other landscape frames use 180 px height.
- Pure SigLIP gate: 0/28 coverage because all median margins were below the provisional 0.08 threshold. Ungated SigLIP accuracy remains 0.536 and is reported only as diagnostic evidence.
- Geometry result: 15/28 coverage (0.536), 8/15 correct among covered clips (0.533 scored accuracy), and 8/28 correct end-to-end (0.286). Errors included crowd/environment wide shots promoted to medium, distant medium subjects promoted to close, and a close-up sign clip reduced to wide because a small background person controlled the heuristic.
- Fusion result: identical to geometry because SigLIP abstained everywhere. It therefore does not improve Shot Scale reliability and cannot justify filling the field.
- Material Role correction: the initial rule implementation used fixed role scores, which falsely implied calibrated confidence. A failing regression test now requires every role score to equal the weakest required input confidence times the documented rule factor; roles with missing confidence evidence are suppressed. Transition remains a candidate rule with factor 0.6 and never becomes an Editorial Role.
- Reliability boundary: Material Roles inherit errors and abstentions from people, scene, action, motion, objects, and Shot Scale. The 30-video labels can test rule consistency but do not establish independent role-model accuracy. `human_story` may be emitted as a candidate when detector evidence exists; environment, experience, detail, transition, and atmosphere should abstain when their required Scanner fields are unreliable.
- Decision: retain explainable fusion/role plumbing and raw method evidence, but mark Shot Scale geometry/fusion and all Material Roles as candidate or not reliable enough for V0.1 according to input coverage. Do not weaken the margin threshold merely to increase coverage on the same evaluation set.
- Next: build one cache-safe pipeline that shares decoded frames across CV, detector, SigLIP, fusion, and roles, while preserving per-stage failures.

## Experiment 09 — Cache-safe End-to-end Pipeline — 2026-08-28

- Method: run one immutable Scanner pipeline that decodes each clip once, shares representative frames across CV, SSDLite, SigLIP2, fusion, and Material Role rules, and writes per-frame evidence separately from the Scanner cards.
- Run contract: every run records a config hash, basic local environment, relative thumbnails, detector/SigLIP evidence, cache identity links, requested/actual device, and pinned model revisions. Existing run IDs are rejected; `--resume` accepts only an identical config hash. Run IDs cannot escape the configured run directory.
- Failure isolation: sampling failure retains a failed card without aborting the manifest; CV, detector, vision, and evidence-write failures are recorded by stage and preserve prior valid evidence as a partial card.
- Test evidence: five focused cache/pipeline tests passed, followed by the full 57-test suite in 5.14 seconds. Tests cover source/config/model cache invalidation, immutable/resumable runs, one-file decode failure isolation, shared-frame model/fusion flow, evidence output, and no-model CLI output.
- Real three-video smoke: `exp09-pipeline-e2e-3-v2` completed 3/3 cards with zero errors in 28.14 seconds on requested and actual MPS. Peak external RSS was 1,031,274,496 bytes. It wrote three evidence files and three cache-link files.
- Provenance: detector revision `SSDLite320_MobileNet_V3_Large_Weights.COCO_V1`; SigLIP revision `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`. Scanner results contain relative source paths and no Ground Truth payload.
- Remaining warning: the known Transformers 5.16 legacy BOS/EOS vocabulary warning still appears during local SigLIP model loading; inference succeeds and the warning remains documented rather than suppressed.
- Decision: retain the cache-safe pipeline and immutable run artifact layout. Do not rerun the already completed 30-video detector, CV, or SigLIP experiments merely to regenerate equivalent raw evidence.
- Next: implement null-aware field evaluation and evaluate only a small pipeline smoke before deciding whether a single canonical 30-video publish run is still needed.

## Experiment 10 — Null-aware Field Evaluation — 2026-08-28

- Method: compare only files present in both frozen Ground Truth and a Scanner run; exclude uncertain Ground Truth values, count Scanner null/abstained/unavailable values as unscored coverage, and count those abstentions as wrong in end-to-end accuracy.
- Metrics: binary precision/recall/F1/accuracy; count exact/within-one/MAE; single-label accuracy/Macro F1/confusion; multilabel Micro/Macro F1/Jaccard; ordered quality rank correlation and threshold confusion. No overall Scanner accuracy is produced.
- Reliability gate: decision-critical class support below five is `insufficient_coverage`; Macro F1 at least 0.80 without systematic failure may be `reliable`; incomplete coverage, a score of 0.65–0.79, or a documented systematic failure remains `candidate`; lower supported results are `not_reliable_for_v0_1`.
- Test evidence: nine focused evaluation tests passed; the final complete suite passed 64 tests in 4.77 seconds.
- Three-video result: `exp09-pipeline-e2e-3-v2/evaluation.json` evaluates 11 independent fields over three overlapping files. Every field is `insufficient_coverage`; `people_present` was 3/3 correct, people count exact accuracy was 2/3, and semantic/quality fields preserved their intended abstentions rather than fabricating predictions.
- Saved-evidence ablation: people-count `max`, `median`, and `high_confidence` each evaluated the same three overlapping files. Shot Scale SigLIP abstained on 3/3; geometry and fusion each emitted one of three. All method decisions remain `insufficient_coverage`.
- Corrected failure: the first ablation draft used all 28 known Ground Truth labels as the denominator even though only three evidence files existed. The evaluator now freezes the denominator to evidence/Ground Truth overlap, matching the main run evaluator.
- Decision: retain field-level evaluation, explicit coverage, end-to-end accuracy, and the restricted saved-evidence ablation methods. Do not use the three-video smoke to claim field reliability.
- Next: render a static validation report from the existing Scanner and evaluation artifacts without rerunning models.
