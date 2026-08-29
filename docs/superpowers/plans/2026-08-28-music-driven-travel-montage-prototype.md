# Music-Driven Travel Montage Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an auditable prototype that turns a local Scanner result plus a user brief into three music directions, an original-music blueprint, an analyzed music structure, a music-driven clip timeline, an SFX/on-location-sound plan, and one bounded playable montage.

**Architecture:** Keep the completed `scanner` package intact and add a sibling `director` package whose versioned Pydantic contracts form the boundary between local analysis, catalog providers, music generation providers, audio analysis, timeline planning, and rendering. Every external provider is behind a protocol and an explicit authorization gate; local fixtures and deterministic planners make all contract and orchestration tests run without a browser, login, paid call, or network.

**Tech Stack:** Python 3.12 with uv, Pydantic 2, Typer, NumPy, librosa/soundfile for local audio analysis, FFmpeg/ffprobe 8+, existing Scanner V0.1, pytest; browser-assisted catalog inspection and Dreamina CLI are separately authorized prototype adapters rather than test dependencies.

**Spec:** `docs/superpowers/specs/2026-08-28-music-driven-travel-montage-prototype-design.md`

## Global Constraints

- Work only in `/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1` on `feature/local-media-scanner-v0.1`; do not implement against `main`, which does not contain Scanner source.
- Treat `/Users/meimaodawang/Desktop/万岁山素材` as read-only; never move, rename, overwrite, upload, or commit source video/audio.
- Preserve Scanner V0.1 and its current 72-test baseline. Add adapters; do not widen `ScannerCard` into a Director object.
- Treat Scanner technical metadata, sparse frames, raw CV evidence, cache/error structure as usable. Treat `people_count_estimate`, `scene_type`, `shot_scale`, `simple_action`, and `main_objects` according to `field_status` and `BENCHMARK.md`; never convert candidate or unreliable semantics into facts.
- Target duration is 30–180 seconds. Original import volume does not determine final clip count.
- Full-library scanning remains sparse, local, cached, resumable, and free of per-frame heavyweight description.
- Music lookup returns three user-facing directions from at most five internally retained candidates. It reads only the current visible page and never crawls, bypasses login/CAPTCHA/WAF, downloads protected previews, or caches protected audio.
- `MusicCatalogProvider` and `MusicGenerationProvider` are replaceable protocols. Director code must not depend on Quduoduo DOM selectors or Dreamina command syntax.
- Generated-music prompts may carry BPM, meter, genre, instruments, emotion, energy curve, duration, and ending behavior; they must exclude reference title, artist, lyrics, melody, and arrangement-copy instructions.
- Dreamina capability inspection is read-only. Any login, generation, credit use, Quduoduo interaction, or other paid/external side effect requires a new explicit user authorization at that stage.
- Analyze the actual generated audio; never treat blueprint section times as measured structure.
- Generate or select SFX only after clip placement. Prefer original location sound when it is more authentic, and allow silence.
- Each phase gets contract tests, one representative smoke, and one frozen acceptance run. A known failure type gets at most one correction per phase before a stage report and review.
- Record paid-call count, expected/actual cost or credits, output status, and cache path. Missing cost evidence is written as `unknown`, never guessed.
- Do not claim Quduoduo, Dreamina, render, or end-to-end success until the corresponding evidence artifact exists.

## Scope Decomposition and File Map

The spec spans independently reviewable subsystems. This plan keeps one ordered roadmap, but every phase ends in working, testable software and a commit so a reviewer can stop before the next external-risk boundary.

- `local-media-scanner/director/schema.py` — all versioned Director input/output contracts and status/error records.
- `local-media-scanner/director/config.py` — duration, candidate-count, audio-analysis, timeline, and authorization settings.
- `local-media-scanner/director/scanner_bridge.py` — conservative conversion from `ScannerResult` to material records and a project profile.
- `local-media-scanner/director/material_enrichment.py` — local duplicate grouping, sparse source-audio evidence, SFX candidates, and recommended source ranges.
- `local-media-scanner/director/search_planner.py` — deterministic `UserCreativeBrief + MaterialLibraryProfile -> MusicSearchBrief` baseline.
- `local-media-scanner/director/catalog/base.py` — provider protocol and normalized catalog result.
- `local-media-scanner/director/catalog/fixture.py` — offline provider for tests and demos.
- `local-media-scanner/director/catalog/quduoduo.py` — parser for explicitly captured visible-page metadata; no browser control or selectors outside this adapter.
- `local-media-scanner/director/music_blueprint.py` — candidate-to-blueprint conversion and reference-safe prompt construction.
- `local-media-scanner/director/generation/base.py` — generation protocol and authorization envelope.
- `local-media-scanner/director/generation/dreamina.py` — audited Dreamina command adapter, disabled until capability evidence and user authorization exist.
- `local-media-scanner/director/music_analysis.py` — local beat, onset, RMS energy, section, and ending analysis from actual audio.
- `local-media-scanner/director/timeline.py` — section-to-slot planning independent of material selection.
- `local-media-scanner/director/clip_selector.py` — constraint-aware clip ranking and placement from Scanner evidence.
- `local-media-scanner/director/sfx.py` — SFX candidates and final original-sound/SFX/silence decisions.
- `local-media-scanner/director/render.py` — FFmpeg filter graph and bounded playable preview rendering.
- `local-media-scanner/director/project.py` — resumable project-state orchestration and artifact paths.
- `local-media-scanner/director/cli.py` — thin local CLI; algorithms remain in focused modules.
- `local-media-scanner/tests/director/` — offline unit/integration tests and synthetic audio/video fixtures.
- `local-media-scanner/prototype/fixtures/` — hand-authored catalog metadata and generated synthetic media only.
- `local-media-scanner/prototype/runs/<run-id>/` — ignored evidence per run, including authorization and external-call ledger.
- `local-media-scanner/PROTOTYPE.md` — commands, phase gates, evidence index, and known limitations.

