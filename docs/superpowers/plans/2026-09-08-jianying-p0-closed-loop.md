# Jianying P0 Closed Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and verify one new 12-second Jianying 11.4.0 draft containing three editable source-video clips, one editable music track, and two editable sound-effect clips, plus a preview generated from the same timeline manifest.

**Architecture:** A small deterministic trial builder owns one versioned timeline manifest and renders the review MP4 from it. Jianying is populated through its supported local UI because version 11.4.0 stores encrypted draft payloads; the trial never writes encrypted draft internals. A verification receipt records both file-level evidence and the manual edit/save/reopen result.

**Tech Stack:** Python 3.12, Pydantic, FFmpeg/ffprobe, pytest, Jianying Pro 11.4.0 macOS UI.

**Spec:** `/Users/meimaodawang/Documents/旅行导演/docs/reviews/2026-09-08-wansuishan-skill-optimization.md`

## Global Constraints

- Work only in `/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1` for repository changes.
- Reuse the existing 万岁山 scan and observations; perform zero new scan or visual-model calls.
- Create a new Jianying test project named `TD-P0-万岁山-12s-20260908`; never change or delete an existing draft.
- Do not write Jianying 11.4.0 encrypted `draft_info.json` directly.
- Use exactly the three video sources and ranges, music, and two SFX events defined in Task 1.
- A generated MP4 or JSON alone is not completion. Completion requires Jianying UI evidence that the project opens, tracks are editable, one clip boundary can be changed, the project saves, and it reopens.

---

### Task 1: Deterministic trial manifest and preview

**Files:**
- Create: `local-media-scanner/director/jianying_trial.py`
- Modify: `local-media-scanner/director/cli.py`
- Create: `local-media-scanner/tests/director/test_jianying_trial.py`

**Interfaces:**
- Produces: `build_p0_trial(output_dir: Path) -> JianyingTrialResult`
- Produces CLI: `uv run travel-director jianying-trial --output <directory>`
- Output files: `jianying_trial.json`, `TD-P0-万岁山-12s-preview.mp4`, `jianying_trial_receipt.json`

Trial timeline values:

- Canvas: 1920x1080, 30 fps, duration 12.0 seconds.
- Video 1: `/Users/meimaodawang/Desktop/万岁山素材/2026_02_06_18_40_27_IMG_0235.MOV`, source 1.000–5.000 seconds, timeline 0.000–4.000 seconds.
- Video 2: `/Users/meimaodawang/Desktop/万岁山素材/2026_02_07_13_24_51_IMG_0364.MOV`, source 1.000–5.000 seconds, timeline 4.000–8.000 seconds.
- Video 3: `/Users/meimaodawang/Desktop/万岁山素材/2026_02_07_21_24_44_IMG_0504.MOV`, source 2.000–6.000 seconds, timeline 8.000–12.000 seconds.
- Music: `/Users/meimaodawang/Documents/旅行导演/local-media-scanner/prototype/runs/travel-project-70811bf416/generation/assets/music-bd40015805a4621c.wav`, source 0.000–12.000 seconds, timeline 0.000–12.000 seconds, gain 0.35.
- SFX 1: `/Users/meimaodawang/Documents/音效及音乐/音效/风声/CZG_Whoosh_007.wav`, source 0.000–2.160 seconds, timeline 0.000–2.160 seconds, gain 0.80.
- SFX 2: `/Users/meimaodawang/Documents/音效及音乐/音效/上升音效/CZG_SubDrop_001.wav`, source 0.000–2.94644 seconds, timeline 7.600–10.54644 seconds, gain 0.75.
- Source-video audio is muted in the preview; Jianying video clips remain editable and their source audio may remain attached but muted.

- [ ] Write a failing test that invokes `build_p0_trial` in a temporary directory and asserts the literal timeline values, six media identities, 12-second preview duration within one frame, H.264/AAC codecs, 1920x1080 dimensions, and SHA-256 receipt verification.
- [ ] Run `uv run pytest tests/director/test_jianying_trial.py -q` and confirm failure because the module/API does not exist.
- [ ] Implement the minimal schema, input-duration validation, shell-free FFmpeg renderer, ffprobe verification, atomic JSON writes, and CLI command.
- [ ] Run the focused test and then the full test suite.
- [ ] Run the CLI against `local-media-scanner/prototype/runs/jianying-p0-20260908` and verify its receipt without scanning or model calls.
- [ ] Commit the Task 1 source and tests.

### Task 2: Create and verify the Jianying draft

**Files:**
- Create: `local-media-scanner/prototype/runs/jianying-p0-20260908/jianying_ui_receipt.json`

**Interfaces:**
- Consumes: Task 1 `jianying_trial.json` and the seven local media files.
- Produces: one new Jianying project `TD-P0-万岁山-12s-20260908` and a UI verification receipt.

- [ ] In Jianying Pro 11.4.0, create the new project and import the three videos, music, and two SFX.
- [ ] Place and trim all items to the exact manifest ranges and timeline positions; mute source-video audio.
- [ ] Confirm the project shows three separate video clips and three editable audio-track items, and play the timeline.
- [ ] Change Video 2 end boundary from timeline 8.000 to 7.900 seconds, verify the gap/change is visible, then restore it to 8.000 seconds. This is the editability proof.
- [ ] Save/return to home, reopen the named project, and verify all media and track positions persist.
- [ ] Write `jianying_ui_receipt.json` with app version, project title/path, manifest hash, track inventory, editability operation, save/reopen timestamps, and verification status.

### Task 3: Final verification and Skill boundary update

**Files:**
- Modify: `skills/travel-director/SKILL.md`
- Modify installed copy only after repository tests pass: `/Users/meimaodawang/.codex/skills/travel-director/SKILL.md`

**Interfaces:**
- Consumes: Task 1 and Task 2 receipts.
- Produces: an accurate experimental P0 capability statement; it must not claim automatic draft export.

- [ ] Add one focused behavior test that the Skill routes an explicit P0 trial request to the new CLI and requires UI verification before reporting completion.
- [ ] Run the test and confirm it fails before editing the Skill.
- [ ] Update the repository Skill to describe the verified experimental path and retain the planning-only boundary for normal runs.
- [ ] Run focused and full tests, then copy the repository Skill to the installed location and confirm byte parity.
- [ ] Commit Task 3 and record final artifact hashes and zero external/model calls.
