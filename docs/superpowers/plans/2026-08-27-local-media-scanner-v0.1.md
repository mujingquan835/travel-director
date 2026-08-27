# Travel Edit Engine V0.1 Local Media Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and evidence-test a local-first CLI that converts sparse frames from travel videos into auditable Scanner cards, then reports per-field accuracy and performance on a frozen 30-video set.

**Architecture:** FFprobe provides technical metadata; FFmpeg and OpenCV produce a bounded low-resolution probe stream and 3–5 representative frames. Traditional CV, a lightweight COCO detector, and SigLIP2 produce independent evidence which a conservative fusion layer turns into nullable Scanner fields and explainable Material Role candidates.

**Tech Stack:** Python 3.12 managed by uv, FFmpeg/ffprobe 8+, Pydantic 2, Typer, NumPy, Pillow, OpenCV headless, psutil, Jinja2, PyTorch/Torchvision, Hugging Face Transformers, pytest.

**Spec:** docs/superpowers/specs/2026-08-27-local-media-scanner-v0.1-design.md

## Global Constraints

- Treat /Users/meimaodawang/Desktop/万岁山素材/ as read-only input; never move, rename, overwrite, upload, or commit source videos.
- Scanner answers What is it; no Director, Editorial Role, timeline, music, SFX, Dreamina generation, export, GUI, Web App, or cloud service.
- Sequence Detection is not implemented in V0.1 and no sequence_candidate field is emitted.
- Use Python >=3.12,<3.13 inside local-media-scanner/.venv; do not install into system Python 3.14.
- Use at most 24 low-resolution probe frames and normally 3–5 representative frames per video.
- All uncertain semantic fields are nullable or marked candidate/abstained; never fill a Schema field merely for completeness.
- Raw Scanner output contains per-video confidence and field_status. Dataset-level reliability is produced only by Ground Truth evaluation.
- Keep model and frame caches below local-media-scanner/.cache/ and benchmark/runs/; exclude private thumbnails and caches from Git.
- MPS fallback to CPU must be explicit in result JSON and BENCHMARK.md.
- Apple Silicon VRAM is reported as not_applicable_shared_memory; unavailable GPU utilization is reported as unavailable.
- Update EXPERIMENTS.md after every experiment with method, parameters, timing, accuracy evidence, failures, retention decision, and next action.
- Create the project memory-retention folder only after all verification and final deliverables are complete.

## File Map

- local-media-scanner/pyproject.toml — package metadata, Python floor, dependency groups, CLI entry point.
- local-media-scanner/scanner/schema.py — versioned Pydantic input/output contracts.
- local-media-scanner/scanner/config.py — sampling, model, cache, and device configuration.
- local-media-scanner/scanner/metadata.py — discovery, ffprobe parsing, and manifest creation.
- local-media-scanner/scanner/sampling.py — probe decoding, motion/scene candidates, de-duplication, thumbnails.
- local-media-scanner/scanner/cv_metrics.py — blur, exposure, brightness, and motion measurements.
- local-media-scanner/scanner/selection.py — stratified test-set proposal and contact-sheet generation.
- local-media-scanner/scanner/detector.py — detector protocol and Torchvision SSDLite implementation.
- local-media-scanner/scanner/vision.py — SigLIP2 prompts, device selection, embeddings, and zero-shot scores.
- local-media-scanner/scanner/fusion.py — cross-frame aggregation and abstention.
- local-media-scanner/scanner/roles.py — explainable Material Role candidate rules.
- local-media-scanner/scanner/cache.py — cache keys and immutable run directories.
- local-media-scanner/scanner/pipeline.py — orchestration for one video and a manifest.
- local-media-scanner/scanner/telemetry.py — stage timing, CPU/RAM/MPS, and environment capture.
- local-media-scanner/scanner/evaluation.py — field metrics, coverage, confusion matrices, reliability decisions.
- local-media-scanner/scanner/report.py — static HTML report and benchmark summary rendering.
- local-media-scanner/scanner/cli.py — Typer commands only; no analysis algorithms.
- local-media-scanner/tests/ — synthetic and mocked tests; real videos remain external.
- local-media-scanner/benchmark/ — frozen manifest, annotation guide, Ground Truth, run metadata.

---

### Task 1: Bootstrap the package and freeze the Schema contract

**Files:**
- Create: local-media-scanner/pyproject.toml
- Create: local-media-scanner/.gitignore
- Create: local-media-scanner/README.md
- Create: local-media-scanner/EXPERIMENTS.md
- Create: local-media-scanner/BENCHMARK.md
- Create: local-media-scanner/scanner/__init__.py
- Create: local-media-scanner/scanner/config.py
- Create: local-media-scanner/scanner/schema.py
- Create: local-media-scanner/scanner/cli.py
- Create: local-media-scanner/tests/test_schema.py

**Interfaces:**
- Produces: SamplingConfig, ModelConfig, ScanConfig.
- Produces: SourceRecord, ManifestEntry, TestManifest, TechnicalMetadata, QualityMetrics, MotionMetrics, ContentAnalysis, FrameRecord, ConfidenceScore, RoleEvidence, ErrorRecord, TimingBreakdown, ScannerCard, ScannerResult.
- Produces CLI entry: scanner.cli:app.

- [ ] **Step 1: Write the failing Schema tests**

    import pytest
    from pydantic import ValidationError
    from scanner.schema import ScannerCard

    def minimal_card():
        return {
            "schema_version": "0.1.0",
            "file": "clip.MOV",
            "source": {"relative_path": "clip.MOV", "size_bytes": 10, "mtime_ns": 20},
            "analysis_status": "complete",
            "technical": {
                "duration": 1.0, "width": 1920, "height": 1080,
                "fps": 30.0, "orientation": "landscape", "codec": "hevc"
            },
            "quality": {"brightness_score": 0.5, "exposure_status": "normal"},
            "motion": {"motion_level": "low", "static_or_dynamic": "static"},
            "content": {"people_present": False, "people_type": [], "main_objects": []},
            "material_role_candidates": [],
            "material_role_evidence": {},
            "representative_frames": [],
            "confidence": {},
            "field_status": {},
            "timings_ms": {},
            "errors": []
        }

    def test_scanner_card_accepts_null_uncertain_fields():
        card = ScannerCard.model_validate(minimal_card())
        assert card.quality.blur_score is None
        assert card.content.scene_type is None
        assert card.shot_scale is None

    def test_scanner_card_rejects_editorial_role():
        payload = minimal_card()
        payload["editorial_role"] = "opening"
        with pytest.raises(ValidationError):
            ScannerCard.model_validate(payload)