The contract fields that connect tasks are fixed as follows:

```text
MaterialScanResult = file, source, technical, analysis_status, quality_evidence,
  motion_evidence, scene_candidates, object_candidates, people_evidence,
  representative_frames, duplicate_group_id, visual_impact_score,
  original_audio_value_candidate, sfx_candidates, recommended_ranges, errors
MaterialLibraryProfile = source_scanner_run_id, manifest_sha256, materials,
  total_source_duration_seconds, usable_material_count, scene_distribution,
  motion_distribution, orientation_distribution, processing_time_estimate_seconds
MusicSearchBrief = keywords, genres, moods, bpm_min, bpm_max,
  instrument_preferences, vocals, target_duration_seconds, evidence
MusicCandidate = provider, candidate_id, title, visible_tags, bpm, duration_seconds,
  author, label, detail_url, preview_url
MusicBlueprint = duration_seconds, bpm, meter, genre, instrumentation, vocals,
  sections, ending
GeneratedMusicAsset = status, provider, blueprint_hash, local_path, sha256,
  duration_seconds, mime_type, external_call, errors
MusicStructure = source_sha256, duration_seconds, bpm, beats_seconds,
  downbeats_seconds, energy_curve, sections, ending, confidence, errors
TimelineSlot = slot_id, start, end, section_role, energy, content_need,
  desired_motion, beat_start, beat_end
ClipPlacement = slot_id, file, source_in, source_out, source_duration,
  section_role, duplicate_group_id, score_components, relaxed_constraints
SfxCandidate = file, label, source_time_seconds, confidence, evidence_source
SfxPlan = status, items, errors
```

---

### Task 1: Freeze the Director contracts and local-only CLI

**Files:**
- Create: `local-media-scanner/director/__init__.py`
- Create: `local-media-scanner/director/schema.py`
- Create: `local-media-scanner/director/config.py`
- Create: `local-media-scanner/director/cli.py`
- Create: `local-media-scanner/tests/director/test_schema.py`
- Modify: `local-media-scanner/pyproject.toml`
- Modify: `local-media-scanner/.gitignore`

**Interfaces:**
- Produces versioned models named in spec section 9 plus `ProjectState`, `ProviderError`, and `ExternalCallRecord`.
- Produces `travel-director version` without importing browser or Dreamina adapters.

- [ ] **Step 1: Write failing strict-contract tests**

```python
from pydantic import ValidationError
from director.schema import MusicBlueprint, ProjectState, UserCreativeBrief

def test_brief_enforces_supported_duration() -> None:
    assert UserCreativeBrief(location="开封", travel_type="城市漫游", target_duration_seconds=60,
        orientation="portrait", style="明亮", mood="探索", rhythm="medium").target_duration_seconds == 60

def test_blueprint_rejects_reference_identity() -> None:
    payload = {"schema_version": "0.1.0", "duration_seconds": 60, "bpm": 116,
        "meter": "4/4", "genre": "轻电子旅行器乐", "instrumentation": ["木吉他"],
        "vocals": "none", "sections": [{"start": 0, "end": 60, "role": "climax", "energy": 0.8}],
        "ending": "明确落点，不淡出", "reference_title": "forbidden"}
    try:
        MusicBlueprint.model_validate(payload)
        raise AssertionError("reference identity was accepted")
    except ValidationError:
        pass

def test_project_state_records_failure_instead_of_faking_completion() -> None:
    state = ProjectState(project_id="demo", status="blocked", current_stage="music_generation",
        artifact_paths={}, errors=[{"stage": "music_generation", "code": "not_authorized", "message": "authorization required"}])
    assert state.status == "blocked"
```

- [ ] **Step 2: Run the focused test and verify the package is absent**

Run: `cd local-media-scanner && uv run pytest tests/director/test_schema.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'director'`.

- [ ] **Step 3: Implement strict versioned models and config**

Implement every model with `ConfigDict(extra="forbid")`. Use these exact core signatures:

```python
class UserCreativeBrief(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    location: str
    travel_type: str
    target_duration_seconds: int = Field(ge=30, le=180)
    orientation: Literal["landscape", "portrait"]
    style: str
    mood: str
    rhythm: Literal["low", "medium", "high"]
    vocals: Literal["instrumental_only", "instrumental_preferred", "allowed"] = "instrumental_preferred"
    instrument_preferences: list[str] = Field(default_factory=list)

class ArtifactStatus(StrictModel):
    status: Literal["pending", "completed", "failed", "blocked"]
    errors: list[ProviderError] = Field(default_factory=list)

class ExternalCallRecord(StrictModel):
    provider: str
    operation: str
    authorized_at: str
    call_count: int = Field(ge=0)
    expected_cost: str = "unknown"
    actual_cost: str = "unknown"
    output_status: Literal["not_started", "succeeded", "failed"]
    artifact_relpath: str | None = None
```

Define all section-9 objects with `schema_version="0.1.0"`, explicit `pending|completed|failed|blocked` status where work can fail, and no implicit success defaults. Add `DirectorConfig(max_internal_candidates=5, displayed_directions=3, min_clip_seconds=0.8, max_clip_seconds=6.0)`.

- [ ] **Step 4: Register the package and CLI, then pass tests**

Set Hatch packages to `packages = ["scanner", "director"]`, add `travel-director = "director.cli:app"`, and ignore `prototype/runs/`. Run:

```bash
cd local-media-scanner
uv lock --check
uv run pytest tests/director/test_schema.py -q
uv run travel-director version
```

Expected: tests PASS and CLI prints `0.1.0` without network access.

- [ ] **Step 5: Commit the contract boundary**

```bash
git add local-media-scanner/pyproject.toml local-media-scanner/.gitignore local-media-scanner/director local-media-scanner/tests/director
git commit -m "feat: freeze travel director contracts"
```

