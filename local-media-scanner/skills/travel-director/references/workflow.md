# Workflow Reference

Use this reference after loading `$travel-director`. Substitute resolved absolute paths from `scripts/resolve_workspace.py`. Do not synthesize missing JSON fields from memory. Every JSON file written by the agent must be validated immediately by the corresponding `travel-director` CLI before it becomes an input to the next step.

## Resolve And Resume

1. Resolve the workspace:

```bash
uv run python skills/travel-director/scripts/resolve_workspace.py --workspace <workspace>
```

2. Initialize or reopen the V0.2 visual project:

```bash
uv run travel-director init-visual-project --project-id <project-id> --raw-brief <raw-brief.json> --run-root <run-root>
uv run travel-director visual-status --project <project>
```

3. Reuse existing `scanner-v1/scanner_result.json` only if it already exists and still validates against the same project inputs. Otherwise run the Scanner path once. This path is local-only and must keep `--no-models`.

## Scanner Preparation

```bash
uv run travel-scanner inspect --input <source-directory> --output <project>/visual/scanner/input_manifest.json
uv run travel-scanner scan --manifest <project>/visual/scanner/input_manifest.json --run-id scanner-v1 --runs-dir <project>/visual/scanner/runs --sampling-profile adaptive5 --device auto --no-models
uv run travel-director build-scanner-observations --scanner-result <project>/visual/scanner/runs/scanner-v1/scanner_result.json --scanner-manifest <project>/visual/scanner/input_manifest.json --output <project>/visual/scanner_only.json
uv run travel-director build-frame-map --scanner-result <project>/visual/scanner/runs/scanner-v1/scanner_result.json --scanner-observations <project>/visual/scanner_only.json --scanner-run-dir <project>/visual/scanner/runs/scanner-v1 --output <project>/visual/material_frame_map.json
uv run travel-director prepare-agent-batches --frame-map <project>/visual/material_frame_map.json --output-dir <project>/visual/agent_batches
```

`MaterialFrameMap` uses `RepresentativeFrame(path,timestamp)`. Each material contributes three to five representative frames, and each reserved agent batch contains at most ten contact sheets.

## Invoking-Agent Batch Loop

Read only the contact sheets assigned to one batch. Write the response directly to the reserved result path in `<project>/visual/agent_batches/results/`.

- If the structured JSON is malformed, repair it once and revalidate.
- If vision is unavailable, do not invent assertions. Leave the batch absent and continue with Scanner-only evidence.
- The batch result must stay within the allowed field contract in `visual-observation-contract.md`.

Validate each saved batch result:

```bash
uv run travel-director validate-agent-batch --manifest <project>/visual/agent_batches/manifest.json --result <project>/visual/agent_batches/results/batch-000.json
```

After all available batches are validated, merge them into a draft artifact. `merge-agent-batches` requires `--project`, and the output must be strictly under `<project>/visual/drafts/`.

```bash
uv run travel-director merge-agent-batches --project <project> --scanner-observations <project>/visual/scanner_only.json --manifest <project>/visual/agent_batches/manifest.json --result-dir <project>/visual/agent_batches/results --output <project>/visual/drafts/clip_observations.merged.json
uv run travel-director record-visual-stage --project <project> --stage clip_observations --artifact <project>/visual/drafts/clip_observations.merged.json
```

If no agent batches are available, keep the Scanner artifact as the working observation set, mark the outcome `scanner_only + assisted`, and surface that status in the final response.

## Review Routing

Plan or prepare review from the canonical `clip_observations.json`:

```bash
uv run travel-director plan-review --observations <project>/visual/clip_observations.json --output <project>/visual/drafts/review_route.json
uv run travel-director prepare-visual-review --observations <project>/visual/clip_observations.json --frame-map <project>/visual/material_frame_map.json --output-dir <project>/visual/review
```

prepare-visual-review may return `none`, `chat`, or `local_page` and never opens the browser.

- `none`: proceed without asking for observation confirmation.
- `chat`: ask the questions from `review_route.json` in one conversation turn.
- `local_page`: only after this result, or if the user explicitly asks, point the user to the generated local review page and its expected `visual_confirmation.json`.

Thresholds:

- Stay in chat at or below 5 pending fields across at most 3 materials.
- If pending work exceeds either limit, route to `local_page`.

When the user supplies a visual confirmation file, validate and import it:

