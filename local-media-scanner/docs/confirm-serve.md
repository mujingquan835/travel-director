# Confirm desk serve

`travel-director serve --project <path> [--port 8765] [--lan]`

The HTTP stack is the Python standard library `http.server.ThreadingHTTPServer`. One local process serves the desk. There is no extra web framework, no authentication, and no upload. The default bind address is `127.0.0.1`. `--lan` binds `0.0.0.0` so another machine on the same network can open the page. This is not a public-internet service.

## Project page `/`

The page can open another local project path, lists a few recent paths, and shows a status bar:

- frozen music present or not
- `music_edit_regions.json` present or not
- confirmed-version count
- FCPXML package present, and whether a sibling `receipt.json` was found

**刷新产物** calls `GET /api/status` again. The server process stays up.

**访达打开目录** is `POST /api/reveal`. macOS runs `open <resolved project root>`. Linux runs `xdg-open <resolved project root>`. The command receives that resolved root only. A client path that resolves somewhere else is refused. Windows is not implemented.

Recent paths are a small JSON file, `.confirm-desk-recent.json`, in the process working directory (tests can point this somewhere else). There is no cloud sync. A path is recorded only after it opens as a real project.

Bad paths and missing artifacts stay on the page as text, with the same copyable `travel-director …` hints as the JSON API.

`/music` and `/export` are stubs that say `Slice 4+/8 coming`.

## Other routes

| Path | Body |
| --- | --- |
| `/api/status` | Frozen music, regions file, version counts, FCPXML package and receipt |
| `/api/recent` | Recent project paths |
| `POST /api/project` | Switch the project this process is showing |
| `POST /api/reveal` | Open the resolved project root in the file manager |
| `/api/regions-versions` | Draft / confirmed / history listings |
| `/api/regions-versions/draft` | Open draft document |
| `/api/regions-versions/regions-vNN` | One snapshot |
| `/api/music-edit-regions` | Analyzer candidate JSON, or an error plus a CLI hint |
| `/audio/frozen` | Frozen music file, `Content-Type` from the asset, `Accept-Ranges: bytes` |

Other writes return `405` JSON. `/audio/frozen` answers `Range: bytes=` with `206 Partial Content`. Request targets that contain `..`, and a frozen path that resolves outside the project, are refused.

This desk does not save drafts, confirm, discard, re-run analysis, or export FCPXML.
