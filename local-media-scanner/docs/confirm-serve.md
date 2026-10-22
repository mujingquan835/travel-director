# Confirm desk serve

`travel-director serve --project <path> [--port 8765] [--lan]`

The HTTP stack is the Python standard library `http.server.ThreadingHTTPServer`. One local process serves the desk. There is no extra web framework and no authentication. The default bind address is `127.0.0.1`. `--lan` binds `0.0.0.0` so another machine on the same network can open the page. This is not a public-internet service. Video is never uploaded. The one upload is **导入 / 换音乐** on the music page: a single local mp3, m4a, or wav. That route accepts only a loopback client, even when `--lan` is on. Other routes still refuse a body larger than 64KB.

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

Opening the page loads the open draft. If there is no draft and nothing has been confirmed yet, one is created from `music_edit_regions.json` through `save_regions_draft`. After a version is confirmed, the page shows that locked snapshot and does not create a draft until you ask. Milestone A does not edit boundaries or add, split, or delete regions. Region blocks are not draggable or resizable. Clicking a block selects it. The project title is the first line of `brief.json` `raw_description`, with the folder name beside it.

The music page is a four-step bar, at most 64px tall: 导入音乐, 定分区角色, 确认版本, 导出剪映. The current step is highlighted and is the only one with a large primary button. Finished steps show a check and can be opened again. Later steps stay visible and muted, with the reason under the button when that step cannot proceed. A pending role’s button is 去选角色: it selects that region and opens the role menu. 收起 collapses the bar to one breadcrumb line; the browser remembers that choice. 换一版 stays on the 确认版本 step, and moves onto the breadcrumb while the bar is collapsed. Play and the clock sit on the line under the steps, with 本版主题 when a technique was chosen. The timeline under that is the ruler, music lane, beat ticks, region blocks, phrase row, shot slots, and the 手法 lane. Region blocks are not draggable. The playhead still is.

The page is a timeline, top to bottom: that step bar, then a mm:ss ruler, the music lane, beat ticks (downbeats thicker), and colored region blocks. Region blocks are not draggable. Clicking the ruler, the music lane, a region, a phrase, or a shot seeks the playhead there. Dragging the playhead, or dragging on those lanes, scrubs; the clock follows the pointer. Space plays or pauses from the current time. Left and right arrows step to the previous or next beat. Shift plus an arrow steps to the previous or next shot cut, or to the previous or next downbeat when the document has no shot slots. When the open document has `shot_slots`, the timeline also shows a phrase row, unequal shot slots, and a one-line「本段怎么剪」row. The open region, phrase, and shot follow the playhead, and the transport names the current shot. A detail lane titled 局部细节 · 跟随播放头 · 前后 4 秒 shows about eight seconds centered on the playhead. Dragging inside that lane scrubs too. The old equal-split row stays hidden until 对比旧版 is checked. Clicking a slot still shows its Chinese reason and the evidence ids, and does not start a loop. Slot edges are the region edges, so the region track and the shot track share one time at each section boundary. Export uses the confirmed region `start` / `end`. After analysis has snapped a boundary, or after you adopt a suggestion, those confirmed boundaries are the cuts. Shot types stay suggestions and are not draggable. If `shot_slots` is empty, the shot lane stays the old equal placeholders marked 预留·未启用. A collapsed **列表视图** replaces the old table. The inspector shows 时段 (read-only; 边界拖动：里程碑 B), the role dropdown, 建议镜长, snap_policy, 置信度, 分析依据, and 警告. It follows the region under the playhead.

New analysis assigns roles on the raw section bounds, then snaps the stored `start` / `end`. A move of less than a bar must not change the role: the 3–8s unknown section and the 8–25s establish section stay those roles when 8.0 moves to 8.74. The raw time stays on `start_raw_s` / `end_raw_s` when it moved. The rule is: nearest downbeat inside half a bar (2 beats). If downbeat confidence is below 0.10 and the nearest downbeat is farther than half a bar, use the nearest beat when that beat is inside one bar, and say so. Farther than one bar, do not move the boundary; flag `boundary_snap_beyond_bar`. A snap that would collapse a region is refused. Downbeats closer than half a bar are dropped (the earlier one is kept) before phrases are built, recorded on `downbeat_cluster_times`, and named in the `downbeat_cluster` warning. A gap of half a bar or more is kept, so 58.24 after 56.74 at 120 BPM stays.

