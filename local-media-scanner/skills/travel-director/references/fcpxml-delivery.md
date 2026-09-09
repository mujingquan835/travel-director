# Validated FCPXML delivery

Read this reference only when the user requests an editable Jianying handoff or asks to materialize an already chosen edit. The model writes a short decision JSON; local code owns probing, ranges, tracks, gain conversion, media references, packaging, FCPXML serialization and receipt validation.

## Generate

Follow `docs/contracts/fcpxml-edit-decision-v0.1.0.md` in the resolved package root. Include only the chosen video, music and SFX segments. Run:

```bash
uv run travel-director export-fcpxml --decision <absolute-decision.json> --output <new-package-directory>
```

The output directory must be new. A successful command writes `project.fcpxml`, `asset/` and `receipt.json`. Report `fcpxml_generated` as program generation only. At this point `client_import`, `client_playback` and `client_edit_save` must remain `not_tested`.

## Accept in Jianying

Use Jianying only for final acceptance:

1. Import `project.fcpxml` and verify the expected video/audio segment counts and duration.
2. Play from a known timecode and confirm the playhead advances.
3. Change one reversible numeric parameter, preferably one SFX volume.
4. Close the editor, reopen the draft from Jianying's home screen, and verify the timeline remains intact and the changed value persists.

Do not add, trim, reorder, relink or mix clips in Jianying to repair the generated timeline. If import or persistence fails, retain `fcpxml_generated`, record the observed incompatibility, and return to the decision/exporter. Limit compatibility work to two evidence-backed corrections; do not fall back to mouse-built delivery.

After all four checks visibly pass, let the program update the receipt:

```bash
uv run travel-director record-fcpxml-acceptance \
  --receipt <absolute-receipt.json> \
  --application "剪映专业版 macOS" \
  --application-version <version> \
  --draft-name <name> \
  --observed-video-segments <count> \
  --observed-audio-segments <count> \
  --playhead-before <HH:MM:SS:FF> \
  --playhead-after <HH:MM:SS:FF> \
  --edit-asset <name> \
  --edit-field volume_db \
  --edit-before <number> \
  --edit-after <number> \
  --reopen-value <number> \
  --accepted-at <ISO-8601>
```

The command verifies the FCPXML hash, expected segment counts, playhead movement, a real value change and reopen persistence. Only its `fcpxml_client_accepted` result permits reporting Jianying acceptance.

## Music replacement and cached understanding

Use the existing `--new-music-version` flow first. It copies validated visual observations and creative evidence into an independent child while excluding the frozen music, music analysis, timeline and delivery. Build a new timeline/decision and FCPXML package from that child. Do not reread contact sheets or rescan video when the source inventory and observation hashes still validate.

## Template and reference loading

Use metadata, filenames and `rg` matches to shortlist relevant templates or reference entries. Open only the selected entry and evidence needed for the current decision. Never recursively read template, asset, example or reference directories into context. If no entry matches, proceed from the Brief and cached material evidence and record that no template was used.

## Match and place local SFX

When sound effects are requested for an editable handoff, turn selected picture events into `sfx_cues` in the concise decision, then run the same exporter with `--sfx-root <actual-sound-effects-directory>`. Do not stop at a prose SFX plan or manually browse the entire music library. Reuse existing shot decisions and cached observations; matching does not need footage extraction or another visual pass.

Each cue supplies `cue_id`, `role`, `anchor_video_index` (zero-based among video clips in decision order), `event`, `offset_seconds` (relative to that video clip's timeline start), `duration`, and linear `gain`. Optional `keywords` must all match the filename; use them for concrete environmental sounds. Roles: `whoosh`, `riser`, `hook_hit`, `hook_subdrop`, `outro_hit`, `outro_piano`, `env_drone`, `env_ambient`. An ambient cue requires a keyword such as `火焰`; do not infer fire/crowd sounds from generic scenery. A shot boundary itself can anchor a transition sound. Preserve user silence/original-audio preferences when deciding which cues to submit; no universal minimum effect count.

```json
"sfx_cues": [{"cue_id":"cut-2","role":"whoosh","anchor_video_index":1,
  "event":"second picture enters","offset_seconds":0,"duration":0.6,"gain":0.5}]
```

The program selects by exact role and all supplied filename keywords, then shortest sufficient duration and stable path order. This is metadata matching, not listening or semantic recognition. It validates the event anchor and media range, writes each cue to a separate audio lane, copies SFX bytes into the package, and saves `resolved_decision.json` plus `receipt.sfx_matches` and `receipt.sfx_segments`. Explicit cues without a match fail before package creation; report the missing cue instead of claiming success or substituting an arbitrary sound.

Check that the receipt contains every requested cue and its resulting track, time range, gain and packaged material. `fcpxml_generated` means those segments exist in the validated FCPXML; it does not mean this package was imported into Jianying or sounds good. Follow the client acceptance section separately. Existing guide-only workflows remain planning output until an edit decision is exported.
