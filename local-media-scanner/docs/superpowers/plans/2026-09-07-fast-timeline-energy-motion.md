# Fast Timeline Energy and Motion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Fast Mode convert an explicit creative climax into shorter high-motion slots and calculate each slot's energy from the measured local energy curve.

**Architecture:** Keep music analysis unchanged. Extend `director.timeline` with typed editorial role overrides and interval-energy sampling, then let `director.delivery` translate `CreativeSection.climax` into a `climax` override before building slots. Music structure remains the base; an explicit creative climax controls editorial role only within its declared time range.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, Typer runner, JSON and Markdown delivery.

**Spec:** `/Users/meimaodawang/Documents/旅行导演/context_summary_20260907_real_case_fast_timeline.md`

## Global Constraints

- Preserve the public `travel-director run --build-timeline` command.
- Preserve beat-aligned, contiguous coverage from `0.0` to the requested target duration.
- Do not select footage or call an external provider.
- Treat `CreativeSection.climax` as the only structured creative role override; do not parse `music_change` or `visual_plan` prose.
- Preserve music-derived `breath` and `outro` behavior outside explicit climax ranges.
- Keep existing JSON keys compatible; no schema-version bump is required for corrected values.
- Validate against the real `travel-project-3d14b9a84b` project after unit and integration tests pass.

---

### Task 1: Add editorial role overrides to the beat timeline

**Files:**
- Modify: `director/timeline.py`
- Test: `tests/director/test_timeline.py`

**Interfaces:**
- Produces: `TimelineRoleOverride(start: float, end: float, role: Literal[...])`
- Changes: `build_timeline_slots(structure, brief, config=None, *, role_overrides=None) -> list[TimelineSlot]`
- Produces: `_interval_energy(structure, start, end, fallback) -> float`
- Consumes: measured `MusicStructure.energy_curve`, beats, downbeats, and music sections.

- [ ] **Step 1: Add a failing regression fixture for the Fireflies-shaped structure**

Add a test structure with one broad `intro` section from `0` to `48`, one `breath` section from `48` to `61.38`, one-second energy points, and an explicit `TimelineRoleOverride(start=34, end=49, role="climax")`.

```python
def test_creative_climax_override_changes_role_motion_and_density() -> None:
    measured = MusicStructure(
        duration_seconds=61.38,
        bpm=112.35,
        confidence=0.96,
        beats_seconds=[index * 0.535 for index in range(115)],
        downbeats_seconds=[index * 2.14 for index in range(29)],
        energy_curve=[
            EnergyPoint(time_seconds=float(second), value=value)
            for second, value in enumerate(
                [0.60] * 34 + [0.92] * 13 + [0.40] * 12 + [0.03] * 3
            )
        ],
        sections=[
            MusicStructureSection(start=0, end=48, role="intro", energy=0.79, confidence=0.8),
            MusicStructureSection(start=48, end=61.38, role="breath", energy=0.32, confidence=0.9),
        ],
        ending=MusicEnding(behavior="decay", last_onset_seconds=59.88),
        source_sha256="a" * 64,
    )
    slots = build_timeline_slots(
        measured,
        60.0,
        role_overrides=[TimelineRoleOverride(start=34, end=49, role="climax")],
    )
    climax = [slot for slot in slots if slot.section_role == "climax"]
    intro = [slot for slot in slots if slot.section_role == "intro"]
    assert climax
    assert all(slot.desired_motion == "high" for slot in climax)
    assert all(slot.content_need == "high_visual_impact" for slot in climax)
    assert sum(slot.duration for slot in climax) / len(climax) < sum(slot.duration for slot in intro) / len(intro)
    assert slots[0].start == 0.0
    assert slots[-1].end == 60.0
    assert all(left.end == right.start for left, right in zip(slots, slots[1:]))
```

- [ ] **Step 2: Run the new test and verify the current API fails**

Run:

```bash
uv run pytest tests/director/test_timeline.py::test_creative_climax_override_changes_role_motion_and_density -q
```

Expected: failure because `TimelineRoleOverride` and `role_overrides` do not exist.

- [ ] **Step 3: Define the typed role override and validation**

Add to `director/timeline.py`:

```python
TimelineRole = Literal["intro", "rise", "breath", "climax", "outro", "unknown"]


class TimelineRoleOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    role: TimelineRole

    @model_validator(mode="after")
    def end_after_start(self) -> "TimelineRoleOverride":
        if self.end <= self.start:
            raise ValueError("override end must be greater than start")
        return self
```

- [ ] **Step 4: Merge override boundaries with music boundaries**

Change `_snap_section_boundaries` to accept `role_overrides`. Add each override start/end that lies within the target duration, snapping internal values to the nearest measured beat/downbeat. Keep `0.0` and `target_duration` exact and de-duplicate sorted boundaries.

```python
for override in role_overrides or []:
    for value in (override.start, override.end):
        if 0 < value < target_duration and measured:
            boundaries.append(_nearest(measured, value))
```