An older draft or confirmed version is not rewritten on open. Boundary suggestions are still recomputed for display on a draft. A confirmed or history version shows the shot track that was frozen at confirm time (regions, `shot_style`, `shot_rules_version`, and the guidance layer) and does not replan it. A draft still replans with the current rules. If that frozen rule version disagrees with the running code, the page only says 「有新规则，可另存新草稿」. A confirmed file written before snapshots existed has no `shot_track_locked` flag. The page says the file will not be rewritten, and **基于此版另开草稿** (or `migrate_unlocked_confirmed_regions`) opens a new draft under the current rules. Each pending boundary gets a Chinese chip (建议 …s，偏移 …s) whose title states the distance and the half-bar threshold. **采纳** moves that region's start and the previous region's end. **全部采纳** moves every pending downbeat or beat suggestion and skips `beyond_bar`. Adopting on a confirmed or history version writes a new draft and leaves the confirmed file untouched. If a draft is already open, the buttons stay disabled and the API returns 409 「已经有打开的草稿。先确认或丢弃它，再基于确认版另开。」 Adopting an open draft updates that draft. `POST /api/regions-draft` is still role-only.

Changing a region's role on a draft recomputes that document's shot slots when beat events are already stored. Times stay put. The recompute keeps the draft's shot style.

Shot blocks tile to the exact time edges: no margin, padding, or outer border. Neighbors meet, and a 1px inner line separates them. A minimum width of one pixel does not move the next block. Labels that do not fit are hidden on the overview and stay available on hover and in the detail lane. A flurry is one bracket with hairlines between its members, on both the overview and the detail lane.

After the shot times are fixed, a guidance layer fills each slot with shot size, motion, transition in and out, a sound cue, a story beat, and a Chinese picture hint. It does not move `start` or `end`, and it leaves the existing `transition` value in place. The desk shows this as 剪辑思路 inside a bottom drawer that starts collapsed. The drawer also holds 对比上次 (still disabled, tooltip 后续版本开放), the beat-backend note, and 刀口嗒嗒声. 展开剪辑思路, or 收起 when it is open, reveals four rows: 景别, 转场, 声音, 故事. The guide choice is remembered in localStorage. The shot-track title no longer carries that button, so it does not sit on top of the shot blocks. The best slot is marked ★. A seam sentence (甩、匹配、推拉、遮挡) shows on that slot. 本段怎么剪 is an action sentence; the counts are in the hover title. Region names are 开场、铺陈、停留、推进、高潮、换气、收尾、待定. The slow style is 慢叙事, so 叙事 is not reused. Unknown roles say 还有 N 段待定角色 and offer 去选角色. 刀口嗒嗒声 is off until checked. Hover or click a shot to read `content_hint`. Narrow cells hide their text. Flurry groups stay one bracket. Travel establish base shots rotate 动, then 细, then 脸. That rotation changes shot type only.

Above the shot track, a draft can switch 剪法: 慢叙事, 旅拍快剪, or 活动快剪. A new `analyze-music-edit-regions` run defaults to 旅拍快剪 (`--shot-style travel`). The narrative planner's previous fields stay as they were. Choosing 叙事 still omits empty fastcut fields. The guidance fields are added on top for every style, including 叙事. 旅拍快剪 and 活动快剪 are deterministic rules (`fastcut-0.4` on the draft). They do not call a model and they do not move region boundaries. 活动快剪 keeps the establish section less dense than the build. Flash, ramp, and transition marks are suggestions for the editor. The detail lane legend reads 闪 闪白, 慢 变速, 甩 转场, and a bracket for a flurry group. `POST /api/regions-draft/shot-style` saves the style on the open draft and re-renders the shot track, 本段怎么剪, the current-shot line, and the detail lane. A confirmed version stays read-only and keeps the style it was locked with. Switching from a confirmed version forks a draft; if a draft is already open the call returns 409. `shot-track stats <desk.json>` prints per-region cuts and the build→drop line.

A travel or event draft also picks one theme technique from `director/shot_track/techniques/cards.json` (反差节奏、留白、定格、推近、条件变速). The seed is sha256 of the audio hash, version id, and options, and it only orders equal scores. Build and peak each have rhythm variants, still on the beat grid. The version header shows 本版主题, and a 手法 lane opens a short why card. Confirmed files keep the theme they were locked with. Calling `generate()` with no rhythm variant still uses the previous tables. The five cards are C-level notes with empty sources and status 草案. Jianying menu names are unchecked. The export writes the technique name into the clip name, the placeholder still, a marker, and a section of `edit-sheet.md`. Markers and speed curves are still unverified in Jianying.

## Beat backend and weights

`analyze-music` defaults to `--beat-backend auto`. Auto uses librosa. It uses beat_this only when that package imports and a checkpoint file is already on disk. It does not download during auto. `--beat-backend beat_this` asks for the model; if the extra is missing, or the run fails, the file records `beat_backend=librosa` and a Chinese note that it fell back. `--beat-backend librosa` stays on librosa. librosa calls `beat_track(..., trim=False)` and also counts `beat.plp` peaks for comparison. `trim=True` (the library default) drops leading and trailing beats while the onset score is under half the beat-envelope RMS, which is why a 123 BPM minute with a quiet intro and outro can come back with about 90 beats instead of about 123.