### Task 2: Adapt Scanner results into a conservative material library

**Files:**
- Create: `local-media-scanner/director/scanner_bridge.py`
- Create: `local-media-scanner/director/material_enrichment.py`
- Create: `local-media-scanner/tests/director/test_scanner_bridge.py`
- Create: `local-media-scanner/tests/director/test_material_enrichment.py`

**Interfaces:**
- Consumes: `scanner.schema.ScannerResult`, `scanner.schema.TestManifest`, and `DirectorConfig`.
- Produces: `to_material_scan(card: ScannerCard) -> MaterialScanResult`.
- Produces: `enrich_materials(materials, input_root, run_dir) -> list[MaterialScanResult]`.
- Produces: `build_library_profile(result: ScannerResult, manifest: TestManifest, run_dir: Path) -> MaterialLibraryProfile`.

- [ ] **Step 1: Write tests that enforce reliability boundaries**

```python
def test_candidate_semantics_remain_candidates(scanner_card) -> None:
    scanner_card.content.scene_type = "theme_park"
    scanner_card.field_status["content.scene_type"] = "candidate"
    material = to_material_scan(scanner_card)
    assert material.scene_candidates == ["theme_park"]
    assert material.confirmed_scene is None

def test_unreliable_people_count_does_not_create_story_weight(scanner_card) -> None:
    scanner_card.content.people_count_estimate = 30
    material = to_material_scan(scanner_card)
    assert material.people_evidence.count_lower_bound == 30
    assert material.story_priority is None

def test_profile_uses_duration_and_raw_motion_without_inventing_sla(scanner_result, manifest, run_dir) -> None:
    profile = build_library_profile(scanner_result, manifest, run_dir)
    assert profile.total_source_duration_seconds > 0
    assert profile.processing_time_estimate_seconds is None

def test_near_duplicate_frames_share_a_group(materials, input_root, run_dir) -> None:
    enriched = enrich_materials(materials, input_root, run_dir)
    assert enriched[0].duplicate_group_id == enriched[1].duplicate_group_id

def test_sparse_audio_evidence_never_becomes_confirmed_semantics(materials, input_root, run_dir) -> None:
    enriched = enrich_materials(materials, input_root, run_dir)
    assert enriched[0].original_audio_value_candidate.status in {"candidate", "unavailable"}
```

- [ ] **Step 2: Verify the tests fail before the bridge exists**

Run: `cd local-media-scanner && uv run pytest tests/director/test_scanner_bridge.py -q`

Expected: FAIL because `director.scanner_bridge` does not exist.

- [ ] **Step 3: Implement explicit mappings and abstention**

Use `field_status` as the gate. Technical metadata and raw CV values copy with provenance; `predicted` and `candidate` semantic values enter `*_candidates`; `abstained` and `unavailable` become `None` plus a `ProviderError`-compatible evidence note. Derive only bucketed distributions whose source is recorded. Never map `material_role_candidates` to editorial roles.

```python
def candidate_value(card: ScannerCard, key: str, value: T | None) -> list[T]:
    return [value] if value is not None and card.field_status.get(key) in {"predicted", "candidate"} else []

def build_library_profile(result: ScannerResult, manifest: TestManifest, run_dir: Path) -> MaterialLibraryProfile:
    cards = [to_material_scan(card) for card in result.items if card.analysis_status != "failed"]
    items = enrich_materials(cards, Path(manifest.input_root), run_dir)
    return MaterialLibraryProfile.from_materials(
        items, source_run_id=result.run_id, manifest_sha256=sha256_file(manifest)
    )
```

For duplicate evidence, compute a dHash for each existing representative thumbnail, group exact source hashes first, then group clips only when at least two representative-frame pairs have Hamming distance `<= 6`; never delete a duplicate automatically. For audio evidence, extract at most three 2-second mono 16 kHz windows with FFmpeg and record RMS, clipping ratio, spectral flatness, and onset density. Mark audio value and event labels as candidates only. Recommended ranges center on representative timestamps, clamp to source duration, merge overlap, and retain their evidence reason.

- [ ] **Step 4: Pass focused and Scanner regression tests**

Run: `cd local-media-scanner && uv run pytest tests/director/test_scanner_bridge.py tests/director/test_material_enrichment.py tests/test_schema.py tests/test_pipeline.py -q`

Expected: all selected tests PASS and existing `ScannerCard` JSON is unchanged.

- [ ] **Step 5: Commit the Scanner adapter**

```bash
git add local-media-scanner/director/scanner_bridge.py local-media-scanner/director/material_enrichment.py local-media-scanner/tests/director/test_scanner_bridge.py local-media-scanner/tests/director/test_material_enrichment.py
git commit -m "feat: bridge scanner evidence into material library"
```

### Task 3: Build the local creative brief and music search planner

**Files:**
- Create: `local-media-scanner/director/search_planner.py`
- Create: `local-media-scanner/tests/director/test_search_planner.py`
- Create: `local-media-scanner/prototype/fixtures/brief.json`
- Modify: `local-media-scanner/director/cli.py`

**Interfaces:**
- Consumes: `MaterialLibraryProfile`, `UserCreativeBrief`.
- Produces: `build_music_search_brief(profile, brief) -> MusicSearchBrief`.
- Produces CLI: `travel-director plan-search --scanner-result ... --brief ... --output ...`.

- [ ] **Step 1: Write a failing deterministic planner test**

```python
def test_search_brief_combines_user_and_material_evidence(profile, brief) -> None:
    result = build_music_search_brief(profile, brief)
    assert result.target_duration_seconds == brief.target_duration_seconds
    assert 60 <= result.bpm_min < result.bpm_max <= 180
    assert brief.location in result.keywords
    assert result.evidence.source_scanner_run_id == profile.source_scanner_run_id
    assert len(result.keywords) <= 8
```

- [ ] **Step 2: Run the focused test and observe the missing planner**

