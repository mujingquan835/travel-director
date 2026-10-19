# Travel Director Skill Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `$travel-director` as the first-stage product entry, using the current invoking agent for bounded visual understanding, deterministic Director rules for treatment and three music prompts, and a local review page only when the confirmation threshold is exceeded.

**Architecture:** Keep `director/` as the only business-rule implementation and add a thin Skill orchestration layer. Scanner produces local evidence and representative frames; one contact sheet per material is grouped into batches of at most 10; the invoking agent writes strict batch checkpoints; Python validates and merges them, selects `none/chat/local_page` review routing, and builds a compact final summary. The version-controlled Skill source is installed as an identical runtime copy under `$CODEX_HOME/skills/travel-director`.

**Tech Stack:** Python 3.11+, Typer, Pydantic v2, Pillow, pytest, existing Scanner/Director CLIs, static local HTML, Codex Skill Markdown.

**Spec:** `docs/superpowers/specs/2026-08-31-travel-director-skill-delivery-design.md`

## Global Constraints

- Work only in `<checkout>/local-media-scanner` on `feature/local-media-scanner-v0.1`; inspect `git worktree list`, branch, HEAD, and status before every execution session.
- Preserve the four unrelated untracked context/plan files currently visible under `../docs/superpowers/`; do not stage, edit, or delete them.
- Do not call 曲多多、即梦、网易云、QQ 音乐、Spotify、Apple Music, a music-generation service, Codex API, or any paid/external provider. Every acceptance artifact must report `external_call_count=0` and the named services as `not_executed`.
- Do not bind a model name or provider in the Skill. It must use the visual capability of the agent that invoked it and must not create another task or sub-agent to switch models.
- Do not read complete videos in the invoking-agent step. Use one local contact sheet per material, containing 3–5 representative frames, with at most 10 contact sheets per batch.
- Agent-visible fields are limited to technical usability, content family, setting, lighting, people presence/count band, subject candidates, and activity candidates. Names, exact locations, relationships, and story identities are unsupported.
- Keep the local review page conditional: `none` for zero pending fields, `chat` when pending fields are at most 5 and affected materials at most 3, otherwise `local_page`. An explicit user request may force `local_page`; browser unavailability falls back to chat batches of at most 3 materials.
- Use TDD for every code task: one focused failing test run, implementation, one focused repair/retry if needed, then pass. Run the complete suite exactly once in Task 7.
- A stage is complete only after its focused tests, `git diff --check`, and named commit pass. Create a context summary Markdown only after the whole first-stage milestone passes, in accordance with `AGENTS.md`.

---

### Task 1: Add deterministic review routing contracts

**Files:**

- Create: `director/skill_workflow.py`
- Create: `tests/director/test_skill_workflow.py`
- Modify: `director/cli.py`

- [ ] **Step 1: Write the failing routing tests**

Create fixtures from the existing `ClipObservationBatch` factory and assert:

```python
def test_no_pending_fields_requires_no_review(observation_batch):
    route = choose_review_route(observation_batch)
    assert route.channel == "none"
    assert route.pending_field_count == 0


def test_five_fields_across_three_materials_stays_in_chat(observation_batch):
    route = choose_review_route(with_pending(observation_batch, count=5, materials=3))
    assert route.channel == "chat"


@pytest.mark.parametrize("fields,materials", [(6, 3), (5, 4)])
def test_exceeding_either_threshold_requires_local_page(
    observation_batch, fields, materials
):
    route = choose_review_route(
        with_pending(observation_batch, count=fields, materials=materials)
    )
    assert route.channel == "local_page"


def test_explicit_page_request_overrides_small_review(observation_batch):
    route = choose_review_route(observation_batch, force_local_page=True)
    assert route.channel == "local_page"
```

- [ ] **Step 2: Run the focused test and confirm the expected failure**

Run:

```bash
uv run pytest -q tests/director/test_skill_workflow.py
```

Expected: collection fails because `director.skill_workflow` does not exist.

- [ ] **Step 3: Implement the strict route model and unique-field counting**

Implement this public contract in `director/skill_workflow.py`:

```python
from typing import Literal

from pydantic import Field

from director.visual_schema import ClipObservationBatch, VisualStrictModel


ReviewChannel = Literal["none", "chat", "local_page"]


class ReviewQuestion(VisualStrictModel):
    material_id: str
    relative_path: str
    fields: list[str]


class ReviewRoute(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    channel: ReviewChannel
    pending_field_count: int = Field(ge=0)
    affected_material_count: int = Field(ge=0)
    questions: list[ReviewQuestion]
    reasons: list[str]


def choose_review_route(
    observations: ClipObservationBatch,
    *,
    max_chat_fields: int = 5,
    max_chat_materials: int = 3,
    force_local_page: bool = False,
) -> ReviewRoute:
    if max_chat_fields < 1 or max_chat_materials < 1:
        raise ValueError("review thresholds must be positive")
    questions = [
        ReviewQuestion(
            material_id=item.material.material_id,
            relative_path=item.material.relative_path,
            fields=sorted(set(item.review_required_fields)),
        )
        for item in sorted(
            observations.items, key=lambda row: row.material.relative_path
        )
        if item.review_required_fields
    ]
    pending = sum(len(question.fields) for question in questions)
    if pending == 0:
        channel = "none"
    elif force_local_page or pending > max_chat_fields or len(questions) > max_chat_materials:
        channel = "local_page"
    else:
        channel = "chat"
    return ReviewRoute(
        channel=channel,
        pending_field_count=pending,
        affected_material_count=len(questions),
        questions=questions,
        reasons=[f"pending_fields={pending}", f"affected_materials={len(questions)}"],
    )
```

Count unique `(material_id, field)` pairs from `review_required_fields`; do not count a duplicated field twice. Sort materials by `relative_path` and fields lexically so output is stable. Reject thresholds below 1. `force_local_page=True` is valid only when at least one review question exists; zero questions remains `none`.

- [ ] **Step 4: Add the read-only CLI command**

Add:

```text
travel-director plan-review \
  --observations <clip_observations.json> \
  --output <review_route.json> \
  [--force-local-page]
```

The command validates `ClipObservationBatch`, writes `ReviewRoute`, and creates no HTML.

- [ ] **Step 5: Run focused verification and commit**

Run:

```bash
uv run pytest -q tests/director/test_skill_workflow.py tests/director/test_visual_review.py
uv run travel-director plan-review --help
git diff --check
git add director/skill_workflow.py director/cli.py tests/director/test_skill_workflow.py
git commit -m "feat: route travel director confirmations"
```

Expected: tests pass; help lists `--observations`, `--output`, and `--force-local-page`; only the three intended files are committed.

---

### Task 2: Build one contact sheet per material and bounded agent batches

**Files:**

- Create: `director/agent_batches.py`
- Create: `tests/director/test_agent_batches.py`
- Modify: `director/scanner_bridge.py`
- Modify: `director/cli.py`
- Modify: `scanner/cli.py`
- Modify: `tests/test_metadata.py`

- [ ] **Step 1: Write failing tests for contact sheets and batching**

Cover these invariants:

```python
def test_contact_sheet_uses_three_to_five_frames(tmp_path, frame_images):
    sheet = build_contact_sheet(frame_images[:5], tmp_path / "sheet.jpg", "clip-a")
    assert sheet.exists()
    assert Image.open(sheet).mode == "RGB"


def test_batch_manifest_caps_every_batch_at_ten(material_frame_map, tmp_path):
    manifest = build_agent_batch_manifest(
        material_frame_map.with_item_count(23), tmp_path
    )
    assert [len(batch.items) for batch in manifest.batches] == [10, 10, 3]
    assert len({item.contact_sheet_path for item in manifest.items}) == 23


def test_missing_representative_frames_is_recorded_not_invented(
    material_frame_map, tmp_path
):
    manifest = build_agent_batch_manifest(
        material_frame_map.with_missing_frames("clip-a"), tmp_path
    )
    item = manifest.item_by_relative_path("clip-a.mov")
    assert item.status == "review_required"
    assert item.contact_sheet_path is None
```

Also test stable ordering, no more than five input frames per contact sheet, local paths only, and that an empty material map is rejected.

Add an integration test that builds `MaterialFrameMap` from `ScannerResult`, `ClipObservationBatch`, and the Scanner run directory. It must resolve each `FrameRecord.thumbnail_relpath` under the run directory, reject path traversal, match by immutable material/relative path, and preserve a material with missing frames as an empty frame set. Add a Scanner CLI test proving `inspect --output manifest.json` writes the same validated `TestManifest` that the command previously printed.

Add a bridge test for `build_scanner_observations_from_files(scanner_result, scanner_manifest, scanner_result_path)`. It must SHA-256 each source file beneath `TestManifest.input_root`, reject a source path escaping that root, pass those hashes into the existing `build_scanner_only_observations`, and bind evidence to the actual `scanner_result.json` hash.

- [ ] **Step 2: Run the focused test and confirm failure**

Run:

```bash
uv run pytest -q tests/director/test_agent_batches.py
```

Expected: collection fails because `director.agent_batches` does not exist.

- [ ] **Step 3: Implement strict batch schemas**

Add these public models:

```python
class MaterialFrameSet(VisualStrictModel):
    material: MaterialRef
    frame_paths: list[str] = Field(max_length=5)


class MaterialFrameMap(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    items: list[MaterialFrameSet] = Field(min_length=1)


class AgentMaterialPacket(VisualStrictModel):
    material_id: str
    relative_path: str
    status: Literal["ready", "review_required"]
    contact_sheet_path: str | None
    allowed_fields: list[str]
    source_evidence_refs: list[EvidenceRef]


class AgentBatch(VisualStrictModel):
    batch_id: str
    batch_index: int = Field(ge=0)
    items: list[AgentMaterialPacket] = Field(min_length=1, max_length=10)
    result_path: str


class AgentBatchManifest(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    max_batch_size: Literal[10] = 10
    items: list[AgentMaterialPacket]
    batches: list[AgentBatch]
```

The only allowed semantic fields are:

```python
AGENT_VISUAL_FIELDS = (
    "technical_usability",
    "content_family",
    "setting",
    "lighting",
    "people_presence",
    "people_count_band",
    "subject_candidates",
    "activity_candidates",
)
```

Implement `build_contact_sheet()` with Pillow and a deterministic two-column layout. It must use 3–5 frames when available, preserve aspect ratio, add only the material filename and frame timestamp labels, and never embed the source video. Implement `build_agent_batch_manifest()` with stable `relative_path` ordering and batches of exactly at most 10.

Implement `build_material_frame_map(scanner_result, scanner_observations, scanner_run_dir) -> MaterialFrameMap` in `director/scanner_bridge.py`. A resolved thumbnail must remain inside `scanner_run_dir`; select at most five saved representative frames in timestamp order. This bridge is the only supported way to create the frame map from a real Scanner run.

- [ ] **Step 4: Add the preparation CLI**

Extend `travel-scanner inspect` with optional `--output`. With the option, atomically write the validated manifest and print its path; without it, preserve the current stdout JSON behavior.

Add:

```text
travel-director build-scanner-observations \
  --scanner-result <scanner_result.json> \
  --scanner-manifest <input_manifest.json> \
  --output <scanner_only.json>

travel-director build-frame-map \
  --scanner-result <scanner_result.json> \
  --scanner-observations <scanner_only.json> \
  --scanner-run-dir <run-directory> \
  --output <material_frame_map.json>
```

Then add:

```text
travel-director prepare-agent-batches \
  --frame-map <material_frame_map.json> \
  --output-dir <project>/visual/agent_batches
```

It writes `manifest.json`, `contact_sheets/*.jpg`, and reserved result paths `results/batch-000.json`, etc. It does not run a model or open a browser.

- [ ] **Step 5: Run focused verification and commit**

Run:

```bash
uv run pytest -q tests/director/test_agent_batches.py
uv run pytest -q tests/test_metadata.py
uv run travel-director build-scanner-observations --help
uv run travel-director build-frame-map --help
uv run travel-director prepare-agent-batches --help
git diff --check
git add director/agent_batches.py director/scanner_bridge.py director/cli.py scanner/cli.py tests/director/test_agent_batches.py tests/test_metadata.py
git commit -m "feat: prepare bounded visual agent batches"
```

---

### Task 3: Validate invoking-agent results and resume from batch checkpoints

**Files:**

- Create: `director/agent_observations.py`
- Create: `tests/director/test_agent_observations.py`
- Modify: `director/cli.py`
- Modify: `director/project.py`

- [ ] **Step 1: Write failing validation and resume tests**

Test all of the following:

- A batch result may contain only the material IDs assigned to that batch.
- Every ready material appears exactly once; missing-frame materials remain `review_required` without a fabricated assertion.
- Assertions outside `AGENT_VISUAL_FIELDS` are rejected.
- `candidate` assertions require confidence and contact-sheet evidence; names, exact places, relationships, and story identities are rejected as unsupported fields.
- A valid completed checkpoint is reused byte-for-byte on resume.
- A malformed checkpoint gets one explicit validation error and is never silently replaced.
- Merging 12 materials from two result files produces one `ClipObservationBatch` while preserving measured Scanner assertions.

Use this result envelope:

```python
class AgentBatchResult(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    batch_id: str
    provider: Literal["invoking_agent"] = "invoking_agent"
    status: Literal["completed", "failed"]
    items: list[ClipObservation]
    errors: list[ProviderIssue] = Field(default_factory=list)
```

- [ ] **Step 2: Run the focused test and confirm failure**

```bash
uv run pytest -q tests/director/test_agent_observations.py
```

Expected: collection fails because `director.agent_observations` does not exist.

- [ ] **Step 3: Implement validation, atomic checkpoints, and merge**

Expose three typed public functions: `validate_agent_batch_result(manifest: AgentBatchManifest, result: AgentBatchResult) -> AgentBatchResult`, `write_agent_batch_checkpoint(result: AgentBatchResult, path: Path) -> Path`, and `merge_agent_batch_results(scanner_observations: ClipObservationBatch, manifest: AgentBatchManifest, result_paths: list[Path]) -> ClipObservationBatch`.

