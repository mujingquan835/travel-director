# Independent People Validation Guide

This phase validates only `people_present` and a coarse people-count band. It does not relabel Scene, Shot Scale, Action, Objects, Quality, Material Role, or Editorial Role.

## Frozen cohort

- Candidate manifest: `people_validation_manifest.json`.
- Frozen manifest SHA-256: `b605ebdc86865814bf1d1b3fb9d5ca85926de1142bb6ad793c0d71cea56bfed7`.
- Seed: `20260828`.
- Count: 30 files selected from the full inventory after excluding every relative path in `test_manifest.json`.
- Selection inputs: metadata only—duration, orientation, resolution, capture day, and time band.
- Do not inspect model predictions before the Ground Truth file is complete and hashed.
- Do not replace files after annotation to improve class balance. Report insufficient class support as `insufficient_coverage`.

## Annotation unit

Watch the complete clip locally. Sparse frames may be used for navigation but cannot replace full-clip review because a person may appear briefly.

Record exactly:

- `people_present`: `true`, `false`, or `null` when unreadable.
- `people_count_band`:
  - `none`: no visible person anywhere in the clip;
  - `single`: maximum defensible visible count is 1;
  - `few`: maximum defensible visible count is 2–5;
  - `crowd`: maximum defensible visible count is 6 or more;
  - `null`: only when `people_present` is `null`.
- `visibility`: `clear`, `distant`, `partial`, `mixed`, or `unreadable`.
- `annotation_confidence`: 0–1 confidence in the label.
- `notes`: concise ambiguity evidence, not a model diagnosis.

Consistency rules are enforced by `PeopleValidationDataset`:

- `people_present=false` requires `people_count_band=none`.
- `people_present=true` requires `single`, `few`, or `crowd`.
- `people_present=null` requires `visibility=unreadable` and no count band.

## Freeze and evaluate

1. Annotate all 30 files without seeing Scanner predictions.
2. Re-review every item below 0.8 annotation confidence before freezing.
3. Save the candidate-manifest SHA-256 inside the Ground Truth dataset.
4. Validate schema, uniqueness, exact manifest membership, and the hash:

   ```bash
   uv run travel-scanner validate-people-ground-truth \
     --manifest benchmark/people_validation_manifest.json \
     --input benchmark/people_validation_ground_truth.json
   ```

5. Commit only the manifest, guide, and final labels; never commit video or private review frames.
6. Run the unchanged Scanner configuration once after the labels are frozen.

Decision thresholds remain evidence gates, not product guarantees:

- `people_present`: F1 at least 0.80, at least five positive and five negative labels, at least 90% scored coverage, and no clear systematic failure to qualify as `reliable`; otherwise `candidate`, `not_reliable_for_v0_1`, or `insufficient_coverage`.
- `people_count_band`: Macro F1 at least 0.80 with at least five labels per decision-critical class and no systematic undercount pattern. Missing class support is `insufficient_coverage`; do not merge or resample classes after seeing results.

This validation does not authorize Director, music/SFX, timeline, or export work.