Run: `cd local-media-scanner && uv run pytest tests/director/test_search_planner.py -q`

Expected: FAIL because `build_music_search_brief` is absent.

- [ ] **Step 3: Implement a transparent baseline mapping**

Map `rhythm` to BPM bands `low=80–105`, `medium=105–125`, `high=125–150`; add at most two evidence-backed content keywords from candidate scene distribution; pass user instrument/vocal preferences through unchanged. Record every mapping in `MusicSearchEvidence.rules`, so a later agent implementation can replace this function without changing the object contract.

- [ ] **Step 4: Add CLI serialization and verify offline behavior**

Run:

```bash
cd local-media-scanner
uv run travel-director plan-search --scanner-result scanner_result.json --scanner-manifest benchmark/test_manifest.json --brief prototype/fixtures/brief.json --output /tmp/music-search-brief.json
python -m json.tool /tmp/music-search-brief.json >/dev/null
```

Expected: one valid `MusicSearchBrief`; no browser, Dreamina, login, or external-call ledger entry.

- [ ] **Step 5: Commit the local planning baseline**

```bash
git add local-media-scanner/director/search_planner.py local-media-scanner/director/cli.py local-media-scanner/prototype/fixtures/brief.json local-media-scanner/tests/director/test_search_planner.py
git commit -m "feat: derive auditable music search briefs"
```

### Task 4: Introduce catalog providers with an offline fixture path

**Files:**
- Create: `local-media-scanner/director/catalog/__init__.py`
- Create: `local-media-scanner/director/catalog/base.py`
- Create: `local-media-scanner/director/catalog/fixture.py`
- Create: `local-media-scanner/director/music_directions.py`
- Create: `local-media-scanner/prototype/fixtures/catalog-visible-results.json`
- Create: `local-media-scanner/tests/director/test_catalog_provider.py`
- Modify: `local-media-scanner/director/cli.py`

**Interfaces:**
- Produces `MusicCatalogProvider.search(brief: MusicSearchBrief) -> CatalogSearchResult`.
- Produces `rank_directions(result: CatalogSearchResult, limit: int = 3) -> list[MusicDirection]`.

- [ ] **Step 1: Write provider and three-direction tests**

```python
class MusicCatalogProvider(Protocol):
    provider_name: str
    def search(self, brief: MusicSearchBrief) -> CatalogSearchResult: ...

def test_fixture_provider_caps_internal_and_displayed_results(brief) -> None:
    result = FixtureCatalogProvider(FIXTURE).search(brief)
    assert len(result.candidates) <= 5
    directions = rank_directions(result, limit=3)
    assert len(directions) == 3
    assert all(item.preview_url.startswith("https://example.invalid/") for item in directions)
```

- [ ] **Step 2: Confirm tests fail before provider code exists**

Run: `cd local-media-scanner && uv run pytest tests/director/test_catalog_provider.py -q`

Expected: FAIL on missing catalog modules.

- [ ] **Step 3: Implement normalization and deterministic ranking**

Normalize only title, visible tags, BPM, duration, author/label, detail URL, and preview URL. Score BPM overlap, duration fit, mood/tag overlap, and instrument overlap; preserve the component scores in `MusicDirection.reasons`. Do not fetch or validate URLs in the fixture provider.

- [ ] **Step 4: Generate an offline review artifact**

Run: `cd local-media-scanner && uv run travel-director catalog-fixture --brief /tmp/music-search-brief.json --fixture prototype/fixtures/catalog-visible-results.json --output /tmp/music-directions.json`

Expected: exactly three directions and no network activity.

- [ ] **Step 5: Commit the replaceable catalog boundary**

```bash
git add local-media-scanner/director/catalog local-media-scanner/director/music_directions.py local-media-scanner/director/cli.py local-media-scanner/prototype/fixtures local-media-scanner/tests/director/test_catalog_provider.py
git commit -m "feat: add offline music catalog provider boundary"
```

### Task 5: Add the separately authorized Quduoduo visible-page adapter

**Files:**
- Create: `local-media-scanner/director/catalog/quduoduo.py`
- Create: `local-media-scanner/tests/director/fixtures/quduoduo-visible-page.json`
- Create: `local-media-scanner/tests/director/test_quduoduo.py`
- Modify: `local-media-scanner/PROTOTYPE.md`

**Interfaces:**
- Consumes an explicit JSON capture of user-visible result cards, not raw protected audio.
- Produces `parse_visible_results(payload: dict, brief: MusicSearchBrief) -> CatalogSearchResult`.

- [ ] **Step 1: Write parser tests for visible fields and hard caps**

```python
def test_visible_page_parser_keeps_only_allowed_fields(brief, visible_payload) -> None:
    result = parse_visible_results(visible_payload, brief)
    assert len(result.candidates) <= 5
    assert result.capture_scope == "current_visible_page"
    assert result.downloaded_audio_count == 0
    assert all(candidate.provider_payload is None for candidate in result.candidates)

def test_login_or_challenge_blocks_without_fake_candidates(brief) -> None:
    result = parse_visible_results({"page_state": "captcha", "cards": []}, brief)
    assert result.status == "blocked"
    assert result.candidates == []
```

- [ ] **Step 2: Run parser tests before implementation**

Run: `cd local-media-scanner && uv run pytest tests/director/test_quduoduo.py -q`

Expected: FAIL because the adapter is absent.

- [ ] **Step 3: Implement the DOM-independent parser**

Accept only `{page_url, captured_at, page_state, cards}` where each card has the normalized visible fields. Reject more than one page per capture, discard unknown raw fields, cap retained cards at five, and return `blocked` for `login_required|captcha|waf|unsupported_structure`.

- [ ] **Step 4: Pause for explicit user authorization before one browser smoke**