- [ ] **Step 2: Run the test to verify it fails**

    cd local-media-scanner
    uv python install 3.12
    uv sync --extra dev
    uv run pytest tests/test_schema.py -v

Expected: FAIL because scanner.schema does not exist.

- [ ] **Step 3: Add package metadata and strict Pydantic models**

Use this project definition:

    [project]
    name = "travel-local-media-scanner"
    version = "0.1.0"
    requires-python = ">=3.12,<3.13"
    dependencies = [
      "jinja2>=3.1,<4",
      "numpy>=2.0,<3",
      "opencv-python-headless>=4.10,<5",
      "pillow>=11,<13",
      "psutil>=6,<8",
      "pydantic>=2.10,<3",
      "typer>=0.15,<1"
    ]

    [project.optional-dependencies]
    vision = [
      "safetensors>=0.5,<1",
      "torch>=2.7,<3",
      "torchvision>=0.22,<1",
      "transformers>=4.52,<6"
    ]
    dev = ["pytest>=8.3,<10", "pytest-cov>=6,<8"]

    [project.scripts]
    travel-scanner = "scanner.cli:app"

    [build-system]
    requires = ["hatchling>=1.27"]
    build-backend = "hatchling.build"

    [tool.hatch.build.targets.wheel]
    packages = ["scanner"]

All Pydantic models use ConfigDict(extra="forbid"). Enums match the design exactly. Optional semantic values default to None; list fields use default_factory.

- [ ] **Step 4: Add the version command and verify the package**

    import typer
    from scanner import __version__

    app = typer.Typer(no_args_is_help=True)

    @app.command()
    def version() -> None:
        typer.echo(__version__)

Run:

    uv run pytest tests/test_schema.py -v
    uv run travel-scanner version

Expected: tests PASS and output 0.1.0.

- [ ] **Step 5: Commit**

    git add local-media-scanner
    git commit -m "feat: bootstrap scanner schema and CLI"

### Task 2: Discover videos and extract trustworthy metadata

**Files:**
- Create: local-media-scanner/tests/conftest.py
- Create: local-media-scanner/tests/test_metadata.py
- Create: local-media-scanner/scanner/metadata.py
- Modify: local-media-scanner/scanner/cli.py
- Modify: local-media-scanner/EXPERIMENTS.md

**Interfaces:**
- Consumes: TechnicalMetadata, ManifestEntry, TestManifest.
- Produces: discover_videos(input_dir: Path) -> list[Path].
- Produces: probe_video(path: Path, ffprobe_bin: str = "ffprobe") -> TechnicalMetadata.
- Produces: build_manifest(input_dir: Path, paths: Sequence[Path]) -> TestManifest.

- [ ] **Step 1: Generate a test video and write failing metadata tests**

The session-scoped fixture runs:

    ffmpeg -v error -f lavfi -i color=c=blue:s=320x240:r=25 -t 1.2 -c:v libx264 -pix_fmt yuv420p fixture.mp4

Tests assert:

    def test_probe_video_reads_duration_dimensions_fps_and_orientation(sample_video):
        meta = probe_video(sample_video)
        assert meta.duration == pytest.approx(1.2, abs=0.08)
        assert (meta.width, meta.height) == (320, 240)
        assert meta.fps == pytest.approx(25.0, abs=0.01)
        assert meta.orientation == "landscape"

    def test_discovery_is_case_insensitive_and_sorted(tmp_path):
        # create b.MOV, a.mp4, ignored.txt
        assert [p.name for p in discover_videos(tmp_path)] == ["a.mp4", "b.MOV"]

- [ ] **Step 2: Verify the tests fail**

    uv run pytest tests/test_metadata.py -v

Expected: FAIL because probe_video and discover_videos are undefined.

- [ ] **Step 3: Implement ffprobe parsing without guessing**

