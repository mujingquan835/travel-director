# Subjective Audiovisual Review

Read this reference when conducting and recording the final subjective listening and viewing review of an edited sequence.

Passing automated test suites, valid FCPXML generation, and successful Jianying NLE import/reopen are necessary preconditions, but they never substitute for human ears and eyes.

---

## 1. Three Orthogonal Verification Dimensions

Verification in Travel Director is strictly divided into three independent dimensions:

1. **Program Verification (`program_verification`)**:
   - Automated testing, data contract constraints, SHA-256 hash consistency, time bounds, pre-roll arithmetic, and non-overlapping track allocations.
2. **Client Compatibility (`client_compatibility`)**:
   - Verification that the NLE client (e.g. Jianying Pro macOS) can parse the FCPXML, advance the playhead, accept parameter edits, save the draft, and reopen it without corruption. Recorded via `record-fcpxml-acceptance`.
3. **Subjective Audiovisual Quality (`audiovisual_quality`)**:
   - Human listening and viewing appraisal of storytelling clarity, motion continuity, auditory spatial planes, acoustic realism, and musical breathing. Recorded via `record-audiovisual-review`.

No dimension may masquerade as another. A delivery that passes program tests and imports cleanly into Jianying remains unaccepted aesthetically until this subjective review is recorded.

---

## 2. Three-Step Review Protocol

Every review report must execute and document three distinct phases in order:

### Phase 1: Silent Picture Review (`silent_picture`)
Mute all audio. Watch only the picture:
- **`temporal_flow`**: Is the cutting rhythm natural? Does it feel rushed, mechanical, or dragging?
- **`event_clarity`**: Can a viewer immediately identify the primary subject, setting, and physical actions?
- **`cut_connection_validity`**: Does each transition have a discernible connection (direction, motion match, visual attraction point, or deliberate contrast)?

### Phase 2: Audio-Only Review (`audio_only`)
Blank the monitor or close your eyes. Listen only to the audio tracks:
- **`ambient_continuity`**: Does the ambient track provide spatial presence, or does it abruptly drop or restart at each cut?
- **`foley_anchor_sync`**: Does the foley accent feel acoustically grounded with natural pre-roll build-up rather than late or synthetic?
- **`dynamic_range_and_planes`**: Are foreground, midground, and background planes distinct? Does music duck appropriately during key acoustic events or pauses?

### Phase 3: Combined Review (`combined`)
Watch and listen together:
- **`foreground_competition`**: Are the music, dialogue, and foley clashing for foreground attention, or is there clear narrative hierarchy?
- **`rhythm_breathing`**: Does the sequence breathe? Are accents earned by visual narrative instead of formulaic "whoosh on every cut"?

---

## 3. Four-Variant Comparison Matrix (A/B/C/D)

When evaluating revisions or troubleshooting drafts, evaluate localized 15–20 second sequences across four structured variants:

| Variant | Kept Constant | Changed | Question Answered |
| --- | --- | --- | --- |
| **A Baseline** | Raw material, music, sfx | None | What is the baseline problem? |
| **B Picture Revised** | Same music & audio | Reordered/fine-reviewed shots | Did visual continuity & shot connection improve? |
| **C Sound Revised** | B's picture & music | Sound event anchors, ambient continuity, foley, ducking | Is the acoustic world believable with dynamic breathing? |
| **D Music Swapped** | C's picture & sound | Alternative music track | Does alternative music better match emotional tone? |

---

## 4. Recording Review Evidence

Author an `audiovisual_review.json` conforming to `AudiovisualReviewReport` and record it into the delivery package's `receipt.json`:

```bash
uv run travel-director record-audiovisual-review \
  --receipt <path/to/receipt.json> \
  --review <path/to/audiovisual_review.json>
```

Verify recorded evidence:

```bash
uv run travel-director inspect-audiovisual-review --receipt <path/to/receipt.json>
```

When `overall_verdict` is `accepted`:
- `receipt["audiovisual_status"]` becomes `"reviewed"`.
- `mix_listening_status` in both `music_adaptation` and `sound_design` snapshots transitions from `"not_reviewed"` to `"reviewed"`.

If any sub-phase needs revision, `overall_verdict` must be `needs_revision`, accompanied by actionable `revision_recommendations`.