Do not open Quduoduo during Tasks 1–4. At this step, report the exact search brief and ask permission to open one current results page. If authorized, use the browser-control skill to capture visible metadata only, write `prototype/runs/<run-id>/catalog/visible-results.json`, record `call_count=1`, and stop on login/CAPTCHA/WAF. Do not download preview audio.

- [ ] **Step 5: Validate and commit code/fixture, not private session data**

Run: `cd local-media-scanner && uv run pytest tests/director/test_quduoduo.py -q && git diff --check`

Commit only adapter/tests/docs. Keep the live `prototype/runs/` capture ignored.

```bash
git add local-media-scanner/director/catalog/quduoduo.py local-media-scanner/tests/director local-media-scanner/PROTOTYPE.md
git commit -m "feat: parse bounded visible catalog results"
```

### Task 6: Convert a chosen direction into a reference-safe music blueprint

**Files:**
- Create: `local-media-scanner/director/music_blueprint.py`
- Create: `local-media-scanner/tests/director/test_music_blueprint.py`
- Modify: `local-media-scanner/director/cli.py`

**Interfaces:**
- Produces `build_blueprint(direction, brief) -> MusicBlueprint`.
- Produces `build_generation_prompt(blueprint) -> str`.

- [ ] **Step 1: Write duration, section, and leakage tests**

```python
def test_blueprint_sections_are_contiguous_and_cover_duration(direction, brief) -> None:
    blueprint = build_blueprint(direction, brief)
    assert blueprint.sections[0].start == 0
    assert blueprint.sections[-1].end == brief.target_duration_seconds
    assert all(a.end == b.start for a, b in zip(blueprint.sections, blueprint.sections[1:]))

def test_prompt_excludes_reference_identity(direction, brief) -> None:
    prompt = build_generation_prompt(build_blueprint(direction, brief))
    assert direction.title not in prompt
    assert direction.author not in prompt
    assert "复制旋律" not in prompt
```

- [ ] **Step 2: Verify failing tests**

Run: `cd local-media-scanner && uv run pytest tests/director/test_music_blueprint.py -q`

Expected: FAIL because blueprint functions do not exist.

- [ ] **Step 3: Implement a five-section, duration-safe baseline**

Allocate intro/rise/breath/climax/outro with ratios `0.12/0.28/0.12/0.38/0.10`, round boundaries once, assign the remainder to outro, and validate contiguous coverage. Use only normalized high-level attributes and user brief fields. The prompt ends with `原创配乐；明确落点；不得复刻任何现有旋律、歌词或具体编曲。`.

- [ ] **Step 4: Verify local blueprint output**

Run: `cd local-media-scanner && uv run travel-director blueprint --directions /tmp/music-directions.json --choice 1 --brief prototype/fixtures/brief.json --output /tmp/music-blueprint.json`

Expected: valid 30–180 second blueprint and prompt; no generation call.

- [ ] **Step 5: Commit blueprint generation**

```bash
git add local-media-scanner/director/music_blueprint.py local-media-scanner/director/cli.py local-media-scanner/tests/director/test_music_blueprint.py
git commit -m "feat: build reference-safe music blueprints"
```

### Task 7: Audit Dreamina capability before adding a disabled generation adapter

**Files:**
- Create: `local-media-scanner/director/generation/__init__.py`
- Create: `local-media-scanner/director/generation/base.py`
- Create: `local-media-scanner/director/generation/dreamina.py`
- Create: `local-media-scanner/tests/director/test_generation_gate.py`
- Modify: `local-media-scanner/PROTOTYPE.md`

**Interfaces:**
- Produces `MusicGenerationProvider.generate(blueprint, authorization) -> GeneratedMusicAsset`.
- Produces `DreaminaCapabilities.from_help(text: str) -> DreaminaCapabilities`.
- Requires `GenerationAuthorization(provider="dreamina", max_calls=1, approved_by_user=True)`.

- [ ] **Step 1: Write authorization and capability tests**

```python
def test_generation_is_blocked_without_explicit_authorization(blueprint) -> None:
    provider = DreaminaMusicProvider(capabilities=CAPABLE, runner=forbidden_runner)
    asset = provider.generate(blueprint, GenerationAuthorization.denied("dreamina"))
    assert asset.status == "blocked"
    assert asset.errors[0].code == "not_authorized"

def test_missing_music_command_blocks_generation(blueprint) -> None:
    capabilities = DreaminaCapabilities.from_help("image\nvideo\n")
    assert capabilities.music_generation is False
```

- [ ] **Step 2: Run tests and implement the gate before inspecting the CLI**

Run: `cd local-media-scanner && uv run pytest tests/director/test_generation_gate.py -q`

Expected before implementation: FAIL. Implement the provider so command execution is impossible unless both capability and authorization are true.

- [ ] **Step 3: Perform read-only installed-CLI inspection**

Run only version/help commands discovered from the executable itself. Save redacted stdout/stderr and exit codes to `prototype/runs/<run-id>/dreamina/capabilities.json`. Do not login and do not generate. If no real music command exists, mark `music_generation=false` and stop this adapter phase.

- [ ] **Step 4: Pause for a new one-call authorization if capability exists**

Report command, expected output duration, whether pricing/credits are known, and exact maximum call count. Only after user authorization may the executor invoke one minimal music job. Record actual command with secrets redacted, call count, cost/credit evidence, duration, output hash, MIME type, and local path. A failed call still consumes the one-call budget.

- [ ] **Step 5: Pass offline tests and commit only reusable code/evidence summary**

Run: `cd local-media-scanner && uv run pytest tests/director/test_generation_gate.py -q`

Commit the adapter, tests, and redacted capability conclusion. Do not commit credentials or generated media.

```bash
git add local-media-scanner/director/generation local-media-scanner/tests/director/test_generation_gate.py local-media-scanner/PROTOTYPE.md
git commit -m "feat: gate audited music generation provider"
```

### Task 8: Analyze actual audio into beats, energy, sections, and ending