Run ffprobe as a list argument, parse JSON, select the first video stream, parse rational frame rates with fractions.Fraction, and apply rotation metadata before orientation. Raise MetadataError with codes ffprobe_missing, ffprobe_failed, no_video_stream, or invalid_metadata.

    def probe_video(path: Path, ffprobe_bin: str = "ffprobe") -> TechnicalMetadata:
        command = [
            ffprobe_bin, "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "format=duration,size:stream=codec_name,width,height,avg_frame_rate:"
            "stream_tags=creation_time,rotate:stream_side_data=rotation",
            "-of", "json", str(path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise MetadataError("ffprobe_failed", completed.stderr.strip())
        return parse_ffprobe_payload(json.loads(completed.stdout))

- [ ] **Step 4: Add inspect CLI and test the real folder read-only**

    @app.command()
    def inspect(input: Path, output: Path | None = None) -> None:
        paths = discover_videos(input)
        manifest = build_manifest(input, paths)
        typer.echo(manifest.model_dump_json(indent=2))

Run:

    uv run pytest tests/test_metadata.py -v
    uv run travel-scanner inspect --input /Users/meimaodawang/Desktop/万岁山素材 > /tmp/travel-scanner-inspect.json

Expected: 272 video entries, no writes beneath the source folder. Record measured metadata time and any failures in EXPERIMENTS.md.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests local-media-scanner/EXPERIMENTS.md
    git commit -m "feat: add video discovery and metadata inspection"

### Task 3: Decode bounded probe frames and select sparse representatives

**Files:**
- Create: local-media-scanner/tests/test_sampling.py
- Create: local-media-scanner/scanner/sampling.py
- Modify: local-media-scanner/scanner/config.py
- Modify: local-media-scanner/scanner/schema.py
- Modify: local-media-scanner/scanner/cli.py
- Modify: local-media-scanner/EXPERIMENTS.md

**Interfaces:**
- Produces internal dataclass ProbeFrame(timestamp: float, image: np.ndarray, path: Path | None).
- Produces: target_probe_times(duration: float, config: SamplingConfig) -> list[float].
- Produces: decode_probe_frames(path: Path, metadata: TechnicalMetadata, output_dir: Path, config: SamplingConfig) -> list[ProbeFrame].
- Produces: select_representatives(frames: Sequence[ProbeFrame], duration: float, profile: Literal["temporal3","adaptive5"]) -> list[FrameCandidate].
- Produces: extract_representative_thumbnails(path: Path, candidates: Sequence[FrameCandidate], output_dir: Path, max_edge: int = 720) -> list[FrameRecord].

- [ ] **Step 1: Write failing selection tests**

    def test_probe_count_is_bounded():
        assert len(target_probe_times(0.5, SamplingConfig())) <= 2
        assert len(target_probe_times(10.0, SamplingConfig())) == 20
        assert len(target_probe_times(120.0, SamplingConfig())) == 24

    def test_temporal_baseline_returns_20_50_80_percent():
        frames = frames_at(np.linspace(0, 10, 21))
        selected = select_representatives(frames, 10.0, "temporal3")
        assert [item.timestamp for item in selected] == pytest.approx([2.0, 5.0, 8.0], abs=0.3)

    def test_adaptive_sampling_merges_reasons_and_deduplicates():
        frames = synthetic_scene_cut_and_motion_frames()
        selected = select_representatives(frames, 10.0, "adaptive5")
        assert 3 <= len(selected) <= 5
        assert any("motion" in item.reasons for item in selected)
        assert any("scene_change" in item.reasons for item in selected)
        assert len({perceptual_hash(item.image) for item in selected}) == len(selected)

- [ ] **Step 2: Verify the tests fail**

    uv run pytest tests/test_sampling.py -v

Expected: FAIL because scanner.sampling does not exist.

- [ ] **Step 3: Implement bounded FFmpeg decode and candidate scoring**

Use one FFmpeg process to create probe JPEGs at max edge 320. Infer the nominal timestamp from the requested uniform grid and never claim frame-accurate seeking. Candidate scores are:

    motion_score = median(flow_magnitude) / (image_diagonal * delta_seconds)
    scene_score = cv2.compareHist(prev_hsv_hist, curr_hsv_hist, cv2.HISTCMP_BHATTACHARYYA)

Start with temporal targets 0.2, 0.5, 0.8; add the highest non-duplicate motion and scene candidates. De-duplicate within max(0.25, duration * 0.08) seconds and by 64-bit dHash Hamming distance <= 5.

- [ ] **Step 4: Test real short and long clips**

Run unit tests, then use the shortest, median-length, and longest files from the metadata manifest:

    uv run pytest tests/test_sampling.py -v
    uv run travel-scanner sample --manifest benchmark/sampling-smoke.json --profile adaptive5 --output benchmark/runs/exp02-smoke

Expected: 1–2 frames for sub-second input, 3–5 for normal/long inputs, no more than 24 probe frames, and no source-folder writes. Record temporal3 versus adaptive5 frame counts and timings in EXPERIMENTS.md.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests local-media-scanner/EXPERIMENTS.md
    git commit -m "feat: add sparse representative frame sampling"

### Task 4: Measure blur, exposure, brightness, and motion

**Files:**
- Create: local-media-scanner/tests/test_cv_metrics.py
- Create: local-media-scanner/scanner/cv_metrics.py
- Modify: local-media-scanner/scanner/schema.py
- Modify: local-media-scanner/scanner/cli.py
- Modify: local-media-scanner/EXPERIMENTS.md

**Interfaces:**
- Consumes: ProbeFrame, QualityMetrics, MotionMetrics.
- Produces: frame_quality(image: np.ndarray) -> FrameQualityRaw.
- Produces: aggregate_quality(frames: Sequence[ProbeFrame]) -> QualityMetrics.
- Produces: measure_motion(frames: Sequence[ProbeFrame]) -> MotionMetrics.
- MotionMetrics also preserves directional_motion_ratio and luma_change_p90 as experimental transition evidence.
- Produces raw values; calibrated blur_score, motion_intensity, quality_score remain None until Task 13.

- [ ] **Step 1: Write failing monotonicity tests**

    def test_blur_reduces_laplacian_variance():
        sharp = checkerboard(320, 240)
        blurred = cv2.GaussianBlur(sharp, (21, 21), 0)
        assert frame_quality(sharp).laplacian_variance > frame_quality(blurred).laplacian_variance

    def test_brightness_and_clipping_direction():
        dark = np.full((120, 160, 3), 5, np.uint8)
        bright = np.full((120, 160, 3), 250, np.uint8)
        assert frame_quality(dark).brightness_score < frame_quality(bright).brightness_score
        assert frame_quality(dark).dark_pixel_ratio > 0.9
        assert frame_quality(bright).bright_pixel_ratio > 0.9

    def test_motion_is_higher_for_translated_pattern():
        static = probe_sequence([checkerboard(160, 120)] * 3)
        moving = translated_checkerboard_sequence()
        assert measure_motion(moving).motion_intensity_raw > measure_motion(static).motion_intensity_raw

    def test_consistent_pan_has_directional_motion_evidence():
        pan = horizontally_translated_checkerboard_sequence()
        assert measure_motion(pan).directional_motion_ratio > 0.7

- [ ] **Step 2: Verify the tests fail**

    uv run pytest tests/test_cv_metrics.py -v

Expected: FAIL because scanner.cv_metrics does not exist.

- [ ] **Step 3: Implement raw metrics and explicit unknown states**

Convert BGR to grayscale for Laplacian variance, use luminance/255 for brightness, and calculate clipping ratios at <=5 and >=250. Motion stores the circular concentration of optical-flow direction as directional_motion_ratio and the p90 absolute luminance change between adjacent frames as luma_change_p90. These are candidate transition signals, not transition labels. Exposure status uses transparent provisional rules:

    underexposed if brightness < 0.18 and dark_pixel_ratio > 0.35
    overexposed if brightness > 0.82 and bright_pixel_ratio > 0.20
    mixed if dark_pixel_ratio > 0.25 and bright_pixel_ratio > 0.15
    normal otherwise

Mark these thresholds provisional in the result evidence. Do not compute blur_score or quality_score yet.

- [ ] **Step 4: Run tests and record real distributions**

    uv run pytest tests/test_cv_metrics.py -v
    uv run travel-scanner cv-profile --manifest benchmark/sampling-smoke.json --output benchmark/runs/exp03-smoke

Expected: tests PASS; EXPERIMENTS.md contains raw min/median/p90 values and visually checked examples rather than an accuracy claim.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests local-media-scanner/EXPERIMENTS.md
    git commit -m "feat: add raw quality and motion metrics"

### Task 5: Select and freeze the 30-video test set before model inference

**Files:**
- Create: local-media-scanner/tests/test_selection.py
- Create: local-media-scanner/scanner/selection.py
- Create: local-media-scanner/benchmark/annotation_guide.md
- Create: local-media-scanner/benchmark/test_manifest.json
- Create: local-media-scanner/benchmark/ground_truth.json
- Create: local-media-scanner/ground_truth.json
- Modify: local-media-scanner/scanner/schema.py
- Modify: local-media-scanner/scanner/cli.py
- Modify: local-media-scanner/EXPERIMENTS.md

**Interfaces:**
- Consumes: TestManifest and optional raw CV profiles.
- Produces: propose_stratified_set(manifest: TestManifest, cv_rows: Sequence[dict], count: int, seed: int) -> TestManifest.
- Produces: render_contact_sheet(entries: Sequence[ManifestEntry], thumbnail_dir: Path, output: Path) -> Path.
- Ground Truth schema: file plus people_present, people_count_estimate, people_type, scene_type, shot_scale, motion_level, exposure_status, quality_label, main_objects, simple_action, material_role_candidates, annotation_confidence, notes.

- [ ] **Step 1: Write failing deterministic-selection tests**

    def test_selection_is_deterministic_and_preserves_rare_strata():
        manifest = synthetic_manifest_with_orientation_duration_and_time_strata()
        first = propose_stratified_set(manifest, [], count=6, seed=20260827)
        second = propose_stratified_set(manifest, [], count=6, seed=20260827)
        assert first.model_dump() == second.model_dump()
        assert {row.technical.orientation for row in first.entries} == {"landscape", "portrait"}
        assert any(row.technical.duration < 3 for row in first.entries)
        assert any(row.technical.duration > 30 for row in first.entries)

- [ ] **Step 2: Verify the test fails**

    uv run pytest tests/test_selection.py -v

Expected: FAIL because scanner.selection does not exist.

- [ ] **Step 3: Implement metadata/CV stratification and contact sheet**

Bin by shooting day/time, portrait/landscape, resolution, duration (<3, 3–10, 10–30, >30), brightness quartile, blur raw quartile, and motion raw quartile. Use deterministic round-robin coverage before filling remaining slots by seed. The HTML contact sheet shows filename, midpoint thumbnail, duration, strata, and no model prediction.

- [ ] **Step 4: Generate, manually inspect, and freeze Ground Truth**

    uv run travel-scanner select-testset --input /Users/meimaodawang/Desktop/万岁山素材 --count 30 --seed 20260827 --manifest benchmark/test_manifest.json --contact-sheet benchmark/test_selection.html

Watch each selected video before any detector/SigLIP real run. Apply annotation_guide.md definitions. Use uncertain only for genuinely ambiguous labels; never copy model output. Verify:

    uv run travel-scanner validate-ground-truth --manifest benchmark/test_manifest.json --ground-truth benchmark/ground_truth.json

Expected: exactly 30 unique files; every required Ground Truth key has a value or explicit uncertain; root ground_truth.json is byte-identical to benchmark/ground_truth.json. Commit filenames and labels, but not contact-sheet thumbnails.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests local-media-scanner/benchmark/annotation_guide.md local-media-scanner/benchmark/test_manifest.json local-media-scanner/benchmark/ground_truth.json local-media-scanner/ground_truth.json local-media-scanner/EXPERIMENTS.md
    git commit -m "test: freeze 30-video scanner ground truth"

### Task 6: Add the lightweight COCO detector

**Files:**
- Create: local-media-scanner/tests/test_detector.py
- Create: local-media-scanner/scanner/detector.py
- Modify: local-media-scanner/scanner/config.py
- Modify: local-media-scanner/scanner/cli.py
- Modify: local-media-scanner/EXPERIMENTS.md

**Interfaces:**
- Produces Detection(label: str, score: float, box_xyxy: tuple[float,float,float,float]).
- Produces Detector protocol with detect(images: Sequence[PIL.Image.Image]) -> list[list[Detection]].
- Produces TorchvisionSSDLiteDetector.load(cache_dir: Path, score_threshold: float, device: str = "cpu").
- Produces summarize_detections(per_frame: Sequence[Sequence[Detection]]) -> DetectionSummary.

- [ ] **Step 1: Write failing adapter and aggregation tests**

    def test_people_summary_keeps_per_frame_counts():
        rows = [
            [Detection("person", 0.9, (0, 0, 20, 80))],
            [Detection("person", 0.8, (0, 0, 20, 80)),
             Detection("person", 0.7, (30, 0, 50, 80))],
        ]
        summary = summarize_detections(rows)
        assert summary.people_present is True
        assert summary.people_counts == [1, 2]
        assert summary.people_count_max == 2
        assert summary.main_objects == ["person"]

    def test_low_score_detections_are_excluded():
        assert filter_detections([Detection("person", 0.2, (0, 0, 1, 1))], 0.5) == []

- [ ] **Step 2: Verify tests fail, then install the vision dependency group**

    uv run pytest tests/test_detector.py -v
    uv sync --extra dev --extra vision

Expected before implementation: FAIL because scanner.detector does not exist. Report the large download/cache status to the user before uv sync and record exact installed versions.

- [ ] **Step 3: Implement the protocol and SSDLite adapter**

Load torchvision.models.detection.ssdlite320_mobilenet_v3_large with DEFAULT weights. Map category IDs from weights.meta["categories"]. Run inference_mode, always start on CPU, and convert boxes to original image coordinates. Batch only if measured memory remains below the 16 GB device limit; initial batch size is 1.

- [ ] **Step 4: Run mocked tests and a five-video detector smoke test**

    uv run pytest tests/test_detector.py -v
    uv run travel-scanner detector-smoke --manifest benchmark/test_manifest.json --limit 5 --output benchmark/runs/exp04-detector

Expected: no full-video upload, per-frame detection JSON, people counts, model ID/revision, load time, inference time, and peak RSS. Compare detections visually to the already frozen Ground Truth and record failures without changing labels.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests local-media-scanner/pyproject.toml local-media-scanner/uv.lock local-media-scanner/EXPERIMENTS.md
    git commit -m "feat: add lightweight local object detection"

### Task 7: Add SigLIP2 zero-shot evidence on CPU and MPS

**Files:**
- Create: local-media-scanner/tests/test_vision.py
- Create: local-media-scanner/scanner/vision.py
- Modify: local-media-scanner/scanner/config.py
- Modify: local-media-scanner/scanner/cli.py
- Modify: local-media-scanner/EXPERIMENTS.md

**Interfaces:**
- Produces LabelScore(label: str, score: float).
- Produces FramePrediction(field: str, scores: list[LabelScore], top_margin: float, source: str).
- Produces resolve_device(requested: str) -> DeviceResolution(requested, actual, fallback_reason).
- Produces SiglipEvidenceEncoder.load(model_id: str, cache_dir: Path, requested_device: str).
- Produces classify(images: Sequence[PIL.Image.Image], prompt_groups: Mapping[str, Sequence[str]]) -> list[FramePrediction].

- [ ] **Step 1: Write failing prompt, score, and device tests**

    def test_prompt_groups_cover_fixed_taxonomies():
        assert set(SCENE_PROMPTS) == {
            "nature", "city", "building", "indoor", "theme_park",
            "food_dining", "transportation", "night_scene", "other"
        }
        assert set(SHOT_SCALE_PROMPTS) == {"wide", "medium", "close", "close_up", "aerial"}
        assert set(PEOPLE_TYPE_PROMPTS) == {"child", "adult"}
        assert set(ACTION_PROMPTS) == {
            "walking", "running", "eating", "riding", "entering",
            "watching", "interacting", "other"
        }
        assert "building" in OBJECT_PROMPTS
        assert "food" in OBJECT_PROMPTS

    def test_margin_uses_top_two_scores():
        scores = [LabelScore("wide", 0.8), LabelScore("medium", 0.6)]
        assert top_margin(scores) == pytest.approx(0.2)

    def test_unavailable_mps_returns_explicit_cpu_fallback(monkeypatch):
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
        resolved = resolve_device("auto")
        assert resolved.actual == "cpu"
        assert resolved.fallback_reason == "mps_unavailable"

- [ ] **Step 2: Verify tests fail**

    uv run pytest tests/test_vision.py -v

Expected: FAIL because scanner.vision does not exist.

- [ ] **Step 3: Implement prompt ensembles and SigLIP2 inference**

Use model ID google/siglip2-base-patch16-224. Processor inputs use the model defaults and max_length 64. Normalize image/text embeddings for similarity; preserve raw SigLIP logits/scores, top-k, and top margin. Do not label the score as probability. Scene, Shot Scale, people type, simple action, and compact main-object prompt groups include at least three phrasings per class and are versioned with PROMPT_SET_VERSION = "0.1.0". The resolved Hugging Face commit hash is stored beside each run.

- [ ] **Step 4: Run tests and CPU/MPS smoke comparison**

    uv run pytest tests/test_vision.py -v
    uv run travel-scanner vision-smoke --manifest benchmark/test_manifest.json --limit 5 --device cpu --output benchmark/runs/exp04-siglip-cpu
    uv run travel-scanner vision-smoke --manifest benchmark/test_manifest.json --limit 5 --device mps --output benchmark/runs/exp04-siglip-mps

Expected: identical label taxonomy, close numerical ordering within documented tolerance, explicit actual_device, model load/inference time, and no silent fallback. Record download size, cache path, peak RSS/MPS allocated memory, and mismatches against frozen Ground Truth.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests local-media-scanner/EXPERIMENTS.md
    git commit -m "feat: add local SigLIP2 evidence encoder"

### Task 8: Fuse video evidence and derive explainable Material Roles

**Files:**
- Create: local-media-scanner/tests/test_fusion.py
- Create: local-media-scanner/tests/test_roles.py
- Create: local-media-scanner/scanner/fusion.py
- Create: local-media-scanner/scanner/roles.py
- Modify: local-media-scanner/scanner/schema.py
- Modify: local-media-scanner/scanner/cli.py
- Modify: local-media-scanner/EXPERIMENTS.md

**Interfaces:**
- Consumes: DetectionSummary and per-frame FramePrediction.
- Produces: fuse_people(summary: DetectionSummary) -> FusedField[bool|int].
- Produces: fuse_single_label(predictions: Sequence[FramePrediction], min_margin: float, min_agreement: float) -> FusedField[str].
- Produces: fuse_shot_scale(predictions, detections, image_sizes) -> FusedField[str].
- Produces: compare_shot_scale_methods(predictions, detections, image_sizes) -> dict[str, FusedField[str]] with siglip, geometry, and fusion keys.
- Produces: infer_material_roles(card: ScannerCard) -> tuple[list[str], dict[str, RoleEvidence]].

- [ ] **Step 1: Write failing abstention and evidence tests**

    def test_conflicting_scene_frames_abstain():
        predictions = frame_predictions(["nature", "city", "building"], margins=[0.03, 0.02, 0.01])
        fused = fuse_single_label(predictions, min_margin=0.08, min_agreement=0.6)
        assert fused.value is None
        assert fused.status == "abstained"

    def test_people_geometry_can_support_medium_but_not_aerial():
        fused = fuse_shot_scale(
            predictions=low_margin_scale_predictions("wide"),
            detections=person_boxes(height_ratios=[0.55, 0.50, 0.58]),
            image_sizes=[(720, 1280)] * 3,
        )
        assert fused.value == "medium"
        assert fused.evidence_source == "geometry_fusion"

    def test_role_candidate_has_rules_and_inputs():
        card = people_medium_card()
        roles, evidence = infer_material_roles(card)
        assert "human_story" in roles
        assert evidence["human_story"].rules
        assert "content.people_present" in evidence["human_story"].inputs
        assert not {"opening", "climax", "ending"} & set(roles)

- [ ] **Step 2: Verify tests fail**

    uv run pytest tests/test_fusion.py tests/test_roles.py -v

Expected: FAIL because fusion and roles modules do not exist.

- [ ] **Step 3: Implement conservative aggregation**

Use median score per label, frame agreement, and median top margin. Initial abstention requires agreement <0.6 or margin <0.08. For person-led shot scale, use person height ratio bands <=0.35 wide, 0.35–0.70 medium, >0.70 close; close_up still requires SigLIP support and is never inferred from height alone. Aerial requires direct SigLIP aerial evidence with margin >=0.12.

Material Role scores are the minimum of required input confidences multiplied by a rule-specific factor; transition uses factor 0.6 and always returns field_status candidate in V0.1.

- [ ] **Step 4: Run tests and inspect five frozen videos**

    uv run pytest tests/test_fusion.py tests/test_roles.py -v
    uv run travel-scanner fuse-smoke --detector-run benchmark/runs/exp04-detector --vision-run benchmark/runs/exp04-siglip-mps --output benchmark/runs/exp05-fusion

Expected: every Material Role has rules/inputs; low-agreement fields abstain; no Editorial Role key. Record Shot Scale pure-SigLIP, geometry, and fusion predictions separately in EXPERIMENTS.md.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests local-media-scanner/EXPERIMENTS.md
    git commit -m "feat: fuse local evidence into scanner candidates"

### Task 9: Build cache-safe end-to-end scanning

**Files:**
- Create: local-media-scanner/tests/test_cache.py
- Create: local-media-scanner/tests/test_pipeline.py
- Create: local-media-scanner/scanner/cache.py
- Create: local-media-scanner/scanner/pipeline.py
- Modify: local-media-scanner/scanner/cli.py
- Modify: local-media-scanner/EXPERIMENTS.md

**Interfaces:**
- Produces: cache_key(entry: ManifestEntry, config: ScanConfig, model_revisions: Mapping[str,str]) -> str.
- Produces: create_run_dir(base: Path, run_id: str, config: ScanConfig) -> RunPaths.
- Produces: scan_one(entry: ManifestEntry, context: ScanContext) -> ScannerCard.
- Produces: scan_manifest(manifest: TestManifest, context: ScanContext) -> ScannerResult.

- [ ] **Step 1: Write failing cache and partial-failure tests**

    def test_cache_key_changes_with_mtime_config_and_model_revision():
        base = manifest_entry(mtime_ns=1)
        first = cache_key(base, scan_config("adaptive5"), {"siglip": "a"})
        changed_source = base.source.model_copy(update={"mtime_ns": 2})
        changed = base.model_copy(update={"source": changed_source})
        assert first != cache_key(changed, scan_config("adaptive5"), {"siglip": "a"})
        assert first != cache_key(base, scan_config("temporal3"), {"siglip": "a"})
        assert first != cache_key(base, scan_config("adaptive5"), {"siglip": "b"})

    def test_one_decode_failure_does_not_abort_manifest(fake_context):
        result = scan_manifest(two_entry_manifest(second_is_corrupt=True), fake_context)
        assert len(result.items) == 2
        assert result.items[0].analysis_status == "complete"
        assert result.items[1].analysis_status == "failed"
        assert result.items[1].errors[0].stage == "sampling"

- [ ] **Step 2: Verify tests fail**

    uv run pytest tests/test_cache.py tests/test_pipeline.py -v

Expected: FAIL because cache and pipeline modules do not exist.

- [ ] **Step 3: Implement immutable runs and stage isolation**

Create benchmark/runs/<run-id>/run_config.json, environment.json, scanner_result.json, evidence/, frames/, cache-links/, and logs/. Refuse an existing run ID unless --resume is passed with an identical config hash. scan_one wraps each stage independently and uses partial when prior valid evidence remains. evidence/ stores per-frame detector and SigLIP scores needed for ablation without rerunning models; it never contains full video.

- [ ] **Step 4: Add scan CLI and execute a three-video end-to-end smoke**

    uv run pytest tests/test_cache.py tests/test_pipeline.py -v
    uv run travel-scanner scan --manifest benchmark/test_manifest.json --limit 3 --sampling-profile adaptive5 --device mps --run-id exp06-e2e-smoke

Expected: three Scanner cards, relative source paths, representative thumbnails, stage timings, actual device, model revisions, and no Ground Truth values copied into raw results.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests local-media-scanner/EXPERIMENTS.md
    git commit -m "feat: add cache-safe local scanning pipeline"

### Task 10: Evaluate every field against frozen Ground Truth

**Files:**
- Create: local-media-scanner/tests/test_evaluation.py
- Create: local-media-scanner/scanner/evaluation.py
- Modify: local-media-scanner/scanner/schema.py
- Modify: local-media-scanner/scanner/cli.py

**Interfaces:**
- Produces: evaluate_binary, evaluate_count, evaluate_single_label, evaluate_multilabel.
- Produces: evaluate_ordered_quality for rank agreement and threshold confusion without adding SciPy.
- Produces: evaluate_run(ground_truth: GroundTruthSet, result: ScannerResult) -> EvaluationSummary.
- Produces: evaluate_ablation(ground_truth: GroundTruthSet, evidence_dir: Path, fields: Sequence[str]) -> AblationSummary.
- Produces: decide_reliability(metrics: FieldMetrics, min_class_support: int = 5, systematic_failure: bool = False) -> ReliabilityDecision.

- [ ] **Step 1: Write failing metric tests with hand-calculated values**

    def test_binary_metrics_match_hand_calculation():
        metrics = evaluate_binary([True, True, False, False], [True, False, True, False])
        assert metrics.precision == pytest.approx(0.5)
        assert metrics.recall == pytest.approx(0.5)
        assert metrics.f1 == pytest.approx(0.5)
        assert metrics.accuracy == pytest.approx(0.5)

    def test_count_metrics_include_exact_plus_minus_one_and_mae():
        metrics = evaluate_count([1, 2, 4], [1, 3, 2])
        assert metrics.exact_accuracy == pytest.approx(1 / 3)
        assert metrics.within_one_accuracy == pytest.approx(2 / 3)
        assert metrics.mae == pytest.approx(1.0)

    def test_insufficient_support_blocks_reliable_decision():
        decision = decide_reliability(field_metrics(macro_f1=0.95, min_class_support=2))
        assert decision.status == "insufficient_coverage"

    def test_systematic_failure_blocks_reliable_decision():
        decision = decide_reliability(
            field_metrics(macro_f1=0.90, min_class_support=8),
            systematic_failure=True,
        )
        assert decision.status == "candidate"

- [ ] **Step 2: Verify tests fail**

    uv run pytest tests/test_evaluation.py -v

Expected: FAIL because scanner.evaluation does not exist.

- [ ] **Step 3: Implement null-aware metrics and explicit coverage**

Exclude only Ground Truth uncertain values from denominators. Count Scanner null as abstention and report both scored coverage and end-to-end accuracy with abstentions counted wrong. evaluate_ordered_quality converts manual bad/usable/good labels to ranks, computes Pearson correlation on average ranks with NumPy, and also reports the calibrated threshold confusion matrix. Reliability rules:

    insufficient_coverage when any decision-critical class support < 5
    reliable when macro_f1 >= 0.80 and no documented systematic failure
    candidate when macro_f1 >= 0.65 or coverage is incomplete
    not_reliable_for_v0_1 otherwise

evaluate_ablation supports only people_count_estimate methods max, median, high_confidence and shot_scale methods siglip, geometry, fusion. Do not calculate an overall Scanner accuracy.

- [ ] **Step 4: Run tests and evaluate the three-video smoke without claiming reliability**

    uv run pytest tests/test_evaluation.py -v
    uv run travel-scanner evaluate --ground-truth benchmark/ground_truth.json --result benchmark/runs/exp06-e2e-smoke/scanner_result.json --output benchmark/runs/exp06-e2e-smoke/evaluation.json

Expected: metrics only for overlapping three files and reliability statuses insufficient_coverage.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests
    git commit -m "feat: add field-level scanner evaluation"

### Task 11: Render the local HTML validation report

**Files:**
- Create: local-media-scanner/tests/test_report.py
- Create: local-media-scanner/scanner/report.py
- Create: local-media-scanner/scanner/templates/validation_report.html.j2
- Modify: local-media-scanner/scanner/cli.py

**Interfaces:**
- Produces: render_validation_report(result: ScannerResult, evaluation: EvaluationSummary, environment: EnvironmentSnapshot, output: Path) -> Path.
- Produces: publish_run(run_dir: Path, ground_truth: Path, output_dir: Path) -> tuple[Path, Path], rewriting thumbnail paths relative to output_dir.
- All thumbnail URLs are relative to output.parent and HTML-escaped.

- [ ] **Step 1: Write failing HTML tests**

    def test_report_contains_cards_metrics_and_mismatch_state(tmp_path):
        output = render_validation_report(
            result=two_card_result(filename="<clip>.MOV"),
            evaluation=sample_evaluation_with_mismatch(),
            environment=sample_environment(),
            output=tmp_path / "validation_report.html",
        )
        html = output.read_text()
        assert "&lt;clip&gt;.MOV" in html
        assert "field-mismatch" in html
        assert "people_present" in html
        assert "not_reliable_for_v0_1" in html
        assert "data:image" not in html

- [ ] **Step 2: Verify the test fails**

    uv run pytest tests/test_report.py -v

Expected: FAIL because scanner.report does not exist.

- [ ] **Step 3: Implement a static, dependency-light report**

Use Jinja autoescape. Top summary shows environment, stage timings, failure count, per-field metrics, coverage, and reliability. Cards show all representative thumbnails, timestamps/reasons, prediction, Ground Truth, confidence source, field_status, errors, and match state. Use embedded CSS only; no JavaScript framework or server. The publish command calls publish_run and rewrites every thumbnail_relpath with os.path.relpath from output_dir before serializing the root Scanner result.

- [ ] **Step 4: Run tests and render the smoke report**

    uv run pytest tests/test_report.py -v
    uv run travel-scanner report --ground-truth benchmark/ground_truth.json --run benchmark/runs/exp06-e2e-smoke --output benchmark/runs/exp06-e2e-smoke/validation_report.html

Expected: opens locally, displays three cards without missing thumbnails, and visually distinguishes mismatch, abstention, and not evaluated.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests
    git commit -m "feat: add static scanner validation report"

### Task 12: Capture environment, timing, CPU, RAM, and MPS evidence

**Files:**
- Create: local-media-scanner/tests/test_telemetry.py
- Create: local-media-scanner/scanner/telemetry.py
- Modify: local-media-scanner/scanner/pipeline.py
- Modify: local-media-scanner/scanner/schema.py
- Modify: local-media-scanner/scanner/cli.py

**Interfaces:**
- Produces StageTimer context manager writing milliseconds to TimingBreakdown.
- Produces ResourceSampler(interval_seconds: float = 0.2) with start(), stop(), summary().
- Produces capture_environment() -> EnvironmentSnapshot.
- Produces benchmark_manifest(manifest, config, repeats: int = 1) -> BenchmarkRun.

- [ ] **Step 1: Write failing telemetry tests**

    def test_stage_timer_records_positive_milliseconds():
        timings = {}
        with StageTimer(timings, "metadata"):
            time.sleep(0.01)
        assert timings["metadata"] >= 8

    def test_apple_unified_memory_never_reports_fake_vram(monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        snapshot = capture_environment()
        assert snapshot.vram == "not_applicable_shared_memory"

    def test_unavailable_gpu_utilization_is_explicit():
        summary = ResourceSummary(gpu_utilization=None)
        assert summary.model_dump()["gpu_utilization"] == "unavailable"

- [ ] **Step 2: Verify tests fail**

    uv run pytest tests/test_telemetry.py -v

Expected: FAIL because scanner.telemetry does not exist.

- [ ] **Step 3: Implement low-overhead sampling and environment capture**

Use time.perf_counter_ns for stages, psutil.Process for CPU time/RSS, psutil.virtual_memory for RAM, system_profiler SPHardwareDataType for Mac model/chip, torch.backends.mps for availability, and torch.mps.current_allocated_memory when supported. Any unavailable metric stores a string state, not zero.

- [ ] **Step 4: Run tests and repeat a warm three-video benchmark**

    uv run pytest tests/test_telemetry.py -v
    uv run travel-scanner benchmark --manifest benchmark/test_manifest.json --limit 3 --sampling-profile adaptive5 --device mps --repeats 2 --run-id exp07-telemetry-smoke

Expected: separate first model load, first scan, warm repeat, per-stage time, average per video, average per source minute, peak RSS, MPS allocation, and explicit unavailable metrics.

- [ ] **Step 5: Commit**

    git add local-media-scanner/scanner local-media-scanner/tests
    git commit -m "feat: add scanner performance telemetry"

### Task 13: Run the 30-video experiment matrix and publish local artifacts

**Files:**
- Modify: local-media-scanner/EXPERIMENTS.md
- Create: local-media-scanner/benchmark/runs/exp08-temporal3/scanner_result.json
- Create: local-media-scanner/benchmark/runs/exp08-adaptive5/scanner_result.json
- Create: local-media-scanner/benchmark/runs/exp08-adaptive5/evaluation.json
- Create: local-media-scanner/benchmark/runs/exp08-adaptive5/validation_report.html
- Create: local-media-scanner/scanner_result.json
- Create: local-media-scanner/validation_report.html

**Interfaces:**
- Consumes the frozen 30-video manifest and Ground Truth.
- Produces comparable temporal3 and adaptive5 runs under the same model revisions and device.

- [ ] **Step 1: Run the complete automated test suite before paid/network-free analysis**

    uv run pytest -v

Expected: all unit/integration tests PASS. Dreamina remains logged out and unused; the only model calls are local cached Torchvision/SigLIP2 inference.

- [ ] **Step 2: Run temporal3 and adaptive5 on the same 30 files**

    uv run travel-scanner benchmark --manifest benchmark/test_manifest.json --sampling-profile temporal3 --device mps --repeats 2 --run-id exp08-temporal3

    uv run travel-scanner benchmark --manifest benchmark/test_manifest.json --sampling-profile adaptive5 --device mps --repeats 2 --run-id exp08-adaptive5

    uv run travel-scanner benchmark --manifest benchmark/test_manifest.json --limit 10 --sampling-profile adaptive5 --device cpu --repeats 1 --run-id exp08-cpu10

Expected: 30 cards in both MPS sampling runs and 10 matching cards in the CPU run; zero omitted files; failed/partial files retained; model revisions identical; cold/warm timings separated. Compare the same first 10 files from exp08-adaptive5 with exp08-cpu10 to answer whether CPU-only operation is acceptable.

- [ ] **Step 3: Evaluate all fields and compare sampling strategies**

    uv run travel-scanner evaluate --ground-truth benchmark/ground_truth.json --result benchmark/runs/exp08-temporal3/scanner_result.json --output benchmark/runs/exp08-temporal3/evaluation.json

    uv run travel-scanner evaluate --ground-truth benchmark/ground_truth.json --result benchmark/runs/exp08-adaptive5/scanner_result.json --output benchmark/runs/exp08-adaptive5/evaluation.json

    uv run travel-scanner ablate --ground-truth benchmark/ground_truth.json --run benchmark/runs/exp08-adaptive5 --fields people_count_estimate,shot_scale --output benchmark/runs/exp08-adaptive5/ablation.json

For each field, record temporal3 metric, adaptive5 metric, delta, coverage, failure examples, and whether the extra 1–2 frames are retained. The ablation compares people-count max/median/high-confidence strategies and Shot Scale siglip/geometry/fusion strategies from saved raw evidence. Calibrate blur/motion thresholds only on the frozen set and label them pilot thresholds.

- [ ] **Step 4: Render and manually inspect all 30 cards**

    uv run travel-scanner report --ground-truth benchmark/ground_truth.json --run benchmark/runs/exp08-adaptive5 --output benchmark/runs/exp08-adaptive5/validation_report.html

Publish the selected canonical run with path rewriting:

    uv run travel-scanner publish --ground-truth benchmark/ground_truth.json --run benchmark/runs/exp08-adaptive5 --output-dir .

This writes scanner_result.json with thumbnail paths relative to the project root and renders validation_report.html against those paths. Inspect all mismatch cards and record at least one concrete failure example for every field marked candidate or not_reliable_for_v0_1.

- [ ] **Step 5: Commit reproducible small artifacts, excluding private frames**

    git add local-media-scanner/EXPERIMENTS.md local-media-scanner/ground_truth.json local-media-scanner/scanner_result.json local-media-scanner/validation_report.html
    git commit -m "test: record 30-video scanner benchmark"

Before committing, confirm generated JSON/HTML contain relative paths only and no embedded source videos or base64 thumbnails.

### Task 14: Estimate 100-video performance, answer Q1–Q6, and close the project

**Files:**
- Create: local-media-scanner/benchmark/performance_manifest_100.json
- Modify: local-media-scanner/BENCHMARK.md
- Modify: local-media-scanner/README.md
- Modify: local-media-scanner/EXPERIMENTS.md
- Create only after all gates pass: local-media-scanner/memory_retention/2026-08-27-local-media-scanner-v0.1/summary.md

**Interfaces:**
- Produces the final feasibility recommendation and reproducible install/run instructions.
- Does not add new Scanner fields or downstream product features.

- [ ] **Step 1: Build a deterministic 100-video performance manifest**

Use seed 20260827 and preserve duration/resolution/time-of-day strata without consulting Ground Truth accuracy. Validate:

    uv run travel-scanner select-testset --input /Users/meimaodawang/Desktop/万岁山素材 --count 100 --seed 20260827 --manifest benchmark/performance_manifest_100.json --performance-only

Expected: exactly 100 unique external relative paths and measured total duration/bytes.

- [ ] **Step 2: Choose actual full-pipeline run versus evidence-marked extrapolation**

Always run metadata plus CV on 100 files. Run the full detector/SigLIP pipeline on 100 only when the 30-video warm run has no process crash, peak RSS <=13 GB, and total scan time <=4 times source duration. Otherwise stop after metadata/CV and extrapolate model time from the 30-video run using both per-file and per-source-minute rates.

    uv run travel-scanner benchmark --manifest benchmark/performance_manifest_100.json --stages metadata,sampling,cv --device mps --run-id exp09-performance-100-cv

If the gate passes:

    uv run travel-scanner benchmark --manifest benchmark/performance_manifest_100.json --sampling-profile adaptive5 --device mps --repeats 1 --run-id exp09-performance-100-full

BENCHMARK.md must say actual or extrapolated and identify the formula and source run.

- [ ] **Step 3: Write README and BENCHMARK with exact evidence**

README includes uv installation, FFmpeg prerequisite, model download/cache behavior, CPU/MPS/CUDA selection, every CLI command, privacy boundary, output paths, cache cleanup by explicit path, and known unreliable fields.

BENCHMARK answers:

    Q1 100-video time range and basis
    Q2 CPU/MPS acceptability and independent-GPU requirement
    Q3 temporal3 versus adaptive5
    Q4 per-field metrics, support, coverage, reliability, failures
    Q5 CV versus detector versus SigLIP2 versus rules
    Q6 not-reliable fields and reasons

End with Continue, Continue with constraints, or Stop, supported by measured evidence.

- [ ] **Step 4: Run final verification and create memory retention only now**

    uv run pytest -v
    uv run travel-scanner validate-ground-truth --manifest benchmark/test_manifest.json --ground-truth ground_truth.json
    uv run travel-scanner evaluate --ground-truth ground_truth.json --result scanner_result.json --output /tmp/final-evaluation.json
    git diff --check
    git status --short

After these gates pass, create memory_retention/2026-08-27-local-media-scanner-v0.1/summary.md containing: scope, Git commits, environment, commands, dataset facts, experiment results, field reliability table, performance conclusion, known failures, Dreamina future constraint, and exact next step. Do not create this folder earlier.

- [ ] **Step 5: Commit final documentation and inspect the finished tree**

    git add local-media-scanner/README.md local-media-scanner/BENCHMARK.md local-media-scanner/EXPERIMENTS.md local-media-scanner/benchmark/performance_manifest_100.json local-media-scanner/memory_retention
    git commit -m "docs: conclude local media scanner v0.1 feasibility"
    git status --short --branch
    git log --oneline --decorate -15

Expected: clean worktree, all requested deliverables present, no private video committed, and no completion claim beyond the evidence in BENCHMARK.md.
