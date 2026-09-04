# Runtime Reference

Read this reference only when `run` requests confirmation or an existing project has an ambiguous resume state. The runner owns all internal stages, hashes, and strict confirmation artifacts.

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

On `waiting_for_music`, read the `provide_music` action's `result_path`. Use only its recorded recommended duration, counts, gaps, artifact paths, and exactly three music prompts. Ask the user to upload the generated music in the same conversation. After the upload is available as a local file, resume the exact project with unchanged input and Brief:

```bash
uv run travel-director run --input <absolute-folder> --brief <description> --project <project_path> --music <local-audio>
```

The Runner accepts WAV, MP3, or M4A, verifies that the visual project is waiting for music, hashes the source, copies it atomically into the project without changing the original, and analyzes only the frozen copy. The first accepted music file is immutable. Repeating the same file reuses the recorded asset and analysis; a different file, drifted artifact, invalid audio, or simultaneous `--response-file` import returns `blocked`.

On `waiting_for_timeline`, report the returned `music_asset`, `frozen_music`, and `music_structure` paths. The measured structure contains the actual BPM, beats, downbeats, energy curve, section candidates, ending behavior, confidence, and source hash. Stop there: this package does not create timeline slots or an editing draft.

`completed` is reserved for a future package that actually creates the requested editing draft. Do not recalculate summary values, introduce provider results, or claim completion early. On `blocked`, report the saved project and the exact blocker without producing prompts.