**Files:**
- Modify: `local-media-scanner/pyproject.toml`
- Create: `local-media-scanner/director/music_analysis.py`
- Create: `local-media-scanner/tests/director/test_music_analysis.py`
- Create: `local-media-scanner/tests/director/conftest.py`
- Create: `local-media-scanner/prototype/fixtures/generate_synthetic_media.py`
- Modify: `local-media-scanner/director/cli.py`

**Interfaces:**
- Produces `analyze_music(path: Path, config: AudioAnalysisConfig) -> MusicStructure`.
- Consumes local WAV/MP3/M4A only; no provider metadata determines measured timings.

- [ ] **Step 1: Add synthetic click-track tests**

Generate a 60-second 120 BPM WAV in the pytest fixture with NumPy and `soundfile`, including a low-energy 24–31 second section and a final impulse at 59.5 seconds. Put the same deterministic generator in `prototype/fixtures/generate_synthetic_media.py`; it accepts `--output-dir` and writes a click track plus five colored test videos without reading private material.

```python
def test_audio_analysis_measures_actual_structure(click_track) -> None:
    result = analyze_music(click_track, AudioAnalysisConfig())
    assert 116 <= result.bpm <= 124
    assert len(result.beats_seconds) >= 100
    assert any(section.role == "breath" and 20 <= section.start <= 30 for section in result.sections)
    assert result.ending.last_onset_seconds >= 59
```

- [ ] **Step 2: Add and lock local audio dependencies**

Add `librosa>=0.11,<1` and `soundfile>=0.13,<1`, then run `uv lock`. Before dependency download, report expected cache change; this is not a paid model call.

- [ ] **Step 3: Implement measured analysis with explicit confidence**

Load mono at 22,050 Hz, compute `beat_track`, onset envelope, RMS, four-beat bar candidates, and change points from smoothed energy/onset features. Label sections by relative energy and position, record confidence, and allow `unknown` rather than forcing all five roles. Detect ending from the last onset plus final RMS decay.

- [ ] **Step 4: Run focused and full offline tests**

```bash
cd local-media-scanner
uv run pytest tests/director/test_music_analysis.py -q
uv run pytest -q
```

Expected: synthetic BPM/sections pass and all Scanner/Director tests pass.

- [ ] **Step 5: Commit local audio analysis**

```bash
git add local-media-scanner/pyproject.toml local-media-scanner/uv.lock local-media-scanner/director/music_analysis.py local-media-scanner/director/cli.py local-media-scanner/prototype/fixtures/generate_synthetic_media.py local-media-scanner/tests/director
git commit -m "feat: analyze actual music structure locally"
```

### Task 9: Turn measured music structure into timeline slots

**Files:**
- Create: `local-media-scanner/director/timeline.py`
- Create: `local-media-scanner/tests/director/test_timeline.py`

**Interfaces:**
- Produces `build_timeline_slots(structure, brief, config) -> list[TimelineSlot]`.
- Timeline slots contain time/energy/content needs, never file choices.

- [ ] **Step 1: Write coverage and pacing tests**

```python
def test_slots_cover_music_without_overlap(structure, brief, config) -> None:
    slots = build_timeline_slots(structure, brief, config)
    assert slots[0].start == 0
    assert slots[-1].end == brief.target_duration_seconds
    assert all(a.end == b.start for a, b in zip(slots, slots[1:]))

def test_climax_is_faster_than_breath(structure, brief, config) -> None:
    slots = build_timeline_slots(structure, brief, config)
    climax = [s.duration for s in slots if s.section_role == "climax"]
    breath = [s.duration for s in slots if s.section_role == "breath"]
    assert sum(climax) / len(climax) < sum(breath) / len(breath)
```

- [ ] **Step 2: Verify the tests fail before timeline code exists**

Run: `cd local-media-scanner && uv run pytest tests/director/test_timeline.py -q`

Expected: FAIL because `director.timeline` is absent.

- [ ] **Step 3: Implement beat-aligned slot budgets**

Choose slot boundaries only from measured beats/downbeats. Use target mean durations `intro=3.5`, `rise=2.2`, `breath=4.5`, `climax=1.4`, `outro=3.5` seconds, clamped to config limits. Set opening need to `establishing_environment`, climax need to `high_visual_impact`, and outro need to `resolved_ending`; record fallback if a measured section role is unknown.

- [ ] **Step 4: Pass timeline tests and inspect JSON**

Run: `cd local-media-scanner && uv run pytest tests/director/test_timeline.py -q`

Expected: contiguous, positive-duration slots with measured beat references.

- [ ] **Step 5: Commit slot planning**

```bash
git add local-media-scanner/director/timeline.py local-media-scanner/tests/director/test_timeline.py
git commit -m "feat: build beat-aligned timeline slots"
```

### Task 10: Select and trim clips without exhausting strong material early

**Files:**
- Create: `local-media-scanner/director/clip_selector.py`
- Create: `local-media-scanner/tests/director/test_clip_selector.py`

**Interfaces:**
- Produces `place_clips(slots, materials, config) -> list[ClipPlacement]`.
- Consumes candidate semantics only as scored hints with provenance.

- [ ] **Step 1: Write selection constraint tests**

```python
def test_adjacent_slots_avoid_same_duplicate_group(slots, materials, config) -> None:
    placements = place_clips(slots, materials, config)
    assert all(a.duplicate_group_id != b.duplicate_group_id for a, b in zip(placements, placements[1:]))

def test_highest_impact_clip_is_reserved_for_climax(slots, materials, config) -> None:
    placements = place_clips(slots, materials, config)
    strongest = max(materials, key=lambda item: item.visual_impact_score).file
    chosen = next(item for item in placements if item.file == strongest)
    assert chosen.section_role == "climax"

def test_in_out_points_stay_inside_recommended_ranges(slots, materials, config) -> None:
    for item in place_clips(slots, materials, config):
        assert 0 <= item.source_in < item.source_out <= item.source_duration
```

