# Music-Driven Travel Montage Prototype

## Current implementation boundary

The completed offline foundation provides strict Director contracts, a conservative Scanner bridge, local duplicate/audio evidence, structured music-search briefs, an offline catalog provider, explainable three-direction ranking, a reference-safe music blueprint, and a fail-closed music-generation authorization boundary.

`director.catalog.quduoduo.parse_visible_results` is only a parser for normalized metadata captured from one currently visible result page. It does not open a browser, contain DOM selectors, bypass access controls, download preview audio, or perform background collection.

## Quduoduo live-smoke gate

Before any live smoke, show the exact `MusicSearchBrief` to the user and obtain explicit authorization to open one search-result page. The allowed capture fields are title, visible tags, BPM, duration, author or label, detail URL, and preview URL. Retain at most five candidates and display three directions.

Stop immediately on login requirements, CAPTCHA, WAF, or an unsupported page structure. The user may complete an access challenge manually; automation must not bypass it. Live capture artifacts belong below ignored `prototype/runs/<run-id>/catalog/` and must not contain cookies, credentials, raw DOM, or protected preview audio.

## External-service status

On 2026-08-30 the user authorized one Quduoduo visible-page smoke for the frozen 60-second search brief. The official product page identifies `https://agm.haifanwu.com/` as the catalog target, but both the in-app browser and connected Chrome timed out during navigation before any page content or result cards became available. The smoke is therefore `blocked/navigation_timeout`, with zero visible candidates, zero downloads, zero login/CAPTCHA/WAF interaction, and zero cost. Redacted local evidence is stored below ignored `prototype/runs/quduoduo-smoke-20260830/`.

On 2026-08-30 a read-only audit of the installed Dreamina CLI build `673dd28-dirty` used only `--version` and `--help`. Its help exposes image and video generators but no music or audio generation command, so `music_generation=false` and the adapter phase stopped as `unsupported_capability`. Login state and credit balance were not checked; no generation command ran, no authorization was requested, and call count and cost remain zero. Redacted evidence is stored below ignored `prototype/runs/dreamina-capability-20260830/`.

Offline fixture-based Director work may continue, but no real Quduoduo catalog value, Dreamina music generation, or end-to-end provider success may be claimed.

## Local music analysis

`travel-director analyze-music` accepts a local WAV, MP3, or M4A and measures decoded samples at 22.05 kHz. It records a source hash, BPM, beat and four-beat downbeat candidates, a normalized one-second energy curve, change-based sections with confidence, and ending behavior. Provider BPM or section metadata is not used as measured timing evidence.

The deterministic fixture generator at `prototype/fixtures/generate_synthetic_media.py` creates a 60-second 120 BPM click track with a 24–31 second low-energy interval and five colored local test videos. These fixtures contain no private source material and make no network or paid-service calls.

`director.timeline.build_timeline_slots` turns measured sections and beats into contiguous editorial budgets. Intermediate boundaries are snapped to measured beats, pacing targets vary by section role, and content/motion needs are recorded without selecting any source file. Unknown measured sections remain `unknown` and receive an explicit `continuity_fallback` need.

`director.clip_selector.place_clips` performs deterministic two-pass placement. Evidence-backed high-impact candidates are reserved for climax first; other slots use duration, raw motion, quality, candidate scene diversity, source-range availability, and duplicate-group constraints. Every placement retains score components and relaxed constraints. Failed materials are never selected, and people candidates do not create a `human_story` score.

`director.sfx.build_sfx_plan` runs only after clip placement and never generates media. It keeps or enhances locally evidenced location sound, may record a selective `generate_sfx` suggestion for a visually grounded event, and otherwise records silence. Adjacent visual events cannot both receive generation suggestions. Timeline event time is reconstructed by treating the ordered placement list as contiguous and accumulating selected clip durations.

`travel-director run-local` creates a resumable project with fixed evidence paths and atomic JSON writes. The brief, external-call ledger, local input manifest, and every completed stage artifact are hashed. Resume verifies hashes and schema versions before skipping work; brief, input, ledger, or completed-artifact drift raises `ProjectConflict`. The local command supports stages through `timeline` and cannot invoke an external provider.
