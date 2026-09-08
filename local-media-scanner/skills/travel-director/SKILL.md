---
name: travel-director
description: Use when a user needs evidence-based creative direction for local travel footage, reference-film adaptation, audiovisual planning, or continuation with selected local music.
---

# Travel Director

Use `$travel-director` with two inputs: an absolute local footage directory and the user's natural-language creative brief.

The supported delivery mode is a fast placeholder timeline plan. Footage-filled previews, slow visual filling, and editable project exports are not yet connected to this Runner workflow.

Resolve the authoritative checkout with [scripts/resolve_workspace.py](scripts/resolve_workspace.py), work from the resolved package root, then call only:

```bash
uv run travel-director run --input <absolute-folder> --brief <description>
```

Reuse the returned `project_path` with `--project` on every later call. Read [references/workflow.md](references/workflow.md) for confirmation, music import, or resume details.

Handle the returned state:

- `needs_visual_observation`: read [references/visual-observation-contract.md](references/visual-observation-contract.md), inspect only the returned contact sheets, and write one valid batch to each `result_path`. Cover every returned `required_fields` entry for every ready material with either a supported candidate or an explicit abstention, then rerun. A path under `results/supplements/` is an immutable additive checkpoint: read the earlier batch result, add only the requested missing fields, and never change a prior assertion. Keep each batch at 10 materials or fewer and each material at 3 to 5 frames.
- `needs_user_confirmation`: ask only the returned fields. For `chat`, write the simple answer format from the workflow reference to `response_path`; for `local_page`, point the user to `page_path`, then import the downloaded JSON through `run --response-file <downloaded-json>`. Chat is limited to 5 fields across at most 3 materials.
- `needs_creative_direction`: read [references/creative-direction.md](references/creative-direction.md) and the returned request `result_path`. In this conversation, select reference methods using the current Brief and material evidence, show the audiovisual section table, then provide music requirements and exactly three prompts. Write the response against the returned schema and submit through `run --creative-response <response_path>`. This is session-authored planning, not another model service or a user approval gate.
- `waiting_for_music`: read the returned summary `result_path`. Present reference selections and the audiovisual table before the music brief and three prompts (each at most 200 characters); if already shown in this conversation, do not repeat the whole plan. Read `artifact_paths.music_recommendations` when returned. Show up to five local candidates with title, version, measured duration, reasons, and a clickable `version_path`; wait for the user to choose, then pass that exact path to `run --music`. Do not auto-select the first candidate. For no matches or an unavailable library, state the reason and retain the external music/upload route.
- Audio delivery: one file explicitly for editing is already selected; directly call `run --music <local-audio>` without another quality confirmation. Reference, analysis, failure-review, and rejected attachments are not formal music. When multiple editing tracks arrive without a choice, ask only which file to use. Rejected examples do not imply a universal ban on their instruments or genres.
- Music replacement: when the user requests a different track after freezing, use `run --project <old-project> --music <new-audio> --new-music-version` and retain the returned new `project_path`. The original version remains unchanged. Without this explicit replacement request, do not switch tracks.
- Same-music timeline revision: when requested, resume the completed parent with unchanged input/brief and `--new-timeline-revision`. This builds a separate project using its frozen observations, creative plan and music analysis. Read the workflow revision rules; keep the returned new `project_path` and report its lineage and receipt.
- `waiting_for_timeline`: report the frozen music and measured analysis paths returned by the Runner. The music is ready; generate beat grid timeline delivery using `run --input <folder> --brief <brief> --project <project_path> --build-timeline`.
- `completed`: link the returned timeline JSON (`timeline_delivery`) and Markdown walkthrough (`timeline_markdown`). Explicitly state that this is a verified timeline plan, footage slots remain placeholders, and a footage-filled preview and editable project have not been generated. Describe only audio packaging actually present in the delivery; a Hook/Outro plan does not mean audio has been mixed.
- `blocked`: report the reason and preserved `project_path`; do not guess, restart, or bypass validation.

Use `uv run travel-director status --project <project_path>` only to diagnose an ambiguous resume state.

Never declare or switch models, start another task, call a local inference model, call Codex API, upload media, or call any external or paid service. Scanner execution must remain `--no-models`; the result must report `external_call_count=0`. Preserve uncertainty and validate every saved observation or confirmation through the next `run` call.
