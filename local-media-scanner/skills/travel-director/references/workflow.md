# Runtime Reference

Read this reference for confirmation, music import, or resume details. The runner owns internal stages, hashes, and strict artifacts. For `needs_creative_direction`, read [creative-direction.md](creative-direction.md).

The runtime requires Python 3.12, uv, and FFmpeg/ffprobe on PATH. From the resolved package root, `uv sync --locked` installs runtime dependencies. Developers running the full test suite use `uv sync --locked --extra dev --extra vision`, then `uv run pytest -q` and `git diff --check`; these test dependencies do not enable model calls in the Skill workflow.

## Run And Resume

Start from the package root returned by `scripts/resolve_workspace.py`:

Workspace resolution uses this order: explicit `--workspace`, then `TRAVEL_DIRECTOR_WORKSPACE`, then the current Git checkout (or current directory outside Git). A configured value may name the package itself or a repository containing `local-media-scanner`. An invalid configured value fails immediately, including an empty value; it never falls back. A valid explicit argument overrides the environment.

If the current checkout has no valid package, discovery checks its registered Git worktrees and the resolver script's parent directories. One unique valid package is accepted; multiple candidates produce an ambiguity error listing their paths. Select the intended checkout explicitly instead of assuming a feature branch or main is preferred. There is no machine-specific default directory. An installed Skill invoked outside a project needs a configured workspace when no package can be discovered.

Before resuming across checkouts, verify the returned absolute package path and run `git -C <package-path> rev-parse HEAD` to identify its code revision (when Git-managed). Keep resolver stdout as the package path so callers can use it directly; failures are written to stderr with a nonzero exit code.

```bash
uv run travel-director run --input <absolute-folder> --brief <description>
```

After the first call, preserve the exact input and brief and reuse the returned project:

```bash
uv run travel-director run --input <absolute-folder> --brief <description> --project <project_path>
```

Use this only when the saved state and the last result disagree:

```bash
uv run travel-director status --project <project_path>
```

Do not call internal stage commands. The Scanner path remains local with `--no-models`, and every result must retain `external_call_count=0`.

## Chat Brief Response

When an action has `kind: confirm_brief` and `review_channel: chat`, ask only its `required_fields`. Write this small object to its `response_path`:

```json
{
  "kind": "brief",
  "answers": {
    "style": "纪实",
    "mood": "探索",
    "rhythm": "medium"
  }
}
```

Include every requested field and no unrequested field. The runner merges the answers with the normalized draft, adds the source hash, creates the strict confirmation artifact, and validates it.

If the user declines a required confirmation, write:

```json
{"kind": "brief", "status": "declined"}
```

The next run returns `blocked` and preserves the project.

## Chat Visual Response

When an action has `kind: confirm_visual_fields` and `review_channel: chat`, ask the fields in `review_questions`. Write one answer for every requested material and field to its `response_path`:

```json
{
  "kind": "visual",
  "answers": [
    {
      "material_id": "sha256:<material-id>",
      "field": "lighting",
      "value": "daylight"
    }
  ]
}
```

Values must follow [visual-observation-contract.md](visual-observation-contract.md). To preserve an explicit inability to decide, set `confirmed_status` to `abstained` and omit `value`. The runner copies the recorded original value and status, adds the observation hash and evidence reference, creates the strict confirmation at `confirmation_path`, and validates it.

If the user declines the required review, write:

```json
{"kind": "visual", "status": "declined"}
```

## Local Page

When `review_channel` is `local_page`, do not write the chat response format. Point the user to `page_path`. After the page downloads its strict Brief or visual confirmation JSON, import that downloaded file through the same project run:

```bash
uv run travel-director run --input <absolute-folder> --brief <description> --project <project_path> --response-file <downloaded-json>
```

The runner validates the response kind and source hashes before atomically recording it at `confirmation_path`. A wrong hash, wrong kind, or duplicate import returns `blocked` without changing the project. Do not open the page unless the user requests it or the returned route requires the page.

## Waiting For Music

