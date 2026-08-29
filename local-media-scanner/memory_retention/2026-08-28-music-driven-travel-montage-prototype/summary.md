# Music-Driven Travel Montage Prototype Retention Summary

Date: 2026-08-30 (Asia/Shanghai)  
Branch: `feature/local-media-scanner-v0.1`  
Decision: `continue-with-constraints`

## Reusable implementation commits

- `053e058` Director contracts and CLI skeleton
- `7ddb200` Scanner evidence bridge and local enrichment
- `fdfa989` auditable music search brief
- `40d947e` offline catalog provider and ranking
- `13f1c98` bounded visible-page parser
- `a69d51c` reference-safe music blueprint
- `b1dce96` Dreamina capability and authorization gate
- `e40aeff` local measured music analysis
- `f1faf58` beat-aligned timeline
- `3843a7b` constrained clip placement
- `40b5765` non-generative SFX plan
- `14a52c9` resumable project orchestration
- `611fb62` bounded local FFmpeg rendering
- `f966d27` shortage-degradation repair used by acceptance rerun

## Verification commands and results

- `uv run pytest -q`: 137 passed after the accepted repair; three upstream `audioread` deprecation warnings.
- `uv run travel-scanner validate-ground-truth --input benchmark/ground_truth.json`: `valid: 30 items`.
- Scanner acceptance used `travel-scanner scan ... --device cpu --no-models`: 5 synthetic videos, 60 seconds, about 9.1 seconds.
- `travel-director run-local ... --stop-after timeline`: completed in about 2.7 seconds for the accepted rerun.
- `travel-director render-project ...`: verified 60.000-second 720×1280 H.264/AAC output in about 1.4 seconds.
- `git diff --check`: clean before acceptance documentation.

## Authoritative evidence paths

- Design: `docs/superpowers/specs/2026-08-28-music-driven-travel-montage-prototype-design.md`
- Plan: `docs/superpowers/plans/2026-08-28-music-driven-travel-montage-prototype.md`
- Acceptance conclusion: `prototype/ACCEPTANCE.md`
- Blocked Quduoduo smoke: ignored `prototype/runs/quduoduo-smoke-20260830/`
- Dreamina read-only audit: ignored `prototype/runs/dreamina-capability-20260830/`
- First partial acceptance: ignored `prototype/runs/acceptance-20260830/director/montage-v1/`
- Accepted single rerun: ignored `prototype/runs/acceptance-20260830-rerun1/director/montage-v1/`
- Accepted render: ignored `prototype/runs/acceptance-20260830-rerun1/director/montage-v1/render/montage.mp4`

## Key accepted hashes

- Scanner result: `e68993888ab9612bf7a1b1ad824af80af9848a2d73b58f2e0e7a5d454e460a64`
- Brief: `0e6a92623b6100757697615c3f41d3064a1e67e88471250a4643f999fbda8f5a`
- Search brief: `54ba602da4a73de2c572ea2af0743bdec91fda08c5fce32101b9954e8e81d90c`
- Selected direction metadata: `c411ba5a345bbccfa8bfaa8dab528b8d11a89ea38f9b2fcb6bd55e67bb631d2b`
- Blueprint: `312d4ee8eed261bd62a0f2dd10ca4d347569277f3faa5373f27631f554bc2051`
- Placements: `0fd0226c56c4333951fe9ef84adc675eed952a974cf4652fe2358fae5c508118`
- SFX plan: `02d6dac0c7057ebeeb1ec4ff38a7e56196397265103afcc5da4fd75e8261db9b`
- Render media: `6a7124f3ceeae65708d2a2a0f1c7acbfa5fd2356027655538a43f8ae3b177aae`

## External boundaries

- Quduoduo: browser-real smoke blocked by navigation timeout; candidates 0, downloads 0, cost 0.
- Dreamina: read-only installed CLI audit showed image/video only; music generation unsupported.
- Provider generation, login, credits, protected audio, and generated SFX: `not_executed`.
- Final accepted external-call ledger: empty.

## Exact next step

Add an avoid-same-file adjacency constraint that remains active when duplicate-group evidence is unknown, with a five-material/29-slot regression and an explicit unavoidable-adjacency counter. Then perform one new local-only synthetic acceptance. Do not reopen Quduoduo or Dreamina gates during that work.
