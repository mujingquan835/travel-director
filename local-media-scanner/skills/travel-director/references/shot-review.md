# Selected-shot temporal review

Use after coarse observations identify an editing candidate, or when its connection needs local inspection. Preserve the existing 3–5-frame coarse pass and compact expansion. This independent contract is for source-time observations and proposed usable ranges, not a timeline, music decision or assertion that the shot was selected for final delivery.

## Prepare only selected intervals

From the resolved package root, reuse the existing project. Read only the relevant coarse observations/contact sheets to shortlist. Author a small selection JSON with known material IDs from `visual/scanner_only.json`:

```json
{"items":[{"material_id":"sha256:<known-source-hash>","source_in":2.8,"source_out":3.9,"purpose":"connection_uncertain","reason":"Inspect foreground occlusion before choosing a connection"}]}
```

`purpose` is `selected` or `connection_uncertain`; reason must describe the actual editorial question. Times are seconds relative to the original source start, not the project timeline. Select a window to inspect, not an already-verified edit point. Do not guess it is the best interval. At most 10 intervals per request, 8 seconds per interval and 40 seconds in total. Never use repeated requests to turn this into a default full-library rescan.

```bash
uv run travel-director prepare-shot-review --project <existing-project> --selection <selection.json>
```

This checks project membership and selected source hashes, decodes only these windows locally with FFmpeg, and creates `visual/shot_reviews/<request-id>/request.json`, dense JPEG frames, timestamped sheets, a response template and JSON schema. It does not run another model, scan music, or rewrite coarse observations. `external_call_count=0`.

The first version uses **dense still sequences**, not playback or a continuous-motion model. Default spacing is at least 0.125 seconds (approximately 8 fps; source frame rate can make it lower). Image long side is at most 640 pixels; sheets contain at most 12 ordered frames. Each `#index` matches that packet's `frames` array, with actual decoder timestamps translated to source seconds. Do not pretend these are all original frames. Open sheets sequentially; inspect individual images when a small detail is unreadable. Frame evidence is scoped to the cited samples, not automatically the whole shot.

## Author compact observations

Copy the returned response template to a separate working file and replace its reasons with real judgments. The program adds source references and evidence hashes; never hand-copy the full source record. Cover every packet once.

- `source_in`, `source_out`, `range_confidence`, `range_evidence_frames`, `range_reason`: proposed usable interval within the requested window. Support both boundaries with frame indices; this is an editorial proposal, not proof of frame-accurate optimality. If no usable range can be established, both times and confidence are null and evidence is empty, with a reason.
- `shot_scale`, `subject_position`, `camera_motion`, `subject_motion`: each has `value`, `confidence`, `evidence_frames`, `reason`. For unknowns use null value and confidence, empty evidence, and an explicit reason. Identify the primary subject in the reason; distinguish subject displacement from camera movement. Do not infer camera translation versus zoom when the images cannot distinguish them.
- `action_description`: observed primary action, or null. Keep one primary action per reviewed window.
- `action_start`, `action_accent`, `action_end`: each is null or an object with `time_seconds`, `uncertainty_seconds`, `confidence`, `evidence_frames`, `reason`. `action_accent` is the visual action emphasis; it is not a heard SFX peak. Use null for an unseen start/end rather than substituting the window boundary. Explain missing moments in `action_unknown_reason`.

Allowed categorical values:

| Field | Values |
| --- | --- |
| shot_scale | extreme_wide, wide, medium, close, extreme_close, changing |
| subject_position | upper_left, upper_center, upper_right, middle_left, center, middle_right, lower_left, lower_center, lower_right, changing |
| camera_motion | static, pan_left, pan_right, tilt_up, tilt_down, push_in, pull_out, track_left, track_right, roll_clockwise, roll_counterclockwise, mixed |
| subject_motion | static, left_to_right, right_to_left, up, down, toward_camera, away_from_camera, clockwise, counterclockwise, mixed |

Directions refer to the displayed image coordinate system, not compass directions. Motion assertions (including `static`) and `changing` need at least three consecutive samples, with gaps no greater than 0.251 seconds. This prevents sparse evidence substitution; it does not prove the judgment is correct. Judge the samples honestly and retain unknowns where movement cannot be disentangled.

Action timing needs at least two consecutive dense frames bracketing the estimate. `time_seconds ± uncertainty_seconds` must cover those frames. For example, observed frames at 3.067 and 3.200 seconds could support a candidate at 3.1335 ± 0.0665 seconds; they cannot justify a zero-uncertainty frame-exact claim. If the moment is absent or obscured, leave it null. Do not substitute confidence for temporal precision. Fast motion, low source fps or blur may remain unresolved.

```bash
uv run travel-director submit-shot-review --request <request.json> --observations <compact.json>
uv run travel-director inspect-shot-review --request <request.json>
```

Submission validates membership, ranges, evidence, timing brackets and source hashes, then expands an immutable `results/observations.json` and receipt. `shot_review_validated` means the contract and evidence checks passed; visual judgments remain session-authored candidates, not ground truth or final timeline acceptance. Result items contain `observation`, `material`, and `evidence`; evidence frame paths are relative to the request directory.

Identical requests reuse evidence without decoding. Identical submissions are idempotent. A differing submission cannot overwrite a saved review. For a revision, author a new selection reason identifying the revision/question; it creates a new request and preserves the old one. This first version's revision may decode the same bounded interval again; do not claim cross-request frame reuse. Source/upstream hash changes or missing/corrupted evidence fail explicitly rather than silently refreshing the same request.

## Continue editing

These commands are available from any existing project with its Scanner-only observations and run contract. They leave Runner stages unchanged. Before using a saved result, inspect it and read the relevant result items, their source ranges, motion claims and uncertainty. For a local 2–4-shot combination, use [shot-group.md](shot-group.md): the group builder consumes these observations and derives a bound EDL; the exporter revalidates the group and its fine-review evidence. Unknown action times stay unknown downstream. The session authors connections; the program does not invent them. Legacy unbound EDLs remain compatible without claiming this validation.

If only scene-level guidance is needed, continue from coarse observations without manufacturing temporal detail. Fine review is required by the Skill when it supplies precise source ranges or movement/action-based edit claims. Do not return to broad scanning or ask the user to label all footage.
