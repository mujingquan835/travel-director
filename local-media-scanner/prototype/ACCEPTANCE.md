# Music-Driven Travel Montage Prototype Acceptance

Acceptance date: 2026-08-30 (Asia/Shanghai)  
Decision: **continue-with-constraints**

## Scope and evidence classes

| Boundary | Evidence class | Result |
|---|---|---|
| Synthetic source media and catalog metadata | fixture | Five 12-second colored MP4 files, one 60-second click-track WAV, and three ranked fixture directions were used. |
| Scanner, audio analysis, timeline, placement, SFX planning, and FFmpeg | local-real | Executed locally with real binaries and stored artifacts. |
| Quduoduo visible page | browser-real | `blocked/navigation_timeout`; zero visible candidates and zero downloads. |
| Dreamina capability | local-real read-only | Installed help exposed image/video generators only; `music_generation=false`. |
| Quduoduo catalog value and Dreamina music output | provider-real | `not_executed`; no protected audio, login, generation, or provider success evidence exists. |
| Paid/provider calls | ledger | Zero calls, zero known cost, zero credit use. |

This acceptance does not claim editorial quality on real travel footage, Quduoduo value, Dreamina music generation, or provider end-to-end success.

## Frozen acceptance inputs

- Target: 60 seconds, portrait, maximum external calls 0, generated SFX calls 0.
- Scanner result SHA-256: `e68993888ab9612bf7a1b1ad824af80af9848a2d73b58f2e0e7a5d454e460a64`.
- Scanner manifest SHA-256: `9d7937dcd118b5a21471e0d17ecd304805bfa80a8901c2aafa414186cd3661c0`.
- User brief SHA-256: `0e6a92623b6100757697615c3f41d3064a1e67e88471250a4643f999fbda8f5a`.
- Search brief SHA-256: `54ba602da4a73de2c572ea2af0743bdec91fda08c5fce32101b9954e8e81d90c`.
- Catalog result SHA-256: `c568a3f8d7a1616af8f6cb1afc05e02551c78fc69c5a650f412057b210b9e5a6`.
- Selected direction metadata SHA-256: `c411ba5a345bbccfa8bfaa8dab528b8d11a89ea38f9b2fcb6bd55e67bb631d2b`.
- Blueprint SHA-256: `312d4ee8eed261bd62a0f2dd10ca4d347569277f3faa5373f27631f554bc2051`.
- Music WAV SHA-256: `305b4b94e64203acf232d25be221fa48dbb58c321d7f4368d12d0fb56f8095f1`.
- Source-video SHA-256 values:
  - `color-01-red.mp4`: `70fac66f50938c72e5f1ff7e7cb4ae6a202a9ffcb3b2f0f3225ea25e849bc849`
  - `color-02-orange.mp4`: `11d73f81952a16cefc955248a6cf762c2bedfb772a8db169dfd7bda1b204b1cd`
  - `color-03-green.mp4`: `1af285b53f28fd00f04f503ac8c32bf237a039fde27de3d159e13b10b7d0c2a6`
  - `color-04-blue.mp4`: `12bfe819386b5e7cb86e453b66c66cd5837b1f98fac1b47f0d2552a812ec862d`
  - `color-05-purple.mp4`: `d9e60ebf5557d9afa21561d68dce66262b7873aa57d1b2751571b2299cfa274c`

## Gate results

- Offline suite after the accepted repair: `137 passed`; three upstream `audioread` deprecation warnings on Python 3.12.
- Frozen Scanner Ground Truth: `valid: 30 items`.
- Scanner: 5 materials, 60 seconds total, CPU/no-models, about 9.1 seconds. Semantics correctly remained abstained.
- Ranked fixture directions: `明亮城市脉冲`, `探索推进`, `古城轻步`.
- Generation prompt: no selected title or author leakage; it retained the original-composition restriction.
- Measured music: 117.453835 BPM; intro 0–7, rise 7–24, breath 24–30, climax 30–53, outro 53–60 seconds.
- Timeline: 29 contiguous slots covering 0–60 seconds without overlap.
- Placement: 29 selected clips, 60 seconds total, 24 recorded reuses, 1 `recommended_range_unavailable` relaxation, 0 unfilled slots, and all source bounds valid.
- Known duplicate groups: 0 adjacent violations. Because the synthetic inputs had no known duplicate-group IDs, this does not prove adjacent visual diversity.
- Same-file adjacency: 21 adjacent pairs. This is the principal quality blocker and is not corrected in this acceptance because the single repair/rerun allowance was already used.
- SFX: 29 items, all restricted to placed materials, all `silence`; no generation was scheduled or called.
- Render: 60.000 seconds, 720×1280, H.264/AAC, 24 fps; output SHA-256 `6a7124f3ceeae65708d2a2a0f1c7acbfa5fd2356027655538a43f8ae3b177aae`.
- External ledger: `[]`; calls 0, cost 0.

Approximate acceptance-stage wall time was 9.1 seconds for Scanner, 2.7 seconds through timeline, under 0.1 seconds for selection/SFX recording, and 1.4 seconds for render. These timings are local observations, not an SLA.

## Failure and rerun record

The first immutable Director acceptance at `prototype/runs/acceptance-20260830/director/montage-v1/` returned 12 placements and 17 `insufficient_material` errors. Investigation found two shortage-degradation branches in the selector: climax did not reuse after unique candidates were exhausted, and a technically long-enough source could not explicitly relax a too-short recommended range.

The single permitted repair added regression tests and an auditable `recommended_range_unavailable` fallback, committed as `f966d27`. The only rerun is `prototype/runs/acceptance-20260830-rerun1/director/montage-v1/`; it filled all 29 slots and produced the verified render. No further quality correction or rerun was performed.

## Decision and exact next step

Continue only with these constraints:

1. Before another acceptance, make same-file adjacency a hard preference whenever any technically valid alternative exists, including when `duplicate_group_id` is unknown. Add a regression using five materials and 29 slots; report unavoidable adjacency separately from known duplicate groups.
2. Repeat a local-only synthetic acceptance once and require zero avoidable same-file adjacencies before using real travel footage.
3. Do not retry Quduoduo without a fresh explicit browser authorization and a reachable official result page. Do not request Dreamina generation authorization until installed help proves a real music command and cost/credit behavior is known.
4. Keep provider-real and editorial-quality claims `not_executed` until rights-cleared real music and representative travel footage complete their own gated acceptance.
