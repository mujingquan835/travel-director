# Confirm desk serve

`travel-director serve --project <path> [--port 8765] [--lan]`

The HTTP stack is the Python standard library `http.server.ThreadingHTTPServer`. One local process serves the desk. There is no extra web framework, no authentication, and no upload. The default bind address is `127.0.0.1`. `--lan` binds `0.0.0.0` so another machine on the same network can open the page. This is not a public-internet service.

## Project page `/`

The page says what the desk is for: the track is split automatically, you listen and edit, then a confirmed version is what export will use.

The path shows the folder name in large type and the full path underneath, truncated, with the full path in the tooltip.

Four steps, each **完成** or **未完成**:

1. 配乐已定 — frozen music is in the project
2. 音乐分段分析 — `music_edit_regions.json` is recorded
3. 分段已确认 — at least one confirmed regions version
4. 已导出剪映工程 — a `project.fcpxml` package is inside the project

**下一步** is the first step that is not done, with one plain Chinese instruction. CLI commands sit in a collapsed **显示命令** block with a copy button. Each command is listed once. The main page does not show raw artifact field names.

**刷新产物** calls `GET /api/status` again. The server process stays up.

**访达打开目录** is `POST /api/reveal`. macOS runs `open <resolved project root>`. Linux runs `xdg-open <resolved project root>`. The command receives that resolved root only. A client path that resolves somewhere else is refused. Windows is not implemented.

Recent paths are a small JSON file, `.confirm-desk-recent.json`, in the process working directory (tests can point this somewhere else). There is no cloud sync. A path is recorded only after it opens as a real project.

A bad path stays on the page as text, with the same copyable `travel-director …` hint as the JSON API.

## Music page `/music`

Opening the page loads analyzer candidates and the open draft. If there is no draft, one is created from `music_edit_regions.json` through `save_regions_draft`. Milestone A does not edit boundaries or add, split, or delete regions.

Each row shows:

- 时段 — `start`–`end`, read-only
- 角色 — `edit_role` dropdown with Chinese labels (前奏, 高潮, 可卡点, and the other roles). `unknown` rows are highlighted
- 建议镜长 — `suggested_shot_mean_s`
- `snap_policy`
- 置信度 — `confidence`
- 警告 — file-level `MusicEditRegions.warnings` (for example `onset_rate_from_beat_grid_proxy`) in plain Chinese, with the code in small type. The region schema has no warning list; an `unknown` role adds “角色还没定”

`POST /api/regions-draft` accepts `expected_revision` and one `{region_id, edit_role}` per existing region. Any other field, a new id, or a missing id is `400` with a Chinese explanation. A changed role sets that region's `evidence_basis` to `manual` and leaves every other region field, including `musical_proxy` and the times, as they were. `edited_at` is the ISO UTC timestamp already on `RegionsVersionDocument`, the draft envelope. It is not added to `MusicEditRegion`, so analyzer JSON and the CLI schema stay the same. A stale `expected_revision` is `409`. The write still uses the temp-file rename inside the project root. A client-supplied path is refused.

**保存草稿** sends the current roles. **丢弃草稿** asks for confirmation, then `POST /api/regions-draft/discard`.

Clicking a row selects it. **播放本段** plays that span from `/audio/frozen`. **循环** seeks back to the span start when the playhead reaches the end (with a small tolerance for `timeupdate`). The page shows the current time. Confirm/lock is not on this page. There is no waveform.

`/export` says `导出：后续版本开放`.

## Other routes

| Path | Body |
| --- | --- |
| `/api/status` | Frozen music, regions file, version counts, FCPXML package and receipt, deduped `hints`, and `progress` |
| `/api/recent` | Recent project paths |
| `/api/music-desk` | Open draft, creating it from candidates when missing |
| `POST /api/project` | Switch the project this process is showing |
| `POST /api/reveal` | Open the resolved project root in the file manager |
| `POST /api/regions-draft` | Change `edit_role` only, when `expected_revision` matches |
| `POST /api/regions-draft/discard` | Delete the open draft when `expected_revision` matches |
| `/api/regions-versions` | Draft / confirmed / history listings |
| `/api/regions-versions/draft` | Open draft document |
| `/api/regions-versions/regions-vNN` | One snapshot |
| `/api/music-edit-regions` | Analyzer candidate JSON, or an error plus a CLI hint |
| `/audio/frozen` | Frozen music file, `Content-Type` from the asset, `Accept-Ranges: bytes` |

`/audio/frozen` answers `Range: bytes=` with `206 Partial Content`. Request targets that contain `..`, and a frozen path that resolves outside the project, are refused.

This desk does not confirm a regions version, re-run analysis, or export FCPXML.
