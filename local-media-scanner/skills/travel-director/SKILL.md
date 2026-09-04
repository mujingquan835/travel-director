---
name: travel-director
description: Use when a user wants to inspect a local travel-video folder from bounded contact sheets, turn a natural-language brief into an evidence-bound director plan, receive exactly three music-generation prompts, and pause for user-supplied music without external services.
---

# Travel Director

Use `$travel-director` with two inputs: an absolute local footage directory and the user's natural-language creative brief.

Resolve the authoritative checkout with [scripts/resolve_workspace.py](scripts/resolve_workspace.py), work from the resolved package root, then call only:

```bash
uv run travel-director run --input <absolute-folder> --brief <description>
```

Reuse the returned `project_path` with `--project` on every later call. Read [references/workflow.md](references/workflow.md) only for confirmation or resume details.

Handle the returned state:

- `needs_visual_observation`: read [references/visual-observation-contract.md](references/visual-observation-contract.md), inspect only the returned contact sheets, and write one valid batch to each `result_path`. Cover every returned `required_fields` entry for every ready material with either a supported candidate or an explicit abstention, then rerun. A path under `results/supplements/` is an immutable additive checkpoint: read the earlier batch result, add only the requested missing fields, and never change a prior assertion. Keep each batch at 10 materials or fewer and each material at 3 to 5 frames.
- `needs_user_confirmation`: ask only the returned fields. For `chat`, write the simple answer format from the workflow reference to `response_path`; for `local_page`, point the user to `page_path`, then import the downloaded JSON through `run --response-file <downloaded-json>`. Chat is limited to 5 fields across at most 3 materials.
- `waiting_for_music`: read the returned summary `result_path`, report the recommended duration and exactly three prompts of at most 200 characters, then tell the user to upload the generated music in the same conversation to continue. Stop here: this package does not accept or analyze music yet.
- `completed`: reserve this state for a future run that has actually created the requested editing draft. The current package must not claim it.
- `blocked`: report the reason and preserved `project_path`; do not guess, restart, or bypass validation.

Use `uv run travel-director status --project <project_path>` only to diagnose an ambiguous resume state.

Never declare or switch models, start another task, call a local inference model, call Codex API, upload media, or call any external or paid service. Scanner execution must remain `--no-models`; the result must report `external_call_count=0`. Preserve uncertainty and validate every saved observation or confirmation through the next `run` call.
