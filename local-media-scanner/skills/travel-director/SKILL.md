---
name: travel-director
description: Use when a user wants to inspect a local travel-video folder, understand its footage from bounded contact sheets, turn the user's description into an evidence-bound director treatment, and return three ready-to-copy music-generation prompts without calling external music or generation services.
---

# Travel Director

Use the current invoking agent's existing visual capability. Do not declare or switch models, create another task, call Codex API, upload source media, or call any external or paid music/generation service.

Use `$travel-director` for the local V0.2 visual path in this repository. The runtime copy is installed from this folder with [scripts/install.py](scripts/install.py). Resolve the authoritative checkout first with [scripts/resolve_workspace.py](scripts/resolve_workspace.py). Keep the entrypoint compact here and read [references/workflow.md](references/workflow.md) for the exact CLI sequence and stop states, plus [references/visual-observation-contract.md](references/visual-observation-contract.md) for the strict allowed-field JSON contract and unsupported inference rules.

Core constraints:

- 不得调用 Codex API，不得调用外部或付费音乐/生成服务，不得切换到别的任务。
- All saved JSON must be validated immediately by the owning CLI before the workflow advances.
- `merge-agent-batches` now requires `--project`, draft outputs must stay under `visual/drafts/`, and only `record-visual-stage` publishes canonical stage artifacts.
- Invoking-agent visual passes are bounded: 每批最多 10 条素材 contact sheets, each material uses 3 to 5 frames, and the Scanner path here always uses `--no-models`.
- The final music prompt artifact must contain exactly three prompts, each at most 200 characters, with `external_call_count=0`.
- `prepare-visual-review` may return `none`, `chat`, or `local_page`; it never opens the browser.
- Route review in chat only when pending work does not exceed the approved threshold. If 超过 5 个字段 or 超过 3 条素材, route to `local_page`.

Decision sequence:

1. Resolve and validate the authoritative workspace, inspect project state, and resume only verified artifacts.
2. Get the source directory and the user's natural-language description; stop before scanning if either is absent.
3. Run local Scanner preparation and build one 3 to 5 frame contact sheet per material.
4. Read at most 10 contact sheets per batch, write `AgentBatchResult` JSON to its reserved result path, validate immediately, and retry malformed structured output at most once.
5. If vision is unavailable, skip agent assertions, retain Scanner evidence, set `scanner_only + assisted`, and continue to review routing.
6. Normalize the Brief and ask only about blocking conflicts.
7. Merge observations and route review as `none`, `chat`, or `local_page` according to the approved thresholds. Open a page only after `local_page` is returned or the user explicitly asks.
8. Import confirmation JSON with hash validation. If the user declines required confirmation, finish `blocked` and report the preserved checkpoints.
9. Build intent decisions, project coverage, DirectorTreatment, DirectorReview, and exactly three music prompts of at most 200 characters each.
10. Return compact results and clickable artifact paths in the current conversation; do not automatically open the final report.