Add a helper where the last matching override wins, though delivery will provide non-overlapping ranges:

```python
def _override_for_time(overrides: list[TimelineRoleOverride], midpoint: float) -> TimelineRoleOverride | None:
    matches = [item for item in overrides if item.start <= midpoint < item.end]
    return matches[-1] if matches else None
```

Use the override role before selecting `TimelineConfig.mean_for(role)` so climax ranges get denser slot subdivision.

- [ ] **Step 5: Calculate energy for each individual slot**

Add `_interval_energy` that averages points in `[start, end)`. If no point falls inside, use the nearest energy point; if the curve is empty, use the music-section energy.

```python
def _interval_energy(
    structure: MusicStructure,
    start: float,
    end: float,
    fallback: float,
) -> float:
    values = [
        point.value
        for point in structure.energy_curve
        if start <= point.time_seconds < end
    ]
    if not values and structure.energy_curve:
        midpoint = (start + end) / 2.0
        values = [min(structure.energy_curve, key=lambda point: abs(point.time_seconds - midpoint)).value]
    return float(min(1.0, max(0.0, sum(values) / len(values)))) if values else fallback
```

Store raw slots as `(start, end, role, fallback_energy)`, then call `_interval_energy` while constructing each `TimelineSlot`.

- [ ] **Step 6: Run timeline tests**

Run:

```bash
uv run pytest tests/director/test_timeline.py -q
```

Expected: all tests pass, including the new override, density, motion, continuity, and local-energy assertions.

- [ ] **Step 7: Commit Task 1**

```bash
git add director/timeline.py tests/director/test_timeline.py
git commit -m "fix: apply creative climax to timeline slots"
```

---

### Task 2: Wire creative climax ranges into Fast Mode delivery

**Files:**
- Modify: `director/delivery.py`
- Test: `tests/director/test_delivery.py`
- Test: `tests/director/test_creative_runner.py`

**Interfaces:**
- Consumes: `CreativeSection.climax`, `CreativeSection.start`, and `CreativeSection.end`.
- Consumes: `TimelineRoleOverride` and the updated `build_timeline_slots` API from Task 1.
- Produces: Fast Mode slots whose `section_role`, `content_need`, `desired_motion`, `energy`, and placeholder text agree.

- [ ] **Step 1: Strengthen the existing creative-section delivery test**

Extend `test_build_fast_mode_timeline_with_creative_sections`:

```python
    climax_slots = [slot for slot in tl.slots if slot.start >= 30.0]
    assert climax_slots
    assert all(slot.section_role == "climax" for slot in climax_slots)
    assert all(slot.desired_motion == "high" for slot in climax_slots)
    assert all(slot.content_need == "high_visual_impact" for slot in climax_slots)
    assert all("运镜: high" in slot.placeholder_text for slot in climax_slots)
```

Add a case with a non-climax creative section over music `breath` and assert the music-derived `breath` role remains unchanged.

- [ ] **Step 2: Run the delivery test and verify it fails**

Run:

```bash
uv run pytest tests/director/test_delivery.py::test_build_fast_mode_timeline_with_creative_sections -q
```

Expected: current Fast Mode slots still use music-only roles and motion.

- [ ] **Step 3: Translate explicit creative climaxes into timeline overrides**

In `build_fast_mode_timeline`, create overrides without parsing prose:

```python
role_overrides = [
    TimelineRoleOverride(start=section.start, end=section.end, role="climax")
    for section in creative_sections or []
    if section.climax
]
raw_slots = build_timeline_slots(
    music_structure,
    target_duration_seconds,
    timeline_config,
    role_overrides=role_overrides,
)
```

Keep the existing midpoint matching for `narrative_task` and `visual_plan`. Because placeholder text is built from the corrected raw slot, no separate Markdown-specific override is needed.

- [ ] **Step 4: Add runner-level delivery assertions**

In the existing `--build-timeline` completion test, load `delivery/fast_mode_timeline.json` and assert:

```python
payload = json.loads((project / "delivery" / "fast_mode_timeline.json").read_text())
climax_slots = [slot for slot in payload["slots"] if slot["section_role"] == "climax"]
assert climax_slots
assert {slot["desired_motion"] for slot in climax_slots} == {"high"}
assert all(slot["content_need"] == "high_visual_impact" for slot in climax_slots)
```

The fixture creative response must contain one `climax=True` section with explicit `material_gaps` when coverage reports a missing climax.

- [ ] **Step 5: Run focused delivery and runner tests**

Run:

```bash
uv run pytest tests/director/test_delivery.py tests/director/test_creative_runner.py -q
```

