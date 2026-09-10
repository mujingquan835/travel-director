# Visual Observation Contract

This reference governs the invoking-agent batch JSON saved under `<project>/visual/agent_batches/results/`. The result must validate as `AgentBatchResult` and stay within the fields allowed by `director.agent_batches.AGENT_VISUAL_FIELDS`.

## Compact Input Format (Preferred)

Instead of hand-writing the full `AgentBatchResult` JSON (which contains repetitive hashes, paths, and evidence structures), use the compact input format and expand it with the local script. This eliminates ~85% of the output tokens.

### Compact JSON Structure

Write one JSON file per batch containing only visual judgments:

```json
{
  "items": [
    {
      "relative_path": "trip/clip-01.mov",
      "assertions": [
        {"field": "technical_usability", "value": "usable", "confidence": 0.85},
        {"field": "content_families", "value": ["culture_architecture"], "confidence": 0.84},
        {"field": "setting", "value": "outdoor_historic", "confidence": 0.8},
        {"field": "lighting", "value": "daylight", "confidence": 0.78},
        {"field": "people_presence", "value": "none", "confidence": 0.9},
        {"field": "people_count_band", "value": null, "status": "abstained"},
        {"field": "subject_candidates", "value": ["ancient_building"], "confidence": 0.72},
        {"field": "activity_candidates", "value": null, "status": "abstained"}
      ]
    }
  ]
}
```

Rules for compact assertions:
- Every assertion needs `field`. For candidates: `value` and `confidence`. For abstentions: `"status": "abstained"` (value/confidence are omitted or null).
- If `status` is omitted, it defaults to `"candidate"`.
- Cover every `required_fields` entry for every ready material, either as a candidate or an explicit abstention.
- `relative_path` must exactly match the manifest packet's `relative_path`.

### Expansion Command

From the resolved package root, expand the compact input into a full `AgentBatchResult`:

```bash
python3 <skill-root>/scripts/expand_observations.py \
    --manifest   <project>/visual/agent_batches/manifest.json \
    --scanner    <project>/visual/scanner_only.json \
    --batch-id   batch-000 \
    --input      /tmp/compact_batch_000.json \
    --output     <project>/visual/agent_batches/results/batch-000.json
```

The script reads the manifest for `material_id` and `contact_sheet_path`, the scanner observations for the full `MaterialRef`, computes contact-sheet SHA-256 locally, and assembles the strict `AgentBatchResult`. It warns on stderr when the abstention rate exceeds 40%.

After expansion, validate with the existing command:

```bash
uv run travel-director validate-agent-batch \
    --manifest <project>/visual/agent_batches/manifest.json \
    --result   <project>/visual/agent_batches/results/batch-000.json
```

### Quality Constraints

- Abstention rate above 40% per batch triggers a warning. If the contact sheets are not obviously degraded (dark, blurred, or empty), re-examine before accepting mass abstentions.
- Do not use abstention as a shortcut for difficult judgments. Only abstain when the contact sheet genuinely cannot support the field.
- The expansion script does not invent or alter any visual judgment; it only fills in the mechanical structure.

## Allowed Fields

Supported assertion fields:

- `technical_usability`
- `content_families`
- `setting`
- `lighting`
- `people_presence`
- `people_count_band`
- `subject_candidates`
- `activity_candidates`

Each candidate assertion must reference the batch contact sheet as `visual_provider` evidence, using the reserved material ID and the contact-sheet SHA-256. If a field cannot be supported from the contact sheet, abstain instead of guessing.

## Full Output Format (Expanded)

This is the final `AgentBatchResult` format produced by `expand_observations.py` and consumed by the Runner. Do not write this structure by hand; use the compact input format above.

```json
{
  "schema_version": "0.2.0",
  "batch_id": "batch-000",
  "provider": "invoking_agent",
  "status": "completed",
  "items": [
    {
      "schema_version": "0.2.0",
      "material": {
        "material_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "relative_path": "trip/clip-01.mov",
        "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "size_bytes": 1024,
        "mtime_ns": 123,
        "duration_seconds": 8.5,
        "fps": 25.0,
        "orientation": "portrait",
        "rotation": null
      },
      "provider": "invoking_agent",
      "observation_status": "automatic",
      "assertions": [
        {
          "field": "content_families",
          "value": ["culture_architecture"],
          "status": "candidate",
          "confidence": 0.84,
          "evidence_refs": [
            {
              "material_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
              "artifact_path": "/absolute/project/visual/agent_batches/contact_sheets/aaaaaaaaaaaaaaaa.jpg",
              "field_path": "contact_sheet",
              "frame_timestamp": null,
              "source_kind": "visual_provider",
              "status": "candidate",
              "confidence": 0.84,
              "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            }
          ]
        },
        {
          "field": "activity_candidates",
          "value": null,
          "status": "abstained",
          "confidence": null,
          "evidence_refs": []
        }
      ],
      "unknown_fields": [],
      "review_required_fields": [],
      "errors": []
    }
  ],
  "errors": []
}
```

## Unsupported Inference Rules

These restrictions govern this coarse eight-field batch only. Selected-shot source ranges and temporal observations use the separate [shot-review.md](shot-review.md) workflow, after local dense evidence has been prepared. Never add those fields to `AgentBatchResult` or infer them from its sparse contact sheet.

Unsupported inference is anything that is not directly supported by the contact sheet or carried forward from Scanner evidence.

Never add:

- `location`, landmark identity, or city-level claims
- `best_range`, `source_in`, `source_out`, recommended clip ranges, or edit timing
- soundtrack choices, catalog IDs, or generation outcomes
- face identity, named people, or personal attributes
- off-screen events, chronology, causes, or story conclusions not visible in the frames
- fields outside the allowed list above

Rules:

- Treat the action's `required_fields` as the required coverage for every ready material in that action. Use one candidate or abstained assertion per required field; do not silently omit a field.
- When `result_path` is under `results/supplements/`, preserve the earlier batch result unchanged. The supplement may repeat an identical assertion or add a missing field, but it must not revise an existing field.
- Materials without a contact sheet remain unavailable and are not fabricated into a batch result or delegated to the user for exhaustive confirmation.
- Do not repair freeform prose into JSON. If the output is malformed, rewrite once as structured JSON and validate.
- Do not mix `unknown` with a concrete value for the same supported field.
- Do not invent values from memory, from the user’s earlier wording, or from adjacent materials.
- If confidence is below the batch threshold, abstain on that field and add it to `review_required_fields`.
- Keep unsupported inference out of `unknown_fields`; `unknown_fields` is only for supported fields that remain unresolved.

The downstream prompt artifact must remain local-only and end with `external_call_count=0`.
