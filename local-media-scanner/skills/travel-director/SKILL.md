---
name: travel-director
description: Use for evidence-based travel-footage direction, music-led timeline planning, local music replacement, or validated FCPXML delivery for Jianying.
---

# Travel Director

Use `$travel-director` with two inputs: an absolute local footage directory and the user's natural-language creative brief.

The analysis flow produces evidence-backed creative and audiovisual plans. After a concise edit decision exists, the delivery flow can materialize its time ranges, tracks, gains, media references and JSON/FCPXML structure with local code. The model supplies decisions; it does not assemble a timeline by operating Jianying.

Resolve the authoritative checkout with [scripts/resolve_workspace.py](scripts/resolve_workspace.py) and work from the resolved package root. Start or resume the analysis flow with:

The installed resolver uses its installation receipt and verifies runtime source hashes before returning a path, even from another checkout. On missing or changed runtime evidence, stop before scanning and validate/reinstall the intended release; do not substitute the current directory.

```bash
uv run travel-director run --input <absolute-folder> --brief <description>
```

Reuse the returned `project_path` with `--project` on every later call. Read [references/workflow.md](references/workflow.md) for confirmation, music import, or resume details.

## Fine-cut sidecars and FCPXML delivery

These steps are **not** automatic main-path clip selection. Use them only when a concise edit decision (or short candidate set) already exists. Statuses such as `needs_shot_observation` / `shot_review_validated` / `shot_group_validated` are sidecar evidence states, not Runner stage transitions.

When the user requests an editable Jianying handoff and a concise edit decision is ready, read [references/fcpxml-delivery.md](references/fcpxml-delivery.md). Use `travel-director export-fcpxml` for generation and `travel-director record-fcpxml-acceptance` only after the client checks. Keep `fcpxml_generated` separate from `fcpxml_client_accepted`; generation alone is never a client acceptance claim.

Before assigning precise source ranges, action moments or movement-based connections to selected shots, read [references/shot-review.md](references/shot-review.md). Use `travel-director prepare-shot-review` on explicit short candidate intervals, inspect its dense timestamped evidence, then `travel-director submit-shot-review` with compact judgments. Use `travel-director inspect-shot-review` to validate saved evidence before reuse. This is an independent local temporal-review sidecar after coarse selection, not a replacement for the eight-field coarse contract or a new full-library scan. `needs_shot_observation` and `shot_review_validated` are this sidecar's statuses, not Runner stage transitions. Resume the existing project unchanged after saving the sidecar; cite its validated result when authoring precise edit decisions. Never infer continuous motion or frame-accurate actions from coarse sheets. When dense samples still cannot resolve an action, retain an explicit unknown and timing uncertainty.

## Main Runner status loop

Handle the returned state:

For music phrase fitting or revisions, read [references/music-adaptation.md](references/music-adaptation.md). Use `travel-director build-music-adaptation` over selected frozen music and an existing picture EDL; use `--parent` plus a new output directory for revisions and `travel-director inspect-music-adaptation` before reuse. Preserve source/project mapping, explicit music pauses, turns, ending treatment and attributable listening records. Automatic energy sections/downbeat candidates never become confirmed phrases without listening evidence. Picture motion may respond inside a held shot; BPM never requires one cut per beat. Export the returned bound EDL through the existing FCPXML command. Do not alter frozen creative history; `needs_audio_processing` is a saved unsupported-processing proposal, not a finished fade or mix.

For energy-based music edit-region candidates (edit roles, shot-length budgets and snap policy per region, bound to the frozen music hash), read [references/music-edit-regions.md](references/music-edit-regions.md). They are unconfirmed candidates, never listening evidence; rerun them after a music version change.

For a selected local combination of 2–4 shots, read [references/shot-group.md](references/shot-group.md). Author shot functions and every adjacent connection using paired fine-review evidence, then use `travel-director build-shot-group` and `travel-director inspect-shot-group`. Preserve inherited time uncertainty and unknowns. Export the generated bound edit decision with the existing FCPXML command; the exporter now revalidates fine-review evidence and video EDL identity through its `shot_group` binding. `needs_connection_review` cannot be exported; `shot_group_validated` is evidence validation, not a claim of pleasing continuity. This local step leaves Runner stages and the coarse observation contract unchanged.

For evidence-backed sound event design, read [references/sound-design.md](references/sound-design.md). Use `travel-director build-sound-design` over a base decision, mapping visual events to acoustic pre-roll anchors, assigning layer roles (location ambient, action foley, transition accent) and auditory depth planes. Use `--parent` plus a new directory for revisions and `travel-director inspect-sound-design` before reuse. Rejects late-arriving accents caused by naive file-start alignment and forbids claiming external library files as location recordings. Export the derived bound decision through `export-fcpxml`, which revalidates the `sound_design` binding, snapshots `sound_design.json` into the package, and records cues, planes and listening provenance in the receipt.

For aesthetic closure after client-compatible delivery, read [references/audiovisual-review.md](references/audiovisual-review.md). Verification strictly separates program checks, NLE client compatibility, and human subjective review. Execute the three-step review protocol (silent picture, blind audio, combined) and compare localized 15–20s A/B/C/D variants **only when real listening/viewing is performed**. Use `travel-director record-audiovisual-review` to record structured appraisal into the delivery `receipt.json` (this is what may update `mix_listening_status`). Use `travel-director inspect-audiovisual-review` to verify recorded evidence. Code tests, FCPXML generation, and NLE import success never equal aesthetic approval; do not cite repo validation samples as completed subjective review.