beat_this is the optional extra `beat` in `pyproject.toml` (torch, torchaudio, beat-this). The code passes `dbn=False`, so madmom is not used. The first explicit run downloads a checkpoint from the beat_this host into the torch hub cache (`beat_this-small0.ckpt` or `beat_this-final0.ckpt`). small0 is about 8MB and final0 is about 78MB. Set `BEAT_THIS_CHECKPOINT` to `small0`, `final0`, or a local file path. After that file exists, auto can use it offline. The music page shows `beat_backend_note`, including the download warning, whenever the analyzer wrote one. The desk never starts a download by itself.

The page does not draw the example slot JSON. Numbers on the timeline come from the open regions document.

The 确认版本 step has the version menu (草稿, 已确认 vNN, 历史确认), labeled 换一版. The bound track's first 8 hash characters and the confirm time sit in the drawer. **确认分区** runs the existing validator. On success it writes a confirmed snapshot and a receipt with `confirmed_by=user`, then the version is locked. There is no unconfirm. **保存草稿** and **丢弃草稿** are under 更多 in the drawer, not in the step bar.

A status chip shows 验收通过 when the draft can be confirmed. If any region is `unknown`, the roles step says 还有 N 段待定角色 and 去选角色 focuses that region's role menu. The normal confirm button stays disabled. The word 验收 is not used for a missing role. **强制确认** is under 更多 in the drawer, off until you check it and type a non-empty reason; the confirm receipt then stores `override` and that reason. The same override covers a validator failure. It is not drawn on the step bar.

A confirmed or history version is read-only: role dropdowns are disabled, and `POST /api/regions-draft` answers `409`. **基于此版另开草稿** copies that snapshot into a new draft and leaves the confirmed file unchanged. **对比上次** is disabled, with the tooltip 后续版本开放.

A broken draft or a drifted artifact hash does not drop the connection. The page or JSON API returns HTTP 4xx/5xx, a Chinese explanation, and a `travel-director` command.

Each row shows:

- 时段 — `start`–`end`, read-only
- 角色 — `edit_role` dropdown with Chinese labels (前奏, 高潮, 可卡点, and the other roles). `unknown` rows are highlighted
- 建议镜长 — `suggested_shot_mean_s`
- `snap_policy`
- 置信度 — `confidence`
- 警告 — file-level `MusicEditRegions.warnings` (for example `onset_rate_from_beat_grid_proxy`) in plain Chinese, with the code in small type. The region schema has no warning list; an `unknown` role adds “角色还没定”

`POST /api/regions-draft` accepts `expected_revision` and one `{region_id, edit_role}` per existing region. Any other field, a new id, or a missing id is `400` with a Chinese explanation. A changed role sets that region's `evidence_basis` to `manual` and leaves every other region field, including `musical_proxy` and the times, as they were. `edited_at` is the ISO UTC timestamp already on `RegionsVersionDocument`, the draft envelope. It is not added to `MusicEditRegion`, so analyzer JSON and the CLI schema stay the same. A stale `expected_revision` is `409`. The write still uses the temp-file rename inside the project root. A client-supplied path is refused.

**保存草稿** sends the current roles. **丢弃草稿** asks for confirmation, then `POST /api/regions-draft/discard`.

Clicking a block seeks there and selects it. **播放本段** plays that span from its start and does not turn the loop on. **循环本段** is off until you check it or press the button. While it is on, playback seeks back to the span start when the playhead reaches the end (with a small tolerance for `timeupdate`). While it is off, playback continues into the next region. The page shows the current time and, when a shot slot is under the playhead, a line such as 镜头 r03-s4 · 细 · 2.0s.

The music lane uses wavesurfer.js 7.12.12 (BSD-3-Clause), vendored under `director/vendor/wavesurfer/` with the Regions and Timeline plugins and `LICENSE`. The desk serves those files from `/vendor/wavesurfer/`. There is no CDN and no npm build at runtime. Peaks are precomputed on the server, not decoded in the browser: ffmpeg writes mono 8 kHz PCM when it is on `PATH`, and a 16-bit wav falls back to the stdlib `wave` module. Buckets are about 20 per second and capped at 20,000, so a 10-minute track stays a small JSON file (12,000 peaks). `GET /api/waveform-peaks` returns them. The cache file is `{sha256}.json` outside the project (`TRAVEL_DIRECTOR_PEAKS_CACHE`, or `~/.cache/travel-director/waveform-peaks`). It is not recorded in `project_state.json` and is not a project artifact. The Regions plugin only highlights the selected span, with drag and resize off.

