# Music-Driven Travel Montage Prototype

## Current implementation boundary

The completed offline foundation provides strict Director contracts, a conservative Scanner bridge, local duplicate/audio evidence, structured music-search briefs, an offline catalog provider, and explainable three-direction ranking.

`director.catalog.quduoduo.parse_visible_results` is only a parser for normalized metadata captured from one currently visible result page. It does not open a browser, contain DOM selectors, bypass access controls, download preview audio, or perform background collection.

## Quduoduo live-smoke gate

Before any live smoke, show the exact `MusicSearchBrief` to the user and obtain explicit authorization to open one search-result page. The allowed capture fields are title, visible tags, BPM, duration, author or label, detail URL, and preview URL. Retain at most five candidates and display three directions.

Stop immediately on login requirements, CAPTCHA, WAF, or an unsupported page structure. The user may complete an access challenge manually; automation must not bypass it. Live capture artifacts belong below ignored `prototype/runs/<run-id>/catalog/` and must not contain cookies, credentials, raw DOM, or protected preview audio.

## External-service status

No Quduoduo page has been opened or captured by this implementation stage. Dreamina capability, login, music generation, SFX generation, paid calls, and credits have not been checked or used.