Use the existing atomic-write pattern from `director.project`. Preserve Scanner `measured` assertions, replace only matching semantic fields with invoking-agent `candidate`/`abstained` assertions, deduplicate evidence refs, and sort by material path. If any ready batch is absent or failed, output `mode="assisted"`, keep its fields in `review_required_fields`, and do not report the stage completed.

Extend `ProjectPaths` with:

```text
visual/agent_batches/manifest.json
visual/agent_batches/results/
visual/review_route.json
visual/final_summary.json
```

These are resumable supporting artifacts, not new mandatory stage names in `VISUAL_STAGE_ORDER`.

- [ ] **Step 4: Add validation and merge CLIs**

Add:

```text
travel-director validate-agent-batch \
  --manifest <manifest.json> \
  --result <batch-NNN.json>

travel-director merge-agent-batches \
  --scanner-observations <scanner_only.json> \
  --manifest <manifest.json> \
  --result-dir <results> \
  --output <clip_observations.json>
```

`validate-agent-batch` must exit non-zero on contract drift. `merge-agent-batches` must not reprocess valid checkpoints.

Add a generic, schema-safe stage recorder used by the Skill:

```text
travel-director record-visual-stage \
  --project <project-root> \
  --stage <V0.2-stage-name> \
  --artifact <validated-artifact.json>
```

Add `record_visual_stage_checked()` in `director.project` and call the existing `record_stage_artifact()` only after verifying every predecessor in `VISUAL_STAGE_ORDER` is present, hash-valid, and `status="completed"` where the model has a status field. It rejects a wrong schema, out-of-order stage, changed completed artifact, canonical artifact supplied as its own draft input, or untracked destination. Add tests that record `clip_observations`, resume with the identical draft artifact, reject a changed artifact, and reject `director_treatment` before its predecessors. The Skill records only the final merged/confirmed observation batch as `clip_observations`; scanner-only drafts, invoking-agent checkpoints, and review routes remain supporting artifacts. Every producer command writes under `visual/drafts/`, and `record-visual-stage` alone publishes to the canonical stage path.

- [ ] **Step 5: Run focused verification and commit**

```bash
uv run pytest -q tests/director/test_agent_observations.py tests/director/test_project.py
uv run travel-director validate-agent-batch --help
uv run travel-director merge-agent-batches --help
uv run travel-director record-visual-stage --help
git diff --check
git add director/agent_observations.py director/cli.py director/project.py tests/director/test_agent_observations.py tests/director/test_project.py
git commit -m "feat: checkpoint invoking agent observations"
```

---

### Task 4: Generate the review page only when routed and support chat fallback

**Files:**

- Modify: `director/skill_workflow.py`
- Modify: `director/visual_review.py`
- Modify: `director/cli.py`
- Modify: `tests/director/test_skill_workflow.py`
- Modify: `tests/director/test_visual_review.py`

- [ ] **Step 1: Write failing side-effect tests**

Add tests that call the routing/render function into an empty directory:

```python
def test_none_route_creates_no_html(clean_observations, frame_map, output_dir):
    artifact = prepare_visual_review(clean_observations, frame_map, output_dir)
    assert artifact.html_path is None
    assert not list(output_dir.glob("*.html"))


def test_chat_route_emits_questions_but_no_html(
    small_review_observations, frame_map, output_dir
):
    artifact = prepare_visual_review(
        small_review_observations, frame_map, output_dir
    )
    assert artifact.route.channel == "chat"
    assert artifact.chat_batches
    assert max(len(batch.material_ids) for batch in artifact.chat_batches) <= 3
    assert artifact.html_path is None


def test_local_page_route_emits_self_contained_html(
    large_review_observations, frame_map, output_dir
):
    artifact = prepare_visual_review(
        large_review_observations, frame_map, output_dir
    )
    html = Path(artifact.html_path).read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html
    assert "visual_confirmation.json" in html
```

- [ ] **Step 2: Run focused tests and confirm failure**

```bash
uv run pytest -q tests/director/test_skill_workflow.py tests/director/test_visual_review.py
```

Expected: tests fail because `prepare_visual_review` and chat batches are absent.

- [ ] **Step 3: Implement conditional rendering**

Add:

```python
class ChatReviewBatch(VisualStrictModel):
    material_ids: list[str] = Field(min_length=1, max_length=3)
    questions: list[ReviewQuestion]


class PreparedVisualReview(VisualStrictModel):
    route: ReviewRoute
    chat_batches: list[ChatReviewBatch]
    html_path: str | None = None
    confirmation_path: str | None = None
```

Implement `prepare_visual_review(observations, frame_map, output_dir, force_local_page=False)`. It must call the existing `render_visual_review()` only for `local_page`. For `chat`, create deterministic batches of at most 3 affected materials. For `none`, write only `review_route.json`. When a browser cannot be opened, the Skill will use these same chat batches; Python must not silently label the project complete.

- [ ] **Step 4: Add the conditional CLI**

