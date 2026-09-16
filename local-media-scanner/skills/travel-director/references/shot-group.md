# Local shot groups with verified paired evidence

Use for a local combination of **2–4 shots**, after [shot-review.md](shot-review.md) has saved the relevant temporal observations. This phase turns the invoking session's editorial choices into a source-bound EDL. It does not automatically select a story, judge aesthetics, rescan footage, change music or operate Jianying.

## Author the local combination

Read the relevant saved fine-review results, not the full library. Identify each shot's role and why its successor belongs there. Choose a source interval inside the fine review's proposed usable interval. A null usable range cannot become an edit. Two different intervals from the same reviewed source may be two shots; do not claim separate scenes or chronology without evidence.

Write a plan JSON. Times are original source seconds. `review_request` must be absolute. Do not copy or invent hashes: the builder resolves them.

```json
{
  "project_name": "Local context to detail",
  "canvas": {"width": 1920, "height": 1080, "fps": 30},
  "shots": [
    {"shot_id":"context", "review_request":"/absolute/review-a/request.json",
     "candidate_id":"shot-000", "source_in":4.8, "source_out":6.0,
     "function":"context", "reason":"Establish the road environment", "gain":1},
    {"shot_id":"detail", "review_request":"/absolute/review-b/request.json",
     "candidate_id":"shot-000", "source_in":2.935, "source_out":3.868,
     "function":"detail", "reason":"Move to the passing foreground vehicle", "gain":1}
  ],
  "connections": [
    {"left_shot_id":"context", "right_shot_id":"detail",
     "status":"intentional_cut", "relationship":"hard_cut",
     "reason":"A deliberate view change; continuous movement is not established",
     "left":{"field":"frames","evidence_frames":[8,9,10]},
     "right":{"field":"frames","evidence_frames":[0,1,2]}}
  ]
}
```

Example times and frame indices illustrate structure only; replace them with inspected evidence. `gain` is original clip audio amplitude (0 muted, 1 unity), defaults to 1, and must follow the user's sound policy. This step does not choose music or substitute SFX for source audio.

Shot functions: `opening`, `context`, `action`, `detail`, `reaction`, `contrast`, `release`, `ending`. Use only roles supported by the footage and intended local sequence. No mandatory mix of roles or cut frequency.

Connections must enumerate every adjacent pair once, in shot order. Each side names a fine-review field and local packet frame indices:

- `action_start`, `action_accent`, `action_end`: reuse the exact complete frame evidence list. The builder copies the saved time and uncertainty unchanged. An unknown moment remains unavailable.
- `camera_motion`, `subject_motion`: at least three consecutive dense frames from that judgment's evidence. For `motion_match`, both sides must cite the same field, have the same known direction, and not be `mixed`. This is a basic evidence check, not proof of perceptual continuity; explain the actual attention/movement connection.
- `shot_scale`, `subject_position`: cite known judgments and at least two consecutive dense boundary frames (three for `changing`). These support `visual_match`. Color/shape matching is not a structured fine-review field yet; do not invent those judgments. If it matters, retain `needs_review` and identify the missing evidence.
- `frames`: cite at least two consecutive dense boundary frames. This is allowed for content, contrast or an intentional hard cut; it cannot replace known motion/action fields to claim a supported motion/action match.

Statuses:

| Status | Meaning |
| --- | --- |
| supported | Session-authored connection with compatible evidence on both sides; still needs actual editorial review |
| intentional_cut | A reasoned plain hard cut or deliberate contrast; no seamless match claim |
| needs_review | Pair still unresolved; keep the plan, but no exportable EDL is produced |

Relationships: `motion_match`, `action_match`, `visual_match`, `content`, `contrast`, `hard_cut`. An action match requires known action moments on both sides; matching the meaning of two described actions is the session's responsibility. No sound-bridge claims here: the current fine review contains visual evidence only.

## Build and inspect

```bash
uv run travel-director build-shot-group --plan <absolute-plan.json> --output <new-group-directory>
uv run travel-director inspect-shot-group --group <returned-group.json>
```

Each shot must belong to the same project. The builder revalidates the source files, fine-review evidence, review receipts and candidate membership. The selected outgoing/incoming cut must lie inside its cited temporal evidence window. The program inherits the action uncertainty; for other fields, it preserves the interval covered by the cited dense samples. It translates both source windows into the local timeline without collapsing them into one fictitiously exact event. The chosen cut is an exact *editorial execution decision*, not an exact perceptual event measurement.

Outputs: immutable `group.json`, `receipt.json`, and, only when all connections are ready, `edit_decision.json`. The program computes contiguous timeline positions, duration and source references in the declared shot order; it does not snap boundaries to beats or secretly change durations. Frame-grid refinement, retiming and transitions remain separate future work. Review time uncertainty does not authorize exporting outside the reviewed usable range.

`shot_group_validated` is a program/evidence status, not aesthetic or client acceptance. `needs_connection_review` saves the unresolved plan and returns no decision path. Resolve missing evidence and use a new group output directory; never silently replace a failed match with a whoosh or call it verified.

## Export actually consumes the group

```bash
uv run travel-director export-fcpxml --decision <returned-edit_decision.json> --output <new-package-directory>
```

The generated EDL contains `shot_group: {path, sha256}`. Do not strip this binding. The exporter reopens the group, validates both reviews, and checks that video source paths, order, ranges, gains, timeline positions and canvas still match. It fails before package creation on stale/missing evidence, unresolved connections or video EDL drift. A changed picture edit requires a new group. Music/SFX segments and cues may be added through existing workflows while preserving the video decisions, binding and total duration.

The package includes `shot_group.json`; its receipt records the snapshot hash, pinned review hashes and both sides' time windows/uncertainties. `resolved_decision.json` retains the group binding. Packaged metadata preserves provenance, while revalidating the original evidence still requires the local source/review files; the snapshot is not a portable copy of every fine-review image.

Existing legacy decisions without a group remain supported, and their receipt has no group-validation claim. For new local combinations use the bound route. No global Runner stage change is required. FCPXML generation and actual Jianying import/play/edit/save acceptance remain separate, as described in [fcpxml-delivery.md](fcpxml-delivery.md).
