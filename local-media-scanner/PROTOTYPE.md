# Music-Driven Travel Montage Prototype

## Current implementation boundary

The completed offline foundation provides strict Director contracts, a conservative Scanner bridge, local duplicate/audio evidence, structured music-search briefs, an offline catalog provider, and explainable three-direction ranking.

`director.catalog.quduoduo.parse_visible_results` is only a parser for normalized metadata captured from one currently visible result page. It does not open a browser, contain DOM selectors, bypass access controls, download preview audio, or perform background collection.

## Quduoduo live-smoke gate

Before any live smoke, show the exact `MusicSearchBrief` to the user and obtain explicit authorization to open one search-result page. The allowed capture fields are title, visible tags, BPM, duration, author or label, detail URL, and preview URL. Retain at most five candidates and display three directions.

Stop immediately on login requirements, CAPTCHA, WAF, or an unsupported page structure. The user may complete an access challenge manually; automation must not bypass it. Live capture artifacts belong below ignored `prototype/runs/<run-id>/catalog/` and must not contain cookies, credentials, raw DOM, or protected preview audio.

## External-service status

On 2026-08-30 the user authorized one Quduoduo visible-page smoke for the frozen 60-second search brief. The official product page identifies `https://agm.haifanwu.com/` as the catalog target, but both the in-app browser and connected Chrome timed out during navigation before any page content or result cards became available. The smoke is therefore `blocked/navigation_timeout`, with zero visible candidates, zero downloads, zero login/CAPTCHA/WAF interaction, and zero cost. Redacted local evidence is stored below ignored `prototype/runs/quduoduo-smoke-20260830/`.

Dreamina capability, login, music generation, SFX generation, paid calls, and credits have not been checked or used. Offline fixture-based Director work may continue, but no real Quduoduo catalog value or end-to-end provider success may be claimed.