```text
travel-director prepare-visual-review \
  --observations <clip_observations.json> \
  --frame-map <material_frame_map.json> \
  --output-dir <project>/visual/review \
  [--force-local-page]
```

The command prints the `PreparedVisualReview` JSON path. It must never call `open`; opening a page is an explicit Skill action after inspecting `route.channel`.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest -q tests/director/test_skill_workflow.py tests/director/test_visual_review.py
uv run travel-director prepare-visual-review --help
git diff --check
git add director/skill_workflow.py director/visual_review.py director/cli.py tests/director/test_skill_workflow.py tests/director/test_visual_review.py
git commit -m "feat: make visual review page conditional"
```

---

### Task 5: Create, validate, and install the `$travel-director` Skill

**Required skill before editing:** Read `skill-creator` completely, then apply its validation and packaging rules. Do not use `dreamina-cli`, browser-control, or any external-provider Skill.

**Files:**

- Create: `skills/travel-director/SKILL.md`
- Create: `skills/travel-director/references/workflow.md`
- Create: `skills/travel-director/references/visual-observation-contract.md`
- Create: `skills/travel-director/scripts/resolve_workspace.py`
- Create: `skills/travel-director/scripts/install.py`
- Create: `tests/director/test_travel_director_skill.py`

- [ ] **Step 1: Write failing static and installer tests**

Tests must verify:

```python
assert frontmatter["name"] == "travel-director"
assert "$travel-director" in skill_text
assert "每批最多 10" in skill_text
assert "超过 5 个字段" in skill_text
assert "超过 3 条素材" in skill_text
assert "external_call_count=0" in skill_text
assert not re.search(r"^model\s*:", skill_text, re.MULTILINE)
assert "Codex API" in skill_text and "不得调用" in skill_text
```

Also assert that all referenced local files exist, the workflow contains `automatic`, `assisted`, and `blocked` exits, the three prompts are returned in one final response, and the installer copies an identical tree into a temporary Codex home. Installer tests must prove an existing different destination is not overwritten without `--replace`, and `--replace` creates a recoverable timestamped backup.

- [ ] **Step 2: Run the focused test and confirm failure**

```bash
uv run pytest -q tests/director/test_travel_director_skill.py
```

Expected: tests fail because the Skill source does not exist.

- [ ] **Step 3: Write the Skill entry point**

Use this frontmatter and opening contract:

```markdown
---
name: travel-director
description: Use when a user wants to inspect a local travel-video folder, understand its footage from bounded contact sheets, turn the user's description into an evidence-bound director treatment, and return three ready-to-copy music-generation prompts without calling external music or generation services.
---

# Travel Director

