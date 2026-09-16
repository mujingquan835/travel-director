# Session-authored creative direction

On `needs_creative_direction`, read the action's `result_path`. It contains the confirmed Brief, `source_hashes`, reference metadata, upstream `artifact_paths`, exact `response_schema`, and `response_path`. Read the treatment, coverage, review and material observations at those paths. Inspect reference metadata first, shortlist by applicability, and open only the selected evidence; do not recursively read the reference/template corpus. The local program validates, saves and restores; the current Codex conversation authors the plan. No additional model/music service or listening UI is part of this flow.

## Reference selection and evidence

The packaged `director/references/defaults.json` is the four-film default library; the request carries its validated snapshot and hash. Each entry records source, allowed interval, observed visual methods, evidence locations and applicability. Case 2 is strictly **00:00–03:00**; no later content or alias may enter its conclusions. User instructions choose which relevant methods to use, not an automatic change of location, duration or aspect ratio.

Read the selected evidence images when their visual details matter. Select only supported observations inside the selected interval. Record `reference_id`, `start`, `end`, `observation_ids` and project-specific `fit_reason`. Distinguish **observed reference fact** from **creative proposal**. Unheard instrumentation, melody, voices and SFX remain unknown; subtitles, credited track names, waveform/BPM/loudness measurements do not prove listening. A user preference may override default selection (`brief_only` with reason, or evidence-backed `custom`); it does not manufacture new reference facts.

## Required conversational output, in order

1. Selected reference intervals, verified methods and reasons; note methods not applicable to this project's material/format.
2. An audiovisual section table with: planned time range, narrative task, available material IDs and gaps, visual organization, music changes, SFX space, title/subtitle. Sections continuously cover the confirmed target duration. These are planning boundaries, **not actual generated-music edit points**. When climax or ending material is missing, adapt the structure or name the gap; do not claim it exists.
3. A shared music brief followed by exactly three copyable prompts, each no more than 200 characters, with a reasoned variation toward the same objective. Derive pacing, density and instrumentation from this project, not travel-type genre presets. Express vocals according to user intent; leave unspecified intent as unspecified. Use positive musical descriptions; no mandatory disclaimer suffix and no assurance that any platform will accept a prompt.

## Submission

Write JSON to the returned `response_path`, following its exact schema. Top-level fields: `schema_version`, `kind`, unchanged `source_hashes`, confirmed duration/location/orientation, `user_preferences`, optional structured `audio_intent`, `reference_policy`, `custom_references`, `selected_references`, `sections`, `music_brief`, `vocals`, and three `music_prompts`. Each section may also contain structured `audio_intent`. Each prompt includes `direction_id`, `title`, `generation_prompt`, `fit_reason`, `variation`, and known `section_ids`.

Use `audio_intent` only for an attributable decision. Set `source` to `user_explicit` for a choice the user stated, or `creative_proposal` for a proposal authored in this plan, and include a concrete `reason`. Global fields can set `hook_policy`, `added_sfx_policy`, `original_sound_priority`, and `silence_priority`; section fields omit Hook. Leave the object at its default `not_recorded` state when no structured decision exists. Do not promote phrases in `sfx_plan`, `visual_plan`, the brief, or earlier prose into a mandatory policy. A required-silence policy cannot simultaneously preserve or foreground original sound in the same scope.

When choices overlap, user-explicit intent outranks creative proposals; within the same source level a section choice outranks a global choice. Keep creative section times unchanged. Music analysis may later report an aligned, near, mismatched, unavailable, or unanalyzed target-cut boundary, but it must not silently snap or rewrite these narrative boundaries.

When actual music calls for an editorial adaptation, use [music-adaptation.md](music-adaptation.md) to record source/project phrase mapping, listening provenance and explicit version differences. This creates a separate adaptation over a chosen picture EDL; it never overwrites the original creative section plan. A revised picture group must be created separately and cited as the new base. Automatic energy/position tags are candidate listening windows, not confirmed phrases or mandatory cuts.

Use only known non-rejected treatment material IDs. Missing footage belongs in `material_gaps`, not invented IDs. Empty SFX or packaging arrays mean no design is planned; explain intentional silence/no-title choices in the displayed table. No routine approval is needed before submitting:

```bash
uv run travel-director run --input <same-folder> --brief <same-description> --project <project_path> --creative-response <response_path>
```

Read the result. `waiting_for_music` means the validated plan was saved, not that music was generated or approved. Duplicate submissions reuse the existing revision; changed valid submissions append one until music is frozen. Do not overwrite old artifacts or submit stale hashes. On a changed reference library, use the newly returned request; on evidence corruption report the blocker.
