# Visual Observation Contract

This reference governs the invoking-agent batch JSON saved under `<project>/visual/agent_batches/results/`. The result must validate as `AgentBatchResult` and stay within the fields allowed by `director.agent_batches.AGENT_VISUAL_FIELDS`.

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

## Strict JSON Example

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

Unsupported inference is anything that is not directly supported by the contact sheet or carried forward from Scanner evidence.

Never add:

- `location`, landmark identity, or city-level claims
- `best_range`, `source_in`, `source_out`, recommended clip ranges, or edit timing
- soundtrack choices, catalog IDs, or generation outcomes
- face identity, named people, or personal attributes
- off-screen events, chronology, causes, or story conclusions not visible in the frames
- fields outside the allowed list above

Rules:

- Do not repair freeform prose into JSON. If the output is malformed, rewrite once as structured JSON and validate.
- Do not mix `unknown` with a concrete value for the same supported field.
- Do not invent values from memory, from the user’s earlier wording, or from adjacent materials.
- If confidence is below the batch threshold, abstain on that field and add it to `review_required_fields`.
- Keep unsupported inference out of `unknown_fields`; `unknown_fields` is only for supported fields that remain unresolved.

The downstream prompt artifact must remain local-only and end with `external_call_count=0`.