Use the current invoking agent's existing visual capability. Do not declare or switch models, create another task, call Codex API, upload source media, or call any external or paid music/generation service.
```

`SKILL.md` must implement this exact decision sequence:

1. Resolve and validate the authoritative workspace; inspect project state and resume verified artifacts.
2. Get the source directory and the user's natural-language description; stop before scanning if either is absent.
3. Run local Scanner preparation and build one 3–5-frame contact sheet per material.
4. Read at most 10 contact sheets per batch and write `AgentBatchResult` JSON to its reserved result path; validate immediately; retry malformed structured output at most once.
5. If vision is unavailable, skip agent assertions, retain Scanner evidence, set `scanner_only + assisted`, and continue to review routing.
6. Normalize the Brief; ask only about blocking conflicts.
7. Merge observations and route review: none, chat, or page according to the approved thresholds. Open a page only after `local_page` is returned or the user explicitly asks.
8. Import confirmation JSON with hash validation; if the user declines required confirmation, finish `blocked` with checkpoints.
9. Build intent decisions, project coverage, DirectorTreatment, DirectorReview, and exactly three music prompts of at most 200 characters each.
10. Return compact results and clickable artifact paths in the current conversation; do not automatically open the final report.

Put the strict allowed-field JSON example and unsupported-inference rules in `references/visual-observation-contract.md`; put exact CLI commands, recovery commands, and stop states in `references/workflow.md`. The Skill entry point should link to these references rather than duplicating their full contents.

The workflow reference must use this local preparation sequence, with resolved absolute paths substituted by the invoking agent:

```bash
uv run travel-director init-visual-project --project-id <project-id> --raw-brief <raw-brief.json> --run-root <run-root>
uv run travel-scanner inspect --input <source-directory> --output <project>/visual/scanner/input_manifest.json
uv run travel-scanner scan --manifest <project>/visual/scanner/input_manifest.json --run-id scanner-v1 --runs-dir <project>/visual/scanner/runs --sampling-profile adaptive5 --device auto --no-models
uv run travel-director build-scanner-observations --scanner-result <project>/visual/scanner/runs/scanner-v1/scanner_result.json --scanner-manifest <project>/visual/scanner/input_manifest.json --output <project>/visual/scanner_only.json
uv run travel-director build-frame-map --scanner-result <project>/visual/scanner/runs/scanner-v1/scanner_result.json --scanner-observations <project>/visual/scanner_only.json --scanner-run-dir <project>/visual/scanner/runs/scanner-v1 --output <project>/visual/material_frame_map.json
uv run travel-director prepare-agent-batches --frame-map <project>/visual/material_frame_map.json --output-dir <project>/visual/agent_batches
```

`--no-models` is mandatory in this Skill path: Scanner supplies local technical/CV evidence and representative frames, while semantic visual fields come from the current invoking agent. On resume, validate and reuse an existing `scanner-v1/scanner_result.json`; otherwise invoke `scan` once. The reference must then list the exact validation, merge, review, Brief, treatment, automatic Director review, prompt, stage-recording, and final-summary commands added by this plan. Producer commands write drafts under `<project>/visual/drafts/`; only `record-visual-stage` publishes canonical stage artifacts. It must never ask the agent to synthesize missing JSON fields from memory; every JSON write is validated immediately by its corresponding CLI.

- [ ] **Step 4: Implement workspace resolution and recoverable installation**

`resolve_workspace.py` must use this precedence:

1. explicit `--workspace`;
2. `TRAVEL_DIRECTOR_WORKSPACE`;
3. the Git root of the current directory;
4. known local candidates under `<checkout>/`.

A candidate is valid only if `pyproject.toml` exposes both `travel-scanner` and `travel-director` and the `director/` package exists. It must print one absolute path or exit non-zero; it must never select root `main` merely because the directory exists.

`install.py` accepts `--codex-home` and optional `--replace`. It computes SHA-256 for every source file, copies through a staging directory, verifies the destination manifest, and then atomically publishes. Without `--replace`, a differing existing destination is a hard stop. With `--replace`, move the old copy to `travel-director.backup-YYYYMMDD-HHMMSS` before publishing.

- [ ] **Step 5: Run focused tests, install the Skill, and verify identity**

Run:

```bash
uv run pytest -q tests/director/test_travel_director_skill.py
uv run python skills/travel-director/scripts/resolve_workspace.py --workspace "$PWD"
uv run python skills/travel-director/scripts/install.py --codex-home $CODEX_HOME
diff -qr skills/travel-director $CODEX_HOME/skills/travel-director
git diff --check
```

Expected: all tests pass; resolver prints the active implementation checkout; `diff -qr` prints nothing. If a differing installed copy already exists, stop and inspect it before using `--replace`; do not overwrite it implicitly.

- [ ] **Step 6: Commit source and installer**

```bash
git add skills/travel-director tests/director/test_travel_director_skill.py
git commit -m "feat: package travel director skill"
```

---

### Task 6: Build the compact final Skill summary and external-call ledger gate

**Files:**

- Create: `director/skill_summary.py`
- Create: `tests/director/test_skill_summary.py`
- Modify: `director/cli.py`
- Modify: `director/project.py`
- Modify: `director/visual_review.py`
- Modify: `tests/director/test_visual_review.py`
- Modify: `skills/travel-director/references/workflow.md`

- [ ] **Step 1: Write failing summary tests**

Use complete V0.2 fixture artifacts to assert this model:

```python
class SkillRunSummary(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    project_mode: Literal["automatic", "assisted", "blocked"]
    material_count: int = Field(ge=0)
    successful_material_count: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    bucket_counts: dict[Bucket, int]
    logline: str | None
    chapter_titles: list[str]
    material_gaps: list[str]
    music_prompts: list[str] = Field(min_length=0, max_length=3)
    unsupported_inferences: list[str]
    artifact_paths: dict[str, str]
    external_call_count: Literal[0] = 0
    external_services: dict[str, Literal["not_executed"]]
```

Prove that:

- a normal completed project has exactly three prompts, each at most 200 characters;
- any unsupported inference, incomplete Brief confirmation, missing treatment review, or non-empty external-call ledger prevents a completed summary;
- a blocked project has zero prompts and retains checkpoint paths;
- counts derive from artifacts rather than prose supplied by the invoking agent.
- a zero-override automatic `DirectorReview` is hash-bound to the treatment and can be recorded without opening a page.

- [ ] **Step 2: Run focused tests and confirm failure**

```bash
uv run pytest -q tests/director/test_skill_summary.py
```

Expected: collection fails because `director.skill_summary` does not exist.

- [ ] **Step 3: Implement the summary builder and gate**

Implement:

```python
EXTERNAL_SERVICES = (
    "quduoduo",
    "dreamina",
    "netease_music",
    "qq_music",
    "spotify",
    "apple_music",
    "music_generation",
)


```

Expose `build_skill_run_summary(project_root: Path) -> SkillRunSummary`. Load artifacts through `open_project()` and the existing stage validators. A completed summary requires validated observations, Brief confirmation, intent decisions, coverage, treatment, director review, and three prompts. Read `external_calls.json`; only `[]` is accepted. Record every named service as `not_executed`. Use absolute artifact paths in the JSON so the Skill can emit clickable paths without searching.

Add `build_automatic_director_review(treatment: DirectorTreatment) -> DirectorReview` in `director.visual_review`. It computes the same canonical treatment hash as `validate_director_review`, sets `status="completed"`, `mode="automatic"`, `overrides=[]`, and `confirmed_at=None`. Expose it as:

```text
travel-director accept-director-treatment \
  --treatment <director_treatment.json> \
  --output <director_review.json>
```

This command is the default no-page path after the Skill has shown the five-bucket summary. Existing `render-director-review` remains an explicit later override path when the user asks to modify buckets.

- [ ] **Step 4: Add the CLI and Skill workflow command**

```text
travel-director skill-summary \
  --project <project-root> \
  --output <project-root>/visual/final_summary.json
```

Update `references/workflow.md` so this command is the only source for final counts, paths, mode, prompts, and external-call status. The invoking agent may explain the summary but may not recalculate or invent those fields.

After writing `final_summary.json`, `skill-summary` must construct and record the existing `VisualReviewArtifact` at the final `visual_review` stage, with `report_path` pointing to the summary JSON, `source_artifact_hashes` covering observations, Brief confirmation, treatment, director review, and music prompts, and `external_call_count=0`. This keeps the existing V0.2 stage graph intact without requiring or pretending that an HTML page was opened.

- [ ] **Step 5: Verify, reinstall, and commit**

```bash
uv run pytest -q tests/director/test_skill_summary.py tests/director/test_music_prompt_recommender.py tests/director/test_project.py tests/director/test_visual_review.py
uv run travel-director accept-director-treatment --help
uv run travel-director skill-summary --help
uv run python skills/travel-director/scripts/install.py --codex-home $CODEX_HOME --replace
diff -qr skills/travel-director $CODEX_HOME/skills/travel-director
git diff --check
git add director/skill_summary.py director/cli.py director/project.py director/visual_review.py skills/travel-director/references/workflow.md tests/director/test_skill_summary.py tests/director/test_project.py tests/director/test_visual_review.py
git commit -m "feat: summarize travel director skill runs"
```

The installer must create a recoverable backup because the Skill source changed after Task 5.

---

### Task 7: Run one frozen blind acceptance, complete documentation, and close the milestone

**Files:**

- Create after successful acceptance: `benchmark/manual_review/travel-director-skill-blind-v1-acceptance.json`
- Modify: `PROTOTYPE.md`
- Modify: `../docs/superpowers/plans/2026-08-31-visual-understanding-and-director-decision.md`
- Create only after all gates pass: `../docs/superpowers/context/2026-08-31-travel-director-skill-delivery-context.md`

- [ ] **Step 1: Recheck the acceptance boundary before spending model context**

Run:

```bash
git worktree list
git branch --show-current
git status --short
uv run python -c 'from pathlib import Path; from scanner.schema import TestManifest; from director.evaluation import membership_hash; p=Path("benchmark/director_visual_blind_manifest.json"); print(membership_hash(TestManifest.model_validate_json(p.read_text())))'
```

Verify the frozen blind membership digest recorded by the evaluation contract is still. This is the SHA-256 of the sorted relative-path membership list, not the whole manifest file bytes:

```text
3023699191e13c8ebe493c3426356e763bf091eeafc5ef4adb4bc38a240a544f
```

Do not open the ground-truth template while generating invoking-agent observations. Use only the blind manifest, local representative frames/contact sheets, and the `blind-primary` Brief.

- [ ] **Step 2: Execute `$travel-director` once on the 12-item blind split**

Use the installed Skill entry with:

```text
素材：benchmark/director_visual_blind_manifest.json 对应的 12 条本地素材
描述：benchmark/director_visual_briefs.json 中的 blind-primary
项目：benchmark/runs/travel-director-skill-blind-v1
```

Bound the run to two invoking-agent batches of at most 10 contact sheets each. Validate and save each batch before reading the next. A malformed structured batch gets one repair/retry only. If visual input is unavailable, record `scanner_only + assisted`; do not substitute the disqualified local VLM or claim automatic visual understanding.

If review routing is `chat`, confirm at most 3 materials at a time. If it is `local_page`, generate and open the single static page, verify images and controls, and wait for the user's confirmation JSON. If the user is unavailable or declines, record `blocked`, preserve checkpoints, and stop this task without claiming milestone completion.

- [ ] **Step 3: Record acceptance facts, not narrative estimates**

Write the tracked `benchmark/manual_review/travel-director-skill-blind-v1-acceptance.json` from actual artifacts. Its strict fields are: `schema_version="0.2.0"`, `split="blind"`, `material_count=12`, `invoking_agent_batch_count=2`, `max_batch_size=10`, `actual_mode` from `Literal["automatic", "assisted", "blocked"]`, `review_channel` from `Literal["none", "chat", "local_page"]`, non-negative `structured_batch_retry_count`, `external_call_count=0`, and every service in `EXTERNAL_SERVICES` set to `not_executed`. Add SHA-256 values for the batch manifest, both batch result files, merged observations, route, treatment, prompts, and final summary. Do not write this tracked record until all values have been read from those files.

- [ ] **Step 4: Perform the one browser check only if a page was routed**

If `review_channel != "local_page"`, record `browser_check="not_applicable"` and do not open a browser. If it is `local_page`, verify exactly once:

- every routed material has visible representative images;
- candidate, unknown, and confirmed states are visually distinct;
- no horizontal overflow at the current viewport;
- no remote request or remote script exists;
- downloaded confirmation JSON passes the existing source-hash validator.

Do not start a persistent web server; open the local static file directly.

- [ ] **Step 5: Run the complete verification suite exactly once**

Run:

```bash
uv run pytest -q
uv run python skills/travel-director/scripts/resolve_workspace.py --workspace "$PWD"
diff -qr skills/travel-director $CODEX_HOME/skills/travel-director
rg -n "model:|api_key|https?://" skills/travel-director
git diff --check
```

Expected:

- the full suite passes;
- source and installed Skill trees are identical;
- the static scan finds no model binding, credential, or external endpoint; descriptive mentions of forbidden APIs in prose are inspected manually and are not executable calls;
- the working tree contains only Task 7 artifacts/docs plus the four pre-existing unrelated untracked files.

- [ ] **Step 6: Update product documentation and supersede the old page-first Task 7/8 wording**

Update `PROTOTYPE.md` to state:

- `$travel-director` is the first-stage entry;
- the local page is conditional review only;
- invoking-agent visual batches are bounded and resumable;
- the first-stage output ends at treatment plus three music prompts;
- all named external/music services remain `not_executed`.

Mark the old static-page-first milestone in `2026-08-31-visual-understanding-and-director-decision.md` as superseded by this implementation plan; do not rewrite historical completed Task 1–7 facts.

- [ ] **Step 7: Create the milestone context summary only after all gates pass**

Create `2026-08-31-travel-director-skill-delivery-context.md` containing exact commits, test count, actual acceptance mode, review channel, retry count, browser status, artifact hashes/paths, installed Skill identity result, `external_call_count=0`, and remaining scope. If any gate is incomplete, do not create this file.

- [ ] **Step 8: Commit the milestone**

```bash
git add PROTOTYPE.md \
  benchmark/manual_review/travel-director-skill-blind-v1-acceptance.json \
  ../docs/superpowers/plans/2026-08-31-visual-understanding-and-director-decision.md \
  ../docs/superpowers/context/2026-08-31-travel-director-skill-delivery-context.md
git commit -m "docs: complete travel director skill milestone"
git status --short
```

Expected: the milestone commit succeeds; `git status --short` shows only the four unrelated pre-existing untracked files. If the blind run is blocked on user confirmation, commit only the truthful partial run artifacts in a separate commit named `test: record blocked travel director blind run`, omit the context summary, and leave this milestone open.

## Execution Stop Conditions

Stop immediately and report the exact artifact/error when any of these occurs:

- the active checkout/branch differs from the Global Constraints;
- source media or required representative frames cannot be resolved locally;
- an agent batch fails strict validation twice;
- the Brief has unresolved blocking conflicts;
- a confirmation hash does not match the project source hash;
- unsupported inference survives Director validation;
- the external-call ledger is non-empty;
- installation would overwrite a differing Skill without a recoverable backup;
- the user must confirm a chat/page review before deterministic stages can continue;
- the full suite fails after the one permitted focused repair/retry for the responsible task.

## Plan Self-Review Checklist

- [ ] Every requirement in the approved design maps to a named task and test.
- [ ] No implementation step calls an external/paid service or fixes a model name.
- [ ] Every local page creation is guarded by the approved threshold or explicit user request.
- [ ] Every invoking-agent operation is bounded to one contact sheet per material and at most 10 per batch.
- [ ] Every resumable boundary has a validated JSON checkpoint and stable path.
- [ ] The three music prompts are generated once, exactly three, and each is at most 200 characters.
- [ ] The installed Skill is verified identical to the repository source.
- [ ] Placeholder scan finds no `TODO`, `TBD`, `FIXME`, ellipsis implementation, or unresolved example value in deliverable code/artifacts.
- [ ] Type names and stage names match existing V0.2 contracts; supporting artifacts do not silently alter `VISUAL_STAGE_ORDER`.
- [ ] Milestone documentation and context are created only after measured acceptance evidence exists.
