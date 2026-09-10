# Music phrase adaptation and immutable revisions

Use when fitting selected music to picture through phrases, pauses, turns and ending choices. This is a separate versioned artifact over **already selected frozen music** and an existing picture EDL. It leaves original music bytes, musical analysis, creative sections, shot reviews and prior EDLs unchanged. The invoking session authors musical decisions; local code validates provenance and materializes timing. No extra model/service or auto-selection of music.

## Evidence before claims

Read the existing music asset/analysis and the relevant picture plan. `automatic_hints` are isolated from phrase judgments: energy/position-based sections, every-fourth-beat markers and source-ending classifications remain **unconfirmed candidates**. BPM is neither edit frequency nor playback speed. Never describe unheard melody, instrumentation, cadence or phrases as confirmed.

Listen to the relevant original music ranges when the current interface provides actual audio understanding, or record the user's specific listening report. Merely playing audio without actually perceiving it, reading lyrics/metadata, or measuring waveforms is not listening evidence. If unavailable, retain `not_listened` and author a clearly labeled candidate proposal; technical trials may still export, but cannot be called listening-approved.

For recorded listening, include source interval, reviewer, method (`user_report` or `direct_listening`), substantive note and a timezone-aware timestamp. The program binds those records to the frozen music hash. It validates coverage and attribution fields, **not whether a human/model really heard it**. Never fabricate testimony. Source-range review is separate from hearing the edited mix; output `mix_listening_status` remains `not_reviewed` in this version.

## Author a plan

Create a JSON plan using `director.music_adaptation_schema.MusicAdaptationPlan` in the resolved package root. Required fields:

- `music_project`: absolute existing project with complete frozen `music_asset` and `music_structure` evidence. Do not pass a new audio file; track replacement still uses the existing `--new-music-version` workflow first.
- `base_decision`: absolute original picture EDL, preferably bound by [shot-group.md](shot-group.md). Its picture decisions remain unchanged; existing music clips are replaced by the explicit mapping. Existing source audio, SFX and cues remain. For revisions continue to refer to this original picture base, not a previously derived music EDL.
- `revision_reason`: specific purpose of this initial version or revision.
- `listening`: records as above, or `[]`.
- `phrases`: source intervals with `phrase_id`, `source_in`, `source_out`, `label`, `status` (`candidate`/`confirmed`), `basis` (`automatic_energy`/`editorial_proposal`/`listening`), optional `listening_id`, and `reason`. Confirmed requires a covering listening record and basis=listening. Automatic energy labels cannot become confirmed phrases.
- `mapping`: ordered complete project coverage, each segment having `segment_id`, `kind` (`music`/`silence`), `source_in/out`, `project_in/out`, optional `phrase_id`, linear `gain`, and `reason`.
- `events`: each has `event_id`, `kind` (`turn`/`pause`/`resume`/`accent`/`ending`), `project_time`, `segment_id`, `source_time`, `status` (`proposed`/`listened`), optional `listening_id` and `reason`.
- `ending`: `treatment` (`cut`/`source_end`/`silence`/`fade`), `reason`, optional covering `listening_id`.
- `pacing`: optional local picture response records described below; use `[]` for an unbound legacy EDL.

Music segments preserve original speed: source duration equals project duration. Source order may change or repeat for deliberate phrase restructuring. A segment with a phrase ID must lie inside that phrase's source interval. Reordering is a proposal until the join has actually been heard; this version exports explicit cuts, not automatically smoothed musical joins.

All project time must be accounted for. Use explicit `silence` segments for planned music pauses, with null source times/phrase ID, zero gain and a reason. This pauses the **music layer** only; it does not mute source audio or SFX. Never call it total silence unless the other sound layers also establish that.

For example, a 4-second technical plan could map source 10–11s to project 0–1s, music silence 1–1.5s, then source 20–22.5s to project 1.5–4s. These are schema examples, not prescribed music cuts or confirmed phrases. Events carry source-to-project mapping from the referenced segment; inserted pauses have no source time and cannot be labeled listened source events.

Ending choices are explicit:

| Treatment | Behavior |
| --- | --- |
| cut | End the selected excerpt as written; do not claim musical resolution |
| source_end | Last segment actually reaches the frozen source end; not itself evidence of a heard cadence |
| silence | Explicit final music-silence interval; source audio/SFX may remain |
| fade | Save the proposed ending, return `needs_audio_processing`, and produce no exportable EDL because gain envelopes are not implemented |

Do not apply the original song's ending label when the target stops in its middle. Never silently turn an unsupported fade into a hard cut.

## Picture response is not a beat-cut grid

For a bound local group, pacing entries contain `mode`, ordered `shot_ids`, optional `event_id`, optional `action_field`, and a concrete `reason`:

- `hold`: preserve the chosen shots across musical beats. No automatic cut is generated.
- `internal_action`: one shot, a music event and known fine-review `action_start`, `action_accent` or `action_end`. The action and music event must both be inside the selected shot. The program copies its source time, timeline time, temporal uncertainty and evidence indices, and reports whether the music event falls within that observation window. A mismatch stays explicit; the program does not silently move the shot or assert audiovisual synchrony.
- `local_fast_cut`: at least two contiguous group shots, with an editorial reason. It documents a selected local passage; it does not force the whole film to cut at the BPM or automatically speed up media. The session must inspect whether durations/readability actually support that description.

The existing picture group and its precise EDL do not move in this step. To propose a different group, create a separate validated group first and reference its EDL in an adaptation revision. The revision diff will show the changed base; original narrative boundaries and frozen versions stay unchanged. Do not rebuild coarse observations just to change music.

## Save a version and its differences

```bash
uv run travel-director build-music-adaptation --plan <absolute-plan.json> --output <new-version-directory>
uv run travel-director build-music-adaptation --plan <revised-plan.json> --parent <previous/adaptation.json> --output <new-revision-directory>
uv run travel-director inspect-music-adaptation --adaptation <returned-adaptation.json>
```

Outputs: immutable `adaptation.json`, receipt, parent path/hash and structured differences containing field path, before and after values. Identical retries reuse the saved version. Differing writes to the same directory fail. A parent revision must use the same frozen music project; replacing the song is a separate existing music-version flow. No historical project state is rewritten and no new top-level Runner status is introduced.

`music_adaptation_validated` means structural/evidence validation passed. `listening_status` is `not_listened`, `partial_source_review` or `source_ranges_reviewed` according to record coverage of used source intervals. None implies edited-mix approval. `needs_audio_processing` saves unsupported processing intent without claiming materialization.

## Export keeps the binding

```bash
uv run travel-director export-fcpxml --decision <returned-edit_decision.json> --output <new-package-directory>
```

The derived EDL carries `music_adaptation: {path, sha256}` and retains the picture group binding. Export rechecks frozen music, analysis, base EDL, parent revision and picture/music clip mapping before creating the package. Do not strip the binding or edit the music clips behind it; build a new adaptation revision instead. The package includes `music_adaptation.json`, with mapping, events, ending, listening state and revision differences in its receipt. Later SFX can be added using existing mechanisms without changing the bound picture/music decisions.

The snapshot records provenance; original local evidence remains required for revalidation. FCPXML generation is separate from Jianying compatibility checks and actual listening/viewing acceptance. Do not present a short mapping experiment as an accepted music choice or an improved full film.