- `needs_visual_observation`: read [references/visual-observation-contract.md](references/visual-observation-contract.md). For each returned action, inspect only the returned contact sheets and write compact visual judgments (field, value, confidence only) to a temporary JSON file. Then expand it into a full `AgentBatchResult` using the local script and validate:

  ```bash
  python3 <skill-root>/scripts/expand_observations.py \
      --manifest   <project>/visual/agent_batches/manifest.json \
      --scanner    <project>/visual/scanner_only.json \
      --batch-id   <batch-id> \
      --input      <compact-json-path> \
      --output     <result_path>
  uv run travel-director validate-agent-batch \
      --manifest <project>/visual/agent_batches/manifest.json \
      --result   <result_path>
  ```

  Cover every returned `required_fields` entry for every ready material with either a supported candidate or an explicit abstention. After writing each batch result, immediately rerun `travel-director run` to continue to the next pending batch. Process all pending batches consecutively without stopping between batches for user confirmation. A path under `results/supplements/` is an immutable additive checkpoint: read the earlier batch result, add only the requested missing fields, and never change a prior assertion. Keep each batch at 10 materials or fewer and each material at 3 to 5 frames.
- `needs_user_confirmation`: ask only the returned fields. For `chat`, write the simple answer format from the workflow reference to `response_path`; for `local_page`, point the user to `page_path`, then import the downloaded JSON through `run --response-file <downloaded-json>`. Chat is limited to 5 fields across at most 3 materials.
- `needs_creative_direction`: read [references/creative-direction.md](references/creative-direction.md) and the returned request `result_path`. Inspect reference/template metadata first and open only evidence for the selected candidates; never load a template directory or reference corpus recursively. In this conversation, select reference methods using the current Brief and material evidence, show the audiovisual section table, then provide music requirements and exactly three prompts. Write the response against the returned schema and submit through `run --creative-response <response_path>`. This is session-authored planning, not another model service or a user approval gate.
- `waiting_for_music`: read the returned summary `result_path`. Present reference selections and the audiovisual table before the music brief and three prompts (each at most 200 characters); if already shown in this conversation, do not repeat the whole plan. Read `artifact_paths.music_recommendations` when returned. Show up to five local candidates with title, version, measured duration, reasons, and a clickable `version_path`; wait for the user to choose, then pass that exact path to `run --music`. Do not auto-select the first candidate. For no matches or an unavailable library, state the reason and retain the external music/upload route.
- Audio delivery: one file explicitly for editing is already selected; directly call `run --music <local-audio>` without another quality confirmation. Reference, analysis, failure-review, and rejected attachments are not formal music. When multiple editing tracks arrive without a choice, ask only which file to use. Rejected examples do not imply a universal ban on their instruments or genres.
- Music replacement: when the user requests a different track after freezing, use `run --project <old-project> --music <new-audio> --new-music-version` and retain the returned new `project_path`. This reuses the parent's frozen visual observations and creative evidence; recompute only the new music asset/analysis and downstream timeline/delivery. Do not rescan frames or repeat visual understanding unless the footage inventory, source hashes, Brief, or observation artifacts changed or failed validation. The original version remains unchanged. Without this explicit replacement request, do not switch tracks.
- Same-music timeline revision: when requested, resume the completed parent with unchanged input/brief and `--new-timeline-revision`. This builds a separate project using its frozen observations, creative plan and music analysis. Read the workflow revision rules; keep the returned new `project_path` and report its lineage and receipt.
- `waiting_for_timeline`: report the frozen music and measured analysis paths returned by the Runner. The music is ready; generate the text music/picture guidance using `run --input <folder> --brief <brief> --project <project_path> --build-guide`. The older `--build-timeline` produces only the underlying reference grid.
- Music/picture and audio-packaging guidance: use `--build-guide` with unchanged input/brief and the existing project. Explain where pictures could change, where to hold and where to try local fast cuts, using measured music evidence separately from creative suggestions. For each audio layer, state its function, timing, visual-event condition and whether a verified frozen candidate exists. Layer count is conditional and may be zero; do not prescribe stacked effects without a concrete picture anchor. Record explicit Hook disable, original-sound priority and silence priority in structured `audio_intent`; user-explicit choices outrank creative proposals, and section choices outrank global choices at the same provenance level. Never infer these policies from free prose. Creative section boundaries remain the narrative plan; music boundaries provide listening windows and never auto-move a section. Beat markers are optional references, never mandatory cuts. Keep unknowns and material gaps visible. Retired `--place-footage` and `--build-preview` are blocked; never bypass them with prototype render commands.
- `completed`: link `music_visual_guide_markdown`, `music_visual_guide` and `guidance_receipt`. For the underlying planning timeline, only Runner artifacts under `delivery/` with a validated `receipt.json` and recorded project hashes are formal planning delivery. Never present `validation/` exports as completed output or use the internal validation exporter to replace Runner delivery. The timeline JSON/Markdown is a reference grid, not an edit decision list. A separate concise decision may be exported through the FCPXML delivery flow; report its generation and Jianying acceptance statuses separately. State that unmaterialized picture and audio-packaging suggestions need listening/editorial review. A source timeline `ready` audio status means candidate instructions exist; the guide must still mark them as needing visual and listening review. When the target ends before the source music, do not apply the source ending behavior to the target cut. Historical R06 MP4s and placements were rejected as outside scope; do not present them as accepted deliveries or current capabilities.
- `blocked`: report the reason and preserved `project_path`; do not guess, restart, or bypass validation.

Use `uv run travel-director status --project <project_path>` only to diagnose an ambiguous resume state.

Never declare or switch models, start another task, call a local inference model, call Codex API, upload media, or call any external or paid service. Scanner execution must remain `--no-models`; the result must report `external_call_count=0`. Preserve uncertainty and validate every saved observation or confirmation through the next `run` call.
