# Confirm desk serve (Slice 2)

`travel-director serve --project <path> [--port 8765] [--lan]`

The HTTP stack is the Python standard library `http.server.ThreadingHTTPServer`. One local process serves a single project. There is no extra web framework, no authentication, and no upload. The default bind address is `127.0.0.1`. `--lan` binds `0.0.0.0` so another machine on the same network can open the page. This is not a public-internet service.

## Routes (GET only)

| Path | Body |
| --- | --- |
| `/` | Placeholder HTML with an `<audio>` element pointed at the frozen track |
| `/api/status` | Frozen music, `music_edit_regions.json`, version counts, discovered `project.fcpxml` |
| `/api/regions-versions` | Draft / confirmed / history listings from the Slice 1 store |
| `/api/regions-versions/draft` | Open draft document |
| `/api/regions-versions/regions-vNN` | One confirmed or draft snapshot |
| `/api/music-edit-regions` | Analyzer candidate JSON |
| `/audio/frozen` | Frozen music file, `Content-Type` from the asset, `Accept-Ranges: bytes` |

Other methods return `405` JSON. A missing project or missing `music_edit_regions.json` returns JSON `error` plus a copyable `hint` such as `travel-director analyze-music-edit-regions --project <path>`.

`/audio/frozen` answers `Range: bytes=` with `206 Partial Content`. The handler never takes a client path. Request targets that contain `..`, and a frozen path that resolves outside the project, are refused.

Slice 2 does not save drafts, confirm, discard, re-run analysis, or export FCPXML.