- [ ] **Step 2: Run the failing selection tests**

Run: `cd local-media-scanner && uv run pytest tests/director/test_clip_selector.py -q`

Expected: FAIL because the selector is absent.

- [ ] **Step 3: Implement two-pass constrained ranking**

First reserve the top decile of evidence-backed visual-impact/motion candidates for climax. Then fill opening, breath, outro, rise, and climax slots with weighted scores for duration fit, raw motion fit, quality evidence, candidate scene diversity, source-range availability, and duplicate-group exclusion. Record each score component and every relaxed constraint. Never infer `human_story` from people detection.

- [ ] **Step 4: Test shortage degradation**

Add cases where there are fewer materials than slots. Reuse only after all unique candidates are exhausted, never use a known unusable item, and return `partial` plus `insufficient_material` if a slot cannot be filled.

Run: `cd local-media-scanner && uv run pytest tests/director/test_clip_selector.py -q`

- [ ] **Step 5: Commit clip placement**

```bash
git add local-media-scanner/director/clip_selector.py local-media-scanner/tests/director/test_clip_selector.py
git commit -m "feat: place scanner materials on music slots"
```

### Task 11: Plan original sound, generated SFX, or silence after placement

**Files:**
- Create: `local-media-scanner/director/sfx.py`
- Create: `local-media-scanner/tests/director/test_sfx.py`

**Interfaces:**
- Produces `collect_sfx_candidates(materials) -> list[SfxCandidate]`.
- Produces `build_sfx_plan(placements, candidates) -> SfxPlan`.
- Does not generate audio.

- [ ] **Step 1: Write post-placement and authenticity tests**

```python
def test_plan_contains_only_placed_materials(placements, candidates) -> None:
    plan = build_sfx_plan(placements, candidates)
    assert {item.file for item in plan.items} <= {item.file for item in placements}

def test_breath_prefers_valuable_location_sound(breath_placement, location_sound_candidate) -> None:
    plan = build_sfx_plan([breath_placement], [location_sound_candidate])
    assert plan.items[0].decision == "keep_original"

def test_no_candidate_can_remain_silent(placement) -> None:
    assert build_sfx_plan([placement], []).items[0].decision == "silence"
```

- [ ] **Step 2: Confirm the SFX planner is initially absent**

Run: `cd local-media-scanner && uv run pytest tests/director/test_sfx.py -q`

Expected: FAIL on missing module.

- [ ] **Step 3: Implement candidate normalization and decisions**

Candidate labels are `water|wind|rain|footsteps|door|vehicle|mechanical|applause|cheer|performance|food|glass|whoosh_motion|environment`. Decide `keep_original|enhance_original|generate_sfx|silence`, include a timeline-relative event time after trimming, and store the reason. Limit generated-SFX suggestions to visually grounded events and never add a sound to every transition.

- [ ] **Step 4: Pass offline SFX planning tests**

Run: `cd local-media-scanner && uv run pytest tests/director/test_sfx.py -q`

Expected: PASS; no provider or generated media involved.

- [ ] **Step 5: Commit the non-generative SFX plan**

```bash
git add local-media-scanner/director/sfx.py local-media-scanner/tests/director/test_sfx.py
git commit -m "feat: plan selective location sound and sfx"
```

### Task 12: Build resumable orchestration and immutable evidence paths

**Files:**
- Create: `local-media-scanner/director/project.py`
- Create: `local-media-scanner/tests/director/test_project.py`
- Modify: `local-media-scanner/director/cli.py`

**Interfaces:**
- Produces `create_project(run_root, project_id, brief) -> ProjectPaths`.
- Produces `advance_project(paths, target_stage, adapters) -> ProjectState`.

- [ ] **Step 1: Write resume and authorization-ledger tests**

```python
def test_existing_project_requires_matching_brief_hash(tmp_path, brief) -> None:
    paths = create_project(tmp_path, "demo", brief)
    with pytest.raises(ProjectConflict):
        create_project(tmp_path, "demo", brief.model_copy(update={"mood": "安静"}))

def test_resume_skips_completed_local_stage(tmp_path, adapters) -> None:
    state = advance_project(PROJECT, "timeline", adapters)
    resumed = advance_project(PROJECT, "timeline", adapters)
    assert resumed.completed_artifact_hashes == state.completed_artifact_hashes
```

- [ ] **Step 2: Run failing orchestration tests**

Run: `cd local-media-scanner && uv run pytest tests/director/test_project.py -q`

Expected: FAIL because project orchestration does not exist.

- [ ] **Step 3: Implement stage manifests and atomic local writes**

Create `project_state.json`, `brief.json`, `material_profile.json`, `search_brief.json`, `catalog/`, `blueprint.json`, `generation/`, `music_structure.json`, `timeline_slots.json`, `clip_placements.json`, `sfx_plan.json`, `render/`, and `external_calls.json`. Write to a sibling `.tmp` path then replace. Hash every input and output; resume only when hashes and schema versions match.

- [ ] **Step 4: Add a local-only orchestration smoke**

Run:

```bash
cd local-media-scanner
uv run python prototype/fixtures/generate_synthetic_media.py --output-dir prototype/runs/synthetic-inputs
uv run travel-director run-local --project-id fixture-demo --scanner-result scanner_result.json --scanner-manifest benchmark/test_manifest.json --brief prototype/fixtures/brief.json --catalog-fixture prototype/fixtures/catalog-visible-results.json --music prototype/runs/synthetic-inputs/click-track.wav --stop-after timeline
```

Expected: project reaches timeline using only local fixture/catalog/audio data; `external_calls.json` contains zero calls.

- [ ] **Step 5: Commit resumable orchestration**

```bash
git add local-media-scanner/director/project.py local-media-scanner/director/cli.py local-media-scanner/tests/director/test_project.py
git commit -m "feat: orchestrate resumable director projects"
```