Expected: all focused tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add director/delivery.py tests/director/test_delivery.py tests/director/test_creative_runner.py
git commit -m "fix: inherit creative climax in fast delivery"
```

---

### Task 3: Generate and verify an independent 万岁山 validation delivery

**Files:**
- Create: `prototype/runs/travel-project-3d14b9a84b/validation/fast-timeline-90028cc/fast_mode_timeline.json`
- Create: `prototype/runs/travel-project-3d14b9a84b/validation/fast-timeline-90028cc/timeline_delivery.md`
- Modify if the installed skill documents exact behavior: `/Users/meimaodawang/.codex/skills/travel-director/references/workflow.md`

**Interfaces:**
- Consumes: the existing frozen music asset and creative revision in `travel-project-3d14b9a84b`.
- Produces: an independent real-case validation delivery with differentiated energy and motion while preserving the parent's hash-locked `completed` delivery.

- [ ] **Step 1: Run the full regression suite before regenerating artifacts**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Build an independent validation delivery from frozen evidence**

The parent delivery is hash-locked and must remain unchanged. `--new-music-version` requires a different music hash, so it cannot rebuild the same Fireflies selection. Use the same pure builder invoked by the Runner and save the result beneath the project's `validation` directory without recording it as a replacement completed artifact:

```bash
uv run python -c 'from pathlib import Path; from director.project import open_project; from director.audio_import import load_music_evidence; from director.creative_direction import load_creative; from director.audio_catalog import build_audio_catalog, resolve_audio_root; from director.delivery import build_fast_mode_timeline, save_fast_mode_delivery; root=Path("/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/prototype/runs/travel-project-3d14b9a84b"); paths=open_project(root); asset, structure=load_music_evidence(paths); creative, _, _=load_creative(paths, validate_sources=False); timeline=build_fast_mode_timeline(music_structure=structure, target_duration_seconds=creative.target_duration_seconds, music_asset_path=str((root / asset.frozen_relative_path).resolve()), music_title="Fireflies", creative_sections=creative.sections, sfx_entries=build_audio_catalog(resolve_audio_root()).sfx); output=root / "validation" / "fast-timeline-90028cc"; generated=save_fast_mode_delivery(timeline, output); print("\n".join(str(path.resolve()) for path in generated))'
```

Expected: two files are written below `validation/fast-timeline-90028cc`. Do not delete or edit the parent's frozen input, creative revision, delivery, receipt, or project state.

- [ ] **Step 3: Verify the real-case invariants**

Run:

```bash
jq -e '
  (.mode == "fast") and
  (.target_duration_seconds == 60) and
  (.slots[0].start == 0) and
  (.slots[-1].end == 60) and
  ([range(1; .slots|length) as $i | (.slots[$i-1].end == .slots[$i].start)] | all) and
  ([.slots[] | select(.start >= 34 and .start < 49) | .desired_motion] | index("high") != null) and
  ([.slots[] | select(.start >= 34 and .start < 49) | .section_role] | index("climax") != null)
' prototype/runs/travel-project-3d14b9a84b/validation/fast-timeline-90028cc/fast_mode_timeline.json
```

Expected: `true`.

Also confirm at least two distinct energy values occur before 48 seconds:

```bash
jq -e '[.slots[] | select(.start < 48) | .energy] | unique | length > 1' \
  prototype/runs/travel-project-3d14b9a84b/validation/fast-timeline-90028cc/fast_mode_timeline.json
```

Expected: `true`.

- [ ] **Step 4: Check Markdown parity**

Confirm `validation/fast-timeline-90028cc/timeline_delivery.md` contains `climax`, `high`, the 34–49 second narrative task, 17 or more contiguous slots as determined by the denser override, and the generated Hook paths. Confirm the JSON and Markdown describe the same slot boundaries.

- [ ] **Step 5: Run repository hygiene checks**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intended source, tests, documentation, and derived real-case artifacts appear.

- [ ] **Step 6: Commit Task 3**

```bash
git add docs/superpowers/plans/2026-09-07-fast-timeline-energy-motion.md
git commit -m "docs: record fast timeline verification plan"
```

The validation run artifacts are intentionally runtime evidence rather than source commits. Commit the plan and any workflow documentation, then record the exact validation artifact paths and verification results in the completion report.

---

## Stop Conditions

- Stop if the new override creates gaps, overlaps, slots shorter than `min_slot_seconds`, or a final boundary beyond 60 seconds.
- Stop if creative climax metadata is absent; preserve music-only behavior instead of inferring climax from prose.
- Stop if real-case regeneration would require deleting or mutating frozen source evidence.
- Stop before slow-mode shot selection, video rendering, provider calls, or editor-project export.

## Self-Review

- Spec coverage: the plan covers differentiated climax role, motion, content need, slot density, local energy, continuity, JSON/Markdown parity, and real-case regression.
- Placeholder scan: no implementation step contains TBD or unspecified behavior.
- Type consistency: `TimelineRoleOverride` is defined in Task 1 and consumed by `director.delivery` in Task 2; all slot properties use the existing `TimelineSlot` and `FastModeSlot` names.
