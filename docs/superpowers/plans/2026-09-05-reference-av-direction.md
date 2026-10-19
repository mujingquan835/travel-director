# Travel Director reference and AV direction implementation

Goal: implement the user-approved reference library -> audiovisual section plan -> three music prompts -> user-selected external music workflow in the current conversation.

Constraints: no external model/provider, music generation, audition UI, or timeline renderer. User-supplied final music is selected; reference/rejected/analysis uploads are not imported. Preserve existing frozen assets and old visual evidence. Bilibili reference only 0–180 seconds. Unknown auditory content is not a verified claim. Three prompts, each <=200 characters. Work in existing feature/local-media-scanner-v0.1 worktree, not main. No unrelated edits.

## Task 1: Reference library and creative schema

Own only director/creative_schema.py, director/references/defaults.json, tests/director/test_creative_schema.py. Main agent owns integration and storage. Do not spawn agents or commit.

Create Pydantic strict types (extra forbid, finite numbers) and validate_creative_direction(payload: dict, *, source_hashes: dict[str,str], brief: BriefConfirmation, treatment: DirectorTreatment, coverage: ProjectCoverage, material_ids: set[str]) -> CreativeDirection. Also load_reference_library() -> dict and reference_library_sha256() -> str. Library path relative to module and load as package data. Return model must expose target_duration_seconds, location, orientation, selected_references, sections, music_brief, music_prompts, user_preferences, source_hashes. Schema version 1.0.0, kind creative_direction.

CreativeDirection fields: source_hashes exact expected keys/hash values; target_duration_seconds numeric equal confirmed brief; location/orientation equal confirmed brief; user_preferences list[str]; reference_policy default_library/custom/brief_only; custom_references list of reference entries (optional); selected_references list of {reference_id,start,end,observation_ids:list[str],fit_reason}; sections list of {section_id,start,end,narrative_task,material_ids:list[str],material_gaps:list[str],visual_plan,music_change,sfx_plan:list[str],packaging:list[str],reference_ids:list[str],climax:bool=false}; music_brief nonblank str; vocals instrumental_only/instrumental_preferred/allowed/unspecified; music_prompts exactly3 objects {direction_id,title,generation_prompt,fit_reason,variation,section_ids:list[str]}. Strings nonblank where mandatory; allow sfx_plan/packaging empty means intentionally no SFX/title. Section material_ids may be empty only with explicit material_gaps. Strictly contiguous nonoverlapping sections from0 to target duration; tolerance1e-6. Reject unknown/rejected treatment material IDs and unselected reference IDs. Climax when missing coverage needs explicit section gap (do not infer semantic wording). Prompt ids/text unique <=200chars, each covers valid section_ids and nonblank rationale/variation. Explicit vocals from confirmed brief must be retained, null allows creative declared policy but not invented source evidence.

Library structure: {schema_version:1.0.0,references:[{reference_id,title,url,start,end,visual_verified:true,audio_listened:false,audio_notes,applicability,observations:[{observation_id,time,description,evidence_path}]}]}. Only observed visual facts; no inferred genre/voice. Reference selection bounds within entry, each cited observation belongs to entry and is within selected range. At least one observation required per selection. Custom refs cannot overwrite built-in IDs; same schema, meaningful evidence source, no pretending known library audio. reference_policy custom requires custom selections; brief_only permits zero refs and user_preferences explaining choice. User preferences coexist without forcing built-ins. Source hash reference_library participates; expected provided by main. Custom refs part of payload canonical version.

Reference IDs case1 (0–113.557), case2 (0–180), case3(0–113.3667), case4(0–64.36). Read actual four analysis reports under <checkout>/outputs/reference-review-20260905/caseN/analysis.md. Preserve useful timestamps, source URLs and evidence filenames, don't bundle downloaded media. Exact observation IDs your choice, report them. Read tests instructions and follow red/green; report actual test results and one valid sample JSON shape in your final response. Do not modify installed skill or other files.

## Task 2: Runner and versioned creative records

Main agent integrates needs_creative_direction and --creative-response before legacy automatic prompts. Store append-only creative revisions with source binding and standalone summaries; reuse identical response and verify hashes on resume. New flow does not rewrite legacy completed visual stages. Frozen legacy music bypasses new requirement. Local pure validation and current-session authored response only.

## Task 3: Music versions and Skill

Keep --music selected-only import semantics. Add explicit new-music-version switch for requested replacements, preserving parent via independent child project/version and using cached visual artifacts. Skill distinguishes reference/rejected files. Sync repo/install docs and default reference description.

## Task 4: Verification

Baseline and changed contracts, schema negatives, lifecycle resume, frozen legacy, rejected uploads policy, replacement versions, real Kaifeng isolated-copy acceptance (no rejected WAV imports), full regression and independent review. Stage context only after milestone, preserve original files. No push/merge.