### Task 13: Render one bounded playable montage locally

**Files:**
- Create: `local-media-scanner/director/render.py`
- Create: `local-media-scanner/tests/director/test_render.py`
- Modify: `local-media-scanner/director/cli.py`

**Interfaces:**
- Produces `build_ffmpeg_command(placements, music, sfx_plan, output, orientation) -> list[str]`.
- Produces `render_preview(...) -> RenderResult`.

- [ ] **Step 1: Write command-safety and duration tests**

```python
def test_ffmpeg_command_is_argument_list_without_shell(placements, music, output) -> None:
    command = build_ffmpeg_command(placements, music, SfxPlan(items=[]), output, "portrait")
    assert command[0] == "ffmpeg"
    assert "-filter_complex" in command
    assert all("; rm " not in argument for argument in command)

def test_rendered_duration_matches_music_within_frame(synthetic_project) -> None:
    result = render_preview(**synthetic_project)
    assert result.status == "completed"
    assert abs(result.duration_seconds - synthetic_project["music_duration_seconds"]) <= 1 / 24
```

- [ ] **Step 2: Run tests before render code exists**

Run: `cd local-media-scanner && uv run pytest tests/director/test_render.py -q`

Expected: FAIL because renderer is absent.

- [ ] **Step 3: Implement explicit FFmpeg trim/scale/concat/audio mixing**

Build one `trim,setpts,scale,crop,fps` chain per placement, concat video, map generated music as the bed, and mix only `keep_original|enhance_original` ranges from the source. Use H.264/AAC preview defaults, `-movflags +faststart`, and a fixed 24 fps. Pass a list to `subprocess.run(shell=False)` and capture stderr into `RenderResult` on failure.

- [ ] **Step 4: Render synthetic media and inspect with ffprobe**

Run:

```bash
cd local-media-scanner
uv run python prototype/fixtures/generate_synthetic_media.py --output-dir prototype/runs/synthetic-inputs
uv run pytest tests/director/test_render.py -q
uv run travel-director render-project --project prototype/runs/fixture-demo --output prototype/runs/synthetic/render/montage.mp4
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height -of json prototype/runs/synthetic/render/montage.mp4
```

Expected: playable MP4, expected orientation/codecs, and no source overwrite.

- [ ] **Step 5: Commit local rendering**

```bash
git add local-media-scanner/director/render.py local-media-scanner/director/cli.py local-media-scanner/tests/director/test_render.py
git commit -m "feat: render bounded local montage previews"
```

### Task 14: Run gated prototype acceptance and write the evidence-backed conclusion

**Files:**
- Modify: `local-media-scanner/PROTOTYPE.md`
- Create: `local-media-scanner/prototype/ACCEPTANCE.md`
- Create after acceptance: `local-media-scanner/memory_retention/2026-08-28-music-driven-travel-montage-prototype/summary.md`

**Interfaces:**
- Produces one immutable acceptance run and an explicit continue/continue-with-constraints/stop decision.
- Does not expand scope after the fixed acceptance run begins.

- [ ] **Step 1: Run all offline gates first**

```bash
cd local-media-scanner
uv run pytest -q
uv run travel-scanner validate-ground-truth --manifest benchmark/test_manifest.json --ground-truth ground_truth.json
git diff --check
git status --short
```

Expected: all tests pass, frozen Ground Truth validates, and only intended implementation/docs are changed.

- [ ] **Step 2: Freeze the acceptance inputs before external actions**

Write hashes for the selected Scanner result, user brief, music search brief, selected catalog direction metadata, blueprint, chosen source files, target duration, orientation, and maximum external calls. Use at most one Quduoduo visible-page capture and one Dreamina music-generation attempt. Do not schedule any SFX generation call in this acceptance.

- [ ] **Step 3: Request explicit authorization for each still-needed external boundary**

If real catalog evidence is missing, request one Quduoduo browser interaction. If a real generated music asset is missing and Dreamina capability was proven, separately request one Dreamina call with expected/actual credit recording. If either is denied or blocked, complete a fixture-based technical acceptance and label the real-provider/end-to-end claim `not_executed`.

- [ ] **Step 4: Execute exactly one representative end-to-end run**

Run the frozen pipeline once from Scanner result through rendered montage. Inspect project-state failures, three music directions, prompt leakage, measured BPM/sections, slot coverage, duplicate adjacency, clip source bounds, SFX-plan scope, MP4 duration/orientation/codecs, and external-call ledger. One newly observed failure type may be corrected once and rerun once; otherwise stop and report.

- [ ] **Step 5: Record results, retention summary, and final commit**

`ACCEPTANCE.md` must distinguish fixture, local-real, browser-real, provider-real, and not-executed evidence. Record actual timing, material count, selected clip count, reuse count, unfilled slots, provider calls/cost, render result, and known failures. Only after these gates, create the memory-retention summary with commit IDs, commands, hashes, evidence paths, external boundaries, and exact next step.

```bash
git add local-media-scanner/PROTOTYPE.md local-media-scanner/prototype/ACCEPTANCE.md local-media-scanner/memory_retention/2026-08-28-music-driven-travel-montage-prototype
git commit -m "docs: conclude music-driven montage prototype"
git status --short --branch
git log --oneline --decorate -20
```

Expected: a clean implementation worktree, no credentials or protected audio committed, and no success claim beyond stored evidence.

## Review Gates Before Execution

1. Approve or revise the `director` sibling-package architecture and the decision to leave Scanner contracts unchanged.
2. Approve the phased external-service gates: offline foundation first, Quduoduo visible-page smoke second, Dreamina read-only capability audit third, then separately authorized generation.
3. Approve librosa/soundfile as local audio-analysis dependencies and FFmpeg as the only preview renderer.
4. Approve the first acceptance boundary: one catalog capture, at most one music-generation attempt, no generated SFX call, one representative end-to-end render.