`/export` points at the music page. After a version is confirmed, **导出剪辑** is enabled and `POST /api/regions-export` writes `delivery/regions/<version>/project.fcpxml`, `edit-sheet.md`, and one 1080×1920 H.264 placeholder per shot under `asset/placeholders/`. The spine is those video clips, abutted at 30 fps. Music is a connected clip (`lane="-1"`) on the first clip, for the whole song. Repeating the export overwrites that package. The button stays on 「正在生成占位…」 while the files are written. A draft is refused and no directory is created.

Region name and role are burned into the top corner of each placeholder, with the slot id, shot size, transition, duration, and `content_hint` on the card. The drop and a ★ best shot are marked on the picture. Markers are still written. There is no second video lane: the FCPXML that imported into macOS Jianying 11.4.0 on 2026-09-09 was spine video clips plus audio connected to the first clip, with no overlay, and a full-frame label would cover the card. Times are rounded to 30 fps because the regions document has no frame rate of its own and the shot planner uses 30. The portrait placeholders and the burned-in text have not been opened in Jianying on this machine. The page says that, and does not call the file compatible.

## 导入 / 换音乐

The music page has **导入 / 换音乐**. Choosing a local mp3, m4a, or wav posts it to `POST /api/music-import` as multipart field `music`. The handler checks the client address before it reads the body. `127.0.0.1` and `::1` are accepted. Any other peer gets 403 and the body is not read, including when the server was started with `--lan`. The import body limit is 100MB. `freeze_and_analyze_music` still refuses audio longer than 10 minutes, and a container that does not match the extension.

The job calls the existing `create_music_version` on the original parent. If the open project is already a music-version child, `music_version.json` points back at that parent, and the new directory is a sibling (`{parent}-music-{sha16}`), not a grandchild. Then `freeze_and_analyze_music` runs with beat backend `auto`: beat_this only when that package imports and a weight file is already cached, otherwise librosa. The page shows the phases 建版本, 拍点, 分区, and 完成, including the beat-backend note. Region analysis uses 旅拍快剪 and `save_regions_draft` opens a draft. On 完成 the page switches to the child with `POST /api/project` and opens `/music`. The parent and earlier children stay on disk. The **配乐** menu switches back the same way.

`create_music_version` still requires a frozen parent whose visual stages through director review are intact. A desk project that only has a brief and a frozen track gets a Chinese error and no new directory. The parent files are not rewritten either way. A file that matches the parent's music, a wrong extension, or an undecodable file does not create a version.

## Other routes

| Path | Body |
| --- | --- |
| `/api/status` | Frozen music, regions file, version counts, FCPXML package and receipt, deduped `hints`, and `progress` |
| `/api/recent` | Recent project paths |
| `/api/music-desk` | Open draft, or the selected `?version=`. Creates a candidate draft only when nothing is confirmed |
| `POST /api/project` | Switch the project this process is showing |
| `POST /api/music-import` | Loopback-only multipart upload of one mp3, m4a, or wav. Returns a job id |
| `GET /api/music-import/status?id=` | Phase of that job: 建版本, 拍点, 分区, 完成, or 失败 |
| `POST /api/reveal` | Open the resolved project root in the file manager |
| `POST /api/regions-draft` | Change `edit_role` only, when `expected_revision` matches. Confirmed versions are `409` |
| `POST /api/regions-draft/confirm` | Lock the open draft. `force` plus a non-empty `reason` records an override |
| `POST /api/regions-draft/from-confirmed` | Copy a confirmed snapshot into a new draft |
| `POST /api/regions-draft/discard` | Delete the open draft when `expected_revision` matches |
| `POST /api/regions-draft/adopt-boundaries` | Apply pending boundary suggestions (`boundaries` is `"all"` or a list of region ids). Confirmed or history versions fork a new draft; an open draft is updated in place. A second open draft is 409 |
| `/api/regions-versions` | Draft / confirmed / history listings |
| `/api/regions-versions/draft` | Open draft document |
| `/api/regions-versions/regions-vNN` | One snapshot |
| `/api/music-edit-regions` | Analyzer candidate JSON, or an error plus a CLI hint |
| `/audio/frozen` | Frozen music file, `Content-Type` from the asset, `Accept-Ranges: bytes` |
| `/api/waveform-peaks` | Display peaks for the frozen track, cached outside the project by sha256 |
| `/vendor/wavesurfer/…` | Vendored wavesurfer.js 7.12.12 and its plugins |

`/audio/frozen` answers `Range: bytes=` with `206 Partial Content`. Request targets that contain `..`, and a frozen path that resolves outside the project, are refused.

Export still calls `require_confirmed_regions_version` and refuses `latest` or `draft`. The project page step 分段已确认 is complete once `confirmed_count` is at least one. Opening a page does not re-run analysis. Importing a new track does, in a new music-version directory. Export writes an FCPXML package only from a confirmed snapshot. The shot lane does not select media.
