# Runtime Reference

Read this reference for confirmation, music import, or resume details. The runner owns internal stages, hashes, and strict artifacts. For `needs_creative_direction`, read [creative-direction.md](creative-direction.md).

## Run And Resume

Start from the package root returned by `scripts/resolve_workspace.py`:

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

On `completed`, report the generated `timeline_delivery` (JSON) and `timeline_markdown` (Markdown) paths. The delivery includes the beat-aligned slot grid, text placeholders, and audio packaging (Hook Riser+Hit, BGM ducking, and Outro SFX). On `blocked`, report the saved project and the exact blocker without producing prompts.