The Runner also returns `artifact_paths.music_recommendations`, a refreshable recommendation document. Read its `status`, `recommendations`, and any `reason`. For `ready`, present up to five candidates with title, `selected_version`, `version_duration_seconds`, `match_reasons`, and a clickable absolute `version_path`. Ask the user to select a candidate; fewer than three eligible tracks is valid and must not be padded with unrelated or too-short music. Recommendations use keyword/category matching, not listening-based quality judgments.

Once the user selects one, use its exact `version_path` with the existing `--music` command below. Never bind a candidate merely because it ranks first. Reuse the same project and input/Brief. A user-provided alternative remains valid. A `no_matches` or `unavailable` response does not block external music or local file upload; explain the reason and retain the three prompts.

The library index is cached outside the source library. File additions, deletions, renames, or size/timestamp changes refresh the index on the next recommendation run. Only versions at least as long as the target and at most 600 seconds are recommended. Cached indexing is not audio freezing; the existing importer validates and hashes the selected source again.

On `waiting_for_music`, read the `provide_music` action's `result_path`. Report the recorded plan in this order: reference selections and reasons, audiovisual section table, music requirements and three prompts. Keep the confirmed duration, location and orientation. If these were already shown, report only the saved result and next step. The user selects or generates music externally. A single file delivered for editing is already selected: resume with unchanged input and Brief, without asking whether its quality is approved:

```bash
uv run travel-director run --input <absolute-folder> --brief <description> --project <project_path> --music <local-audio>
```

The Runner accepts WAV, MP3, or M4A, verifies the creative checkpoint, hashes the source, copies it atomically without changing the original, and analyzes the frozen copy. Repeating the same file reuses the asset and analysis; if analysis failed after freezing, the same `--music` retries analysis without replacing the frozen bytes. A different file, drifted artifact, invalid audio, or simultaneous confirmation/creative response import returns `blocked`.

Do not call `--music` for reference, analysis, failure-review, or rejected audio. If multiple files are delivered for editing without a choice, ask only which file should be used. Do not infer genre or instrument dislikes from a rejected track. If delivery purpose itself is unclear, clarify that purpose before importing.

For an explicitly requested replacement of already-frozen music:

```bash
uv run travel-director run --input <absolute-folder> --brief <description> --project <old-project> --music <new-audio> --new-music-version
```

This returns an independent new project path with reused visual evidence and new frozen music. Continue from that path; retain the parent. Retrying the same replacement against the same parent reuses the version. It is not an overwrite flag.

Unfrozen legacy projects reuse existing analysis and request a new creative plan; they do not rescan or overwrite historical summaries. Valid new submissions append creative revisions. Stale submissions are rejected; rerun to obtain the current request and author from its current source hashes. Corrupt records block rather than being silently regenerated. All already-frozen projects, whether legacy or using creative revisions, resume their existing contract even after reference-library updates, without replanning or reselection.

On `waiting_for_timeline`, report the returned `music_asset`, `frozen_music`, and `music_structure` paths. The measured structure contains the actual BPM, beats, downbeats, energy curve, section candidates, ending behavior, confidence, and source hash. To generate the beat grid timeline delivery:

```bash
uv run travel-director run --input <absolute-folder> --brief <description> --project <project_path> --build-timeline
```

On `completed`, link the returned `timeline_delivery` (JSON) and `timeline_markdown` (Markdown) paths. State that the fast timeline plan is verified, footage slots remain placeholders, and no footage-filled preview or editable project has been generated. Report Hook Riser+Hit, BGM ducking, and Outro only when present in the saved plan; these are mixing instructions, not rendered audio. Include a recorded omission reason when available; a null plan without a reason must not be described as an intentional creative choice. On `blocked`, report the saved project and the exact blocker without producing prompts.

Fast placeholder planning is the only delivery mode connected to this workflow. Slow visual filling, footage preview, and editable project export remain future integrations. Do not route a request for these outputs to internal prototype commands or present a plan as their completed result.


Timeline completion verifies both JSON and Markdown against a recorded delivery receipt. Missing or changed files, an interrupted receipt write, or a legacy delivery without a receipt returns `blocked`; report the reason and preserve the existing files rather than treating a saved completion key as sufficient. When the target ends before the measured music ends, Outro timing uses the target duration and automatic ending-based SFX selection is deferred because the cut point has not been analyzed. `completed` describes the placeholder timeline plan, not a rendered or mixed video.
