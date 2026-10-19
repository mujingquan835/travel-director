# Music edit-region versions

Regions versions are draft / confirmed / history **inside one project**. They are not `music_version` child projects.

`director.music_version.create_music_version` forks a project onto a **new track** (`<project>-music-<sha16>`). A regions version stays on the frozen track already in the project. Another track belongs in a child project. `create_music_version` does not copy `music_edit_regions_versions/` and strips that store's hash keys from the child so an old lock is not inherited.

## Layout

```
<project>/
  music_edit_regions.json                  # analyzer candidates (existing mutable sibling)
  music_edit_regions_versions/
    index.json                             # music_edit_regions_versions_index
    draft.json                             # music_edit_regions_version_draft (at most one)
    confirmed/regions-vNN.json             # music_edit_regions_version:regions-vNN (write-once)
    receipts/regions-receipt-NN.json       # music_edit_regions_receipt:regions-receipt-NN (write-once)
```

`project_state.json` → `completed_artifact_hashes` records every file above. Confirmed snapshots and receipts follow the stage-artifact rule: a different payload is refused. Draft and index follow `record_supporting_artifact` and may be replaced while the recorded hash still matches the file. The analyzer key `music_edit_regions` is separate and is not a version-store key.

Listing fields are `status` (`draft` / `confirmed` / `history`), `source_music_sha8`, and `confirmed_at` (set for confirmed and history). History is the older confirmed files, still immutable. There is no unlock.

## Re-analysis and export

`stage_regions_reanalysis` replaces an open draft, or opens a new draft when the latest snapshot is confirmed. It does not rewrite `confirmed/`. After this directory exists, `build_project_music_edit_regions` applies that rule once it has refreshed `music_edit_regions.json`.

`require_confirmed_regions_version(project, version_id)` is the export gate. A missing id, `latest`, or a draft is refused — never a silent fallback. `export_fcpxml_for_confirmed_regions` is the Slice 1 hook only; it does not build an FCPXML decision or write `project.fcpxml`.

Receipt actions: `draft_save`, `confirm` (force-confirm sets `override` and a non-empty `reason`), `rerun`, `export`. Re-run and export writers record the receipt. They are not a job machine or an export UI.