```bash
uv run travel-director validate-visual-confirmation --observations <project>/visual/clip_observations.json --confirmation <project>/visual/review/visual_confirmation.json
uv run travel-director import-visual-confirmation --observations <project>/visual/clip_observations.json --confirmation <project>/visual/review/visual_confirmation.json --output <project>/visual/drafts/clip_observations.assisted.json
uv run travel-director record-visual-stage --project <project> --stage clip_observations --artifact <project>/visual/drafts/clip_observations.assisted.json
```

If required visual confirmation is declined, stop with `blocked` and report the preserved Scanner and draft artifacts instead of guessing.

## Brief Normalization And Confirmation

Normalize the raw brief first:

```bash
uv run travel-director normalize-brief --brief <project>/brief.json --output <project>/visual/drafts/intent_brief.json
uv run travel-director record-visual-stage --project <project> --stage intent_brief --artifact <project>/visual/drafts/intent_brief.json
```

If the normalized brief has blocking conflicts or missing required fields, render the offline confirmation form and wait for the user’s `brief_confirmation.json`:

```bash
uv run travel-director render-brief-review --draft <project>/visual/intent_brief.json --output <project>/visual/review/brief_review.html
uv run travel-director confirm-brief --draft <project>/visual/intent_brief.json --confirmation <project>/visual/review/brief_confirmation.json --output <project>/visual/drafts/brief_confirmation.confirmed.json
uv run travel-director record-visual-stage --project <project> --stage brief_confirmation --artifact <project>/visual/drafts/brief_confirmation.confirmed.json
```

If the normalized brief is already complete and conflict-free, the agent may write a matching `brief_confirmation.json` with the required draft hash and immediately validate it with `confirm-brief` before recording the stage.

## Treatment, Director Review, And Prompts

Build the deterministic downstream artifacts from canonical inputs:

```bash
uv run travel-director build-director-treatment --observations <project>/visual/clip_observations.json --brief-confirmation <project>/visual/brief_confirmation.json --decisions-output <project>/visual/drafts/intent_decisions.json --coverage-output <project>/visual/drafts/project_coverage.json --output <project>/visual/drafts/director_treatment.json
uv run travel-director record-visual-stage --project <project> --stage intent_decisions --artifact <project>/visual/drafts/intent_decisions.json
uv run travel-director record-visual-stage --project <project> --stage project_coverage --artifact <project>/visual/drafts/project_coverage.json
uv run travel-director record-visual-stage --project <project> --stage director_treatment --artifact <project>/visual/drafts/director_treatment.json
```

For an automatic Director review, write a local `director_review.json` draft with:

- `schema_version: "0.2.0"`
- `treatment_sha256`: hash of the recorded treatment
- `status: "completed"`
- `mode: "automatic"`
- `overrides: []`
- `confirmed_at`: current ISO timestamp

Then validate and publish it:

```bash
uv run travel-director validate-director-review --treatment <project>/visual/director_treatment.json --review <project>/visual/drafts/director_review.json
uv run travel-director record-visual-stage --project <project> --stage director_review --artifact <project>/visual/drafts/director_review.json
```

If the user wants manual bucket overrides instead, render the page, wait for the exported file, then validate and publish it with the same `validate-director-review` and `record-visual-stage` commands.

Finally write the prompt batch:

```bash
uv run travel-director recommend-music-prompts --treatment <project>/visual/director_treatment.json --brief-confirmation <project>/visual/brief_confirmation.json --coverage <project>/visual/project_coverage.json --output <project>/visual/drafts/music_style_recommendations.json
uv run travel-director record-visual-stage --project <project> --stage music_style_recommendations --artifact <project>/visual/drafts/music_style_recommendations.json
```

The final artifact must contain exactly three music prompts, each at most 200 characters, and `external_call_count=0`.

## Final Response

There is no dedicated final-summary CLI in this checkout. The final summary is assembled in the current conversation from validated artifacts only.

Return one final response containing:

- project status and whether completion was `automatic`, `assisted`, or `blocked`
- the canonical artifact paths for `clip_observations.json`, `brief_confirmation.json`, `director_treatment.json`, and `music_style_recommendations.json`
- exactly three ready-to-copy music prompts
- any unresolved checkpoints that prevented completion

Do not automatically open the final report. Keep the response compact and evidence-bound.
