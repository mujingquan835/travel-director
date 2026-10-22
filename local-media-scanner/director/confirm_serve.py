"""Local confirm desk: project page and thin music-region editor.

HTTP stack: the stdlib ``http.server.ThreadingHTTPServer``. One process, no
extra dependency, and no authentication. The default bind address is
``127.0.0.1``. ``--lan`` binds ``0.0.0.0`` for other machines on the same
network. This is not a public internet service. The only upload is
``POST /api/music-import``: one local mp3, m4a, or wav, and only from a
loopback client, even when the port is bound on the LAN. Other routes still
refuse bodies larger than 64KB.

``/`` explains the desk in Chinese and shows four steps. ``/music`` is the
timeline desk for the open draft (created from analyzer candidates only when
nothing is confirmed yet) and can lock it. ``/export`` points at the music-page
button. That button writes a 30 fps FCPXML package of real portrait
placeholders from a confirmed snapshot. Jianying has not opened this
portrait file on this machine. The 2026-09-09 check only covered video
and audio clips.

``POST /api/regions-draft`` accepts only an ``edit_role`` change for each
existing region id, plus ``expected_revision``. A role change sets
``evidence_basis`` to ``manual``. ``edited_at`` stays on the draft document
(``RegionsVersionDocument``), not on the analyzer region schema. Times, adds,
and deletes are refused. A confirmed version is read-only. ``POST
/api/regions-draft/shot-style`` replans the shot track for narrative, travel,
or event. An open draft is updated in place. A confirmed version is not
rewritten: the same call forks a draft, unless one is already open. ``POST
/api/regions-draft/confirm`` locks the open draft. ``POST
/api/regions-draft/from-confirmed`` copies a locked snapshot into a new draft.
Exceptions while rendering a page or API become a Chinese error body. Opening
a page does not re-run analysis. Importing a new track does: it forks a music
version, measures beats, and opens a draft. Export reads a confirmed snapshot.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import ValidationError

from director.audio_import import ImportedMusicAsset, load_music_evidence
from director.music_import import (
    MAX_MUSIC_IMPORT_BYTES,
    chinese_import_error,
    import_jobs,
    is_loopback_host,
    list_music_family,
    parse_music_upload,
    resolve_family_parent,
    start_music_import,
)
from director.music_edit_regions_schema import MusicEditRegion, MusicEditRegions
from director.music_edit_regions_versions import (
    RegionsVersionError,
    _confirm_blockers,
    confirm_regions_draft,
    discard_regions_draft,
    list_regions_versions,
    migrate_unlocked_confirmed_regions,
    load_regions_draft,
    load_regions_version,
    save_regions_draft,
)
from director.project import ProjectConflict, ProjectPaths, _sha256_file, load_project_state, open_project
from director.role_labels import ROLE_LABELS_ZH
from director.waveform_peaks import load_or_build_peaks


DEFAULT_BIND_HOST = "127.0.0.1"
LAN_BIND_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
RECENT_FILE_NAME = ".confirm-desk-recent.json"
_MAX_RECENT = 8
_MAX_BODY_BYTES = 65536

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_VERSION_ID_RE = re.compile(r"^regions-v[0-9]{2,}$")
_DRAFT_LOCK = threading.Lock()
_STALE_REVISION = "stale draft revision; refresh and edit again"
_ROLE_ONLY = "只能修改每段的角色。不能改时间，也不能增加或删除分段。"
_CLIENT_PATH_KEYS = ("path", "destination", "output", "target")
_PLAYBACK_TOLERANCE = 0.08

KIND_LABELS = ROLE_LABELS_ZH
SNAP_LABELS = {
    "downbeat": "对齐强拍",
    "beat": "对齐拍点",
    "free": "自由",
}
WARNING_LABELS = {
    "onset_rate_from_beat_grid_proxy": "节奏密度来自节拍网格，不是真正的起音",
    "hook_window_soft": "开场窗口只是宽松估计",
    "short_region_unmerged": "有很短的一段没能并进旁边",
    "target_window_clipped": "目标时长被整曲长度截断了",
    "missing_settle_outro": "结尾没有收尾段",
    "meter_assumed_4_4": "拍号按 4/4 估计，曲子如果不是 4/4，强拍会偏",
    "downbeat_phase_heuristic": "强拍由起音相位估计；置信度太低时退回每四拍",
    "beat_grid_gaps": "有的拍点之间空了一截，缺口里的刀口会弱一些",
    "boundary_snapped": "分区边界已经吸到拍上，吸附前的时间记在每条边界的原始时间里。",
    "boundary_snap_beat_low_confidence": "强拍置信度低，而且最近强拍超过半小节，这条边界改吸最近拍点",
    "boundary_snap_beyond_bar": "最近的格点超过 1 小节，这条边界没有移动",
    "downbeat_cluster": "有的强拍相距不足半小节，较晚的那一个已忽略",
    "slot_budget_exception": "有的镜头短于本段镜长下限，属于列出的加速或转场",
}
_PROGRESS_STEPS = (
    {
        "id": "music",
        "title": "配乐已定",
        "meaning": "这首配乐已经固定在项目里，后面的分段都对着它。",
        "instruction": "先把配乐导入这个项目，定下来再做分段。",
    },
    {
        "id": "analysis",
        "title": "音乐分段分析",
        "meaning": "程序已经把曲子切成几段，供你试听和修改。",
        "instruction": "去音乐分段页听每一段，按需要改角色。",
    },
    {
        "id": "confirmed",
        "title": "分段已确认",
        "meaning": "已经有锁定的分段版本，导出时会用这一版。",
        "instruction": "打开音乐分段，听完后点确认分区。还有待定角色时，普通确认会停用。",
    },
    {
        "id": "export",
        "title": "已导出剪映工程",
        "meaning": "已确认快照已经写成占位视频、FCPXML 和剪辑单。这份竖屏占位还没在这台机器上用剪映打开过。",
        "instruction": "在音乐页确认之后，点导出剪辑。",
    },
)

_PAGE_STYLE = """
    :root { color-scheme: light; font-family: "Iowan Old Style", Palatino, "Songti SC", serif; }
    body { margin: 0; background: #f7f4ee; color: #1c1915; }
    header, main { max-width: 56rem; margin: 0 auto; padding: 1.25rem; }
    header { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }
    nav a { margin-left: 0.75rem; color: #6b4423; }
    h1 { font-size: 1.6rem; margin: 0; }
    .lede { font-size: 1.05rem; line-height: 1.5; }
    form, .panel, .steps li, #next-step { background: #fffdf8; border: 1px solid #e4dccb; border-radius: 8px; padding: 0.9rem 1rem; }
    label { display: block; font-size: 0.85rem; margin-bottom: 0.35rem; }
    input[type="text"], select { width: 100%; box-sizing: border-box; padding: 0.35rem 0.45rem; font: inherit; }
    .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.6rem; }
    button { font: inherit; background: #243024; color: #f7f4ee; border: 0; border-radius: 6px; padding: 0.4rem 0.75rem; cursor: pointer; }
    button.secondary { background: #6b4423; }
    .steps { list-style: none; padding: 0; margin: 0 0 0.9rem; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.75rem; }
    .steps .index { color: #6b6256; font-size: 0.8rem; }
    .steps h2 { font-size: 1rem; margin: 0.15rem 0; }
    .steps .state { display: block; font-size: 1.05rem; }
    .steps p, .project-path { color: #5c564c; font-size: 0.82rem; line-height: 1.4; }
    .steps li.is-next { outline: 2px solid #243024; background: #fff8e8; }
    .project-name { font-size: 1.35rem; margin: 0.15rem 0; }
    .project-path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 0; }
    #next-step { margin: 0 0 0.9rem; }
    #error { border-color: #9a3412; background: #fff1eb; }
    #hints code { display: block; font-family: ui-monospace, monospace; font-size: 0.82rem; margin: 0.35rem 0; white-space: pre-wrap; }
    #recent button { display: block; width: 100%; text-align: left; background: transparent; color: #1c1915; border: 1px solid #e4dccb; margin-top: 0.35rem; }
    audio { width: 100%; margin-top: 0.5rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 0.35rem; border-bottom: 1px solid #e4dccb; vertical-align: middle; }
    .strip { display: flex; height: 2rem; margin: 0.4rem 0 0.8rem; border-radius: 6px; overflow: hidden; }
    .strip span { display: flex; align-items: center; justify-content: center; background: #efe6d6; border-right: 1px solid #fffdf8; font-size: 0.75rem; overflow: hidden; }
    tr.is-unknown { background: #fff1eb; }
    tr.is-selected { box-shadow: inset 3px 0 0 #243024; background: #fff8e8; }
    small { color: #6b6256; }
    #playhead, #version-meta { font-variant-numeric: tabular-nums; }
    #acceptance { margin: 0.6rem 0; padding: 0.45rem 0.7rem; border-radius: 6px; }
    #acceptance.ok { background: #e5f6e8; color: #14532d; }
    #acceptance.bad { background: #fee2e2; color: #9a3412; }
    #unknown-warning { color: #9a3412; }
    button:disabled, select:disabled { opacity: 0.55; cursor: not-allowed; }
    @media (max-width: 720px) { .steps { grid-template-columns: 1fr 1fr; } }
"""

_PROJECT_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>确认台 · 项目</title>
  <style>__STYLE__</style>
</head>
<body>
  <header>
    <h1>确认台</h1>
    <nav>
      <a href="/" aria-current="page">项目</a>
      <a href="/music">音乐分段</a>
      <a href="/export">导出</a>
    </nav>
  </header>
  <main>
    <p class="lede">配乐自动分段 → 你听并修改确认 → 用确认版导出剪映 FCPXML。</p>
    <p class="project-name" id="project-name" title="__PROJECT_PATH__">__PROJECT_NAME__</p>
    <p class="project-path" id="project-path" title="__PROJECT_PATH__">__PROJECT_PATH__</p>
    <form id="open-form" class="panel">
      <label for="project-path-input">打开本机项目路径</label>
      <input id="project-path-input" type="text" name="path" autocomplete="off" spellcheck="false" value="__PROJECT_PATH__">
      <div class="actions">
        <button type="submit">打开项目</button>
        <button type="button" id="refresh" class="secondary">刷新产物</button>
        <button type="button" id="reveal" class="secondary">访达打开目录</button>
      </div>
    </form>
    <ol class="steps" aria-label="进度">
      <li data-step="music"><span class="index">①</span><h2>配乐已定</h2><strong class="state">未完成</strong><p>这首配乐已经固定在项目里，后面的分段都对着它。</p></li>
      <li data-step="analysis"><span class="index">②</span><h2>音乐分段分析</h2><strong class="state">未完成</strong><p>程序已经把曲子切成几段，供你试听和修改。</p></li>
      <li data-step="confirmed"><span class="index">③</span><h2>分段已确认</h2><strong class="state">未完成</strong><p>已经有锁定的分段版本，导出时会用这一版。</p></li>
      <li data-step="export"><span class="index">④</span><h2>已导出剪映工程</h2><strong class="state">未完成</strong><p>剪映工程已经生成，可以拿去剪辑。</p></li>
    </ol>
    <p id="next-step">下一步：正在读取项目状态。</p>
    <section id="error" class="panel" hidden></section>
    <section class="panel">
      <div>冻结曲试听</div>
      <audio id="track" controls src="/audio/frozen"></audio>
    </section>
    <details class="panel">
      <summary>显示命令</summary>
      <div id="hints"></div>
      <button type="button" id="copy-commands" class="secondary">复制命令</button>
    </details>
    <section id="recent" class="panel" aria-label="最近项目"></section>
  </main>
  <script>
    function showPath(full) {
      if (!full) return;
      var parts = full.split("/").filter(Boolean);
      var name = parts.length ? parts[parts.length - 1] : full;
      var nameEl = document.getElementById("project-name");
      var pathEl = document.getElementById("project-path");
      nameEl.textContent = name;
      nameEl.title = full;
      pathEl.textContent = full;
      pathEl.title = full;
      document.getElementById("project-path-input").value = full;
    }
    function renderHints(list) {
      var box = document.getElementById("hints");
      box.textContent = "";
      var seen = {};
      (list || []).forEach(function (text) {
        if (!text || seen[text]) return;
        seen[text] = true;
        var code = document.createElement("code");
        code.textContent = text;
        box.appendChild(code);
      });
    }
    function applyProgress(progress) {
      var steps = (progress && progress.steps) || [];
      steps.forEach(function (step) {
        var item = document.querySelector('[data-step="' + step.id + '"]');
        if (!item) return;
        item.querySelector(".state").textContent = step.state === "完成" ? "完成" : "未完成";
        item.classList.toggle("is-next", progress.next && progress.next.id === step.id);
      });
      var next = document.getElementById("next-step");
      if (!progress || !progress.next) {
        next.textContent = "下一步：这四步都完成了。";
        return;
      }
      next.textContent = "下一步：" + progress.next.title + "。" + progress.next.instruction;
    }
    function show(data) {
      var errorBox = document.getElementById("error");
      if (data.error) {
        errorBox.hidden = false;
        errorBox.textContent = data.error;
        renderHints(data.hint ? [data.hint] : data.hints || []);
        document.querySelectorAll(".state").forEach(function (node) { node.textContent = "未完成"; });
        document.getElementById("next-step").textContent = "下一步：这条路径打不开。请换一个项目目录，或展开命令查看怎么建项目。";
        return;
      }
      errorBox.hidden = true;
      errorBox.textContent = "";
      showPath(data.project_path);
      applyProgress(data.progress);
      renderHints(data.hints || []);
    }
    function refresh() {
      return fetch("/api/status").then(function (response) {
        return response.json().then(show);
      }).catch(function (err) {
        show({error: String(err), hint: ""});
      });
    }
    function loadRecent() {
      return fetch("/api/recent").then(function (response) { return response.json(); }).then(function (data) {
        var box = document.getElementById("recent");
        box.textContent = "";
        var title = document.createElement("div");
        title.textContent = "最近项目";
        box.appendChild(title);
        (data.paths || []).forEach(function (path) {
          var button = document.createElement("button");
          button.type = "button";
          button.textContent = path;
          button.addEventListener("click", function () { openProject(path); });
          box.appendChild(button);
        });
      });
    }
    function openProject(path) {
      return fetch("/api/project", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path: path})
      }).then(function (response) {
        return response.json().then(function (data) { show(data); return loadRecent(); });
      });
    }
    document.getElementById("refresh").addEventListener("click", refresh);
    document.getElementById("open-form").addEventListener("submit", function (event) {
      event.preventDefault();
      openProject(document.getElementById("project-path-input").value);
    });
    document.getElementById("reveal").addEventListener("click", function () {
      var path = document.getElementById("project-path-input").value;
      fetch("/api/reveal", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path: path})
      }).then(function (response) {
        return response.json().then(function (data) {
          var errorBox = document.getElementById("error");
          if (data.error) {
            errorBox.hidden = false;
            errorBox.textContent = data.error;
          }
        });
      });
    });
    document.getElementById("copy-commands").addEventListener("click", function () {
      var text = Array.prototype.map.call(document.querySelectorAll("#hints code"), function (node) {
        return node.textContent;
      }).join("\\n");
      if (navigator.clipboard && text) navigator.clipboard.writeText(text);
    });
    refresh().then(loadRecent);
  </script>
</body>
</html>
"""

_EXPORT_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>确认台 · 导出</title>
  <style>
    body { margin: 0; background: #f7f4ee; color: #1c1915; font-family: "Iowan Old Style", Palatino, "Songti SC", serif; }
    main { max-width: 40rem; margin: 0 auto; padding: 1.25rem; }
    a { color: #6b4423; }
  </style>
</head>
<body>
  <main>
    <p>导出在音乐页。确认分区之后，点「导出剪辑」。只导出已确认快照，按 30fps 生成竖屏占位视频，接成 FCPXML，并写一份剪辑单。分区名烧在占位角标上。</p>
    <p>主轨是真实占位视频，音乐挂在第一段下面。竖屏占位和烧录的字还没在这台机器上验证。不要把这份导出当成已经兼容剪映。</p>
    <p><a href="/music">去音乐页</a> · <a href="/">返回项目</a></p>
  </main>
</body>
</html>
"""

class FrozenMusicPathError(ProjectConflict):
    """Frozen music does not stay inside the project directory."""


@dataclass
class ServeResponse:
    status: int
    body: bytes
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)


def serve_bind_host(lan: bool) -> str:
    """Return the bind address. Loopback unless the operator asked for the LAN."""

    return LAN_BIND_HOST if lan else DEFAULT_BIND_HOST


def _json_response(status: int, payload: dict) -> ServeResponse:
    body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return ServeResponse(status, body, "application/json; charset=utf-8")


def _error(status: int, message: str, hint: str) -> ServeResponse:
    return _json_response(status, {"error": message, "hint": hint})


def _project_hint(project: Path) -> str:
    return (
        "travel-director init-visual-project --project-id <id> "
        f"--raw-brief <brief.json> --run-root {project.parent}"
    )


def _regions_hint(project: Path) -> str:
    return f"travel-director analyze-music-edit-regions --project {project}"


def _music_hint(project: Path) -> str:
    return f"travel-director run --project {project} --music <file.wav>"


def _open(project: Path) -> tuple[ProjectPaths | None, ServeResponse | None]:
    try:
        return open_project(project), None
    except FileNotFoundError as exc:
        return None, _error(404, str(exc), _project_hint(project))


def _traversal_requested(target: str) -> bool:
    parsed = urlsplit(target)
    decoded_path = unquote(parsed.path)
    decoded_query = unquote(parsed.query)
    if ".." in decoded_path or ".." in decoded_query or "\\" in decoded_path:
        return True
    return decoded_path.startswith("//")


def _frozen_music(paths: ProjectPaths) -> tuple[Path, ImportedMusicAsset] | None:
    state = load_project_state(paths)
    recorded = state.completed_artifact_hashes.get("music_asset")
    asset_path = paths.generated_music
    if recorded is None or not asset_path.is_file():
        return None
    if _sha256_file(asset_path) != recorded:
        raise ProjectConflict("supporting artifact hash drifted: music_asset")
    asset = ImportedMusicAsset.model_validate_json(asset_path.read_text(encoding="utf-8"))
    relative = Path(asset.frozen_relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise FrozenMusicPathError("frozen music path is outside the project")
    root = paths.root.resolve()
    frozen = (paths.root / relative).resolve()
    if not frozen.is_file() or not frozen.is_relative_to(root):
        raise FrozenMusicPathError("frozen music path is outside the project")
    if _sha256_file(frozen) != asset.source_sha256:
        raise ProjectConflict("frozen music asset hash drifted")
    return frozen, asset


def _regions_present(paths: ProjectPaths) -> bool:
    state = load_project_state(paths)
    recorded = state.completed_artifact_hashes.get("music_edit_regions")
    artifact = paths.music_edit_regions
    return bool(recorded and artifact.is_file() and _sha256_file(artifact) == recorded)


def _inside_project(base: Path, candidate: Path) -> bool:
    if candidate.is_symlink() or not candidate.is_file():
        return False
    resolved = candidate.resolve()
    return resolved.is_file() and resolved.is_relative_to(base)


def _discover_fcpxml(root: Path) -> tuple[list[str], list[str]]:
    packages: list[str] = []
    receipts: list[str] = []
    base = root.resolve()
    for directory, dirnames, filenames in os.walk(base, followlinks=False):
        current = Path(directory)
        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
        if "project.fcpxml" not in filenames:
            continue
        package = current / "project.fcpxml"
        if not _inside_project(base, package):
            continue
        packages.append(package.resolve().relative_to(base).as_posix())
        receipt = current / "receipt.json"
        if _inside_project(base, receipt):
            receipts.append(receipt.resolve().relative_to(base).as_posix())
    return sorted(packages), sorted(receipts)


def file_manager_command(root: Path) -> list[str]:
    """Command that opens ``root`` in the system file manager.

    macOS uses ``open``. Linux uses ``xdg-open``. Windows is intentionally
    unsupported until a later slice.
    """

    resolved = str(root.resolve())
    if sys.platform == "darwin":
        return ["open", resolved]
    if sys.platform == "win32":
        raise OSError("Windows folder open is not implemented; use macOS open or Linux xdg-open")
    return ["xdg-open", resolved]


def _recent_file(server: ThreadingHTTPServer) -> Path:
    configured = getattr(server, "recent_path", None)
    if configured:
        return Path(configured)
    return Path.cwd() / RECENT_FILE_NAME


def _read_recent(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    paths = payload.get("paths") if isinstance(payload, dict) else None
    if not isinstance(paths, list):
        return []
    return [item for item in paths if isinstance(item, str)]


def _remember_recent(path: Path, project: Path) -> None:
    resolved = str(project.resolve())
    paths = [resolved] + [item for item in _read_recent(path) if item != resolved]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"paths": paths[:_MAX_RECENT]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _default_opener(command: list[str]) -> None:
    subprocess.run(command, check=False)


def build_progress(
    *,
    music_ready: bool,
    analysis_ready: bool,
    confirmed_ready: bool,
    export_ready: bool,
) -> dict:
    """Four Chinese steps. ``next`` is the first step that is not done."""

    flags = (music_ready, analysis_ready, confirmed_ready, export_ready)
    steps = []
    nxt = None
    for spec, done in zip(_PROGRESS_STEPS, flags, strict=True):
        steps.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "meaning": spec["meaning"],
                "state": "完成" if done else "未完成",
            }
        )
        if nxt is None and not done:
            nxt = {
                "id": spec["id"],
                "title": spec["title"],
                "instruction": spec["instruction"],
            }
    return {"steps": steps, "next": nxt}


def collect_hints(*groups: list[str]) -> list[str]:
    """Keep the first copy of each CLI hint."""

    seen: list[str] = []
    for group in groups:
        for hint in group:
            if hint and hint not in seen:
                seen.append(hint)
    return seen


def _resolved_project(project: Path) -> tuple[str, str]:
    full = str(Path(project).expanduser().resolve())
    name = Path(full).name or full
    return name, full


def render_project_page(project: Path) -> str:
    name, full = _resolved_project(project)
    page = _PROJECT_PAGE_TEMPLATE.replace("__STYLE__", _PAGE_STYLE)
    page = page.replace("__PROJECT_NAME__", html.escape(name))
    page = page.replace("__PROJECT_PATH__", html.escape(full))
    return page


def _validation_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for item in exc.errors():
            loc = ".".join(str(part) for part in item.get("loc") or () if str(part) != "")
            message = str(item.get("msg", ""))
            if message.startswith("Value error, "):
                message = message.removeprefix("Value error, ")
            if loc and message:
                parts.append(f"{loc}: {message}")
            elif message:
                parts.append(message)
        return "; ".join(parts) or "invalid regions"
    return str(exc)


def _classify_failure(exc: Exception) -> tuple[int, str]:
    """Map a render failure to a status and a Chinese explanation."""

    if isinstance(exc, ValidationError):
        detail = _validation_message(exc)
        blob = f"{detail} {exc}"
        if "json_invalid" in blob or "Invalid JSON" in blob:
            return 400, f"分段文件不是合法的 JSON。{detail}"
        return 400, f"分段文件有无法识别的字段或格式。{detail}"
    if isinstance(exc, ProjectConflict):
        text = str(exc)
        if "drifted" in text:
            key = text.split(":", 1)[-1].strip()
            return 409, f"分段版本文件的校验和变了：{key}。文件和记录对不上。"
        return 409, f"项目文件冲突：{text}"
    return 500, f"页面渲染失败（{type(exc).__name__}）：{exc}"


def _error_page(status: int, message: str, hint: str) -> ServeResponse:
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>确认台 · 出错了</title>
  <style>{_PAGE_STYLE}</style>
</head>
<body>
  <main>
    <h1>这一页打不开</h1>
    <section id="error" class="panel">{html.escape(message)}</section>
    <p>可以在终端运行：</p>
    <code id="hint">{html.escape(hint)}</code>
    <p><a href="/">返回项目</a></p>
  </main>
</body>
</html>
"""
    return ServeResponse(status, page.encode("utf-8"), "text/html; charset=utf-8")


def _failure_response(target: str, exc: Exception, project: Path) -> ServeResponse:
    status, message = _classify_failure(exc)
    hint = _regions_hint(project)
    path = unquote(urlsplit(target).path)
    if path.startswith("/api") or path.startswith("/audio"):
        return _error(status, message, hint)
    return _error_page(status, message, hint)


def _query_value(query: str, name: str) -> str | None:
    values = parse_qs(query, keep_blank_values=False).get(name)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def playback_span_step(
    current: float,
    start: float,
    end: float,
    looping: bool,
    tolerance: float = _PLAYBACK_TOLERANCE,
) -> str:
    """What the playhead should do for one selected span.

    ``seek`` jumps to the span start. ``pause`` stops when looping is off and
    the playhead has reached the end. ``continue`` leaves playback alone.
    ``tolerance`` covers ``timeupdate`` arriving slightly after the end.
    """

    if current >= end - tolerance:
        return "seek" if looping else "pause"
    if current < start - tolerance:
        return "seek"
    return "continue"


def clamp_seek(seconds: float, duration: float) -> float:
    """Keep a playhead inside the track."""

    duration = max(0.0, float(duration))
    seconds = float(seconds)
    if seconds < 0.0:
        return 0.0
    if seconds > duration:
        return duration
    return seconds


def seek_from_fraction(fraction: float, duration: float) -> float:
    """Map a 0–1 click on a full-length lane to a time."""

    fraction = float(fraction)
    if fraction < 0.0:
        fraction = 0.0
    if fraction > 1.0:
        fraction = 1.0
    return clamp_seek(fraction * max(0.0, float(duration)), duration)


def neighbor_mark(marks: list[float], current: float, step: int) -> float:
    """Next mark strictly after ``current``, or the previous one when ``step`` is negative.

    An empty list, or no mark on that side, leaves ``current`` where it is.
    """

    ordered = sorted(float(mark) for mark in marks)
    current = float(current)
    if not ordered:
        return current
    epsilon = 1e-3
    if step >= 0:
        for mark in ordered:
            if mark > current + epsilon:
                return mark
        return current
    for mark in reversed(ordered):
        if mark < current - epsilon:
            return mark
    return current


def detail_window(playhead: float, duration: float, half: float = 4.0) -> tuple[float, float]:
    """An 8 second window centered on the playhead, clamped inside the track.

    Near either end the window stays 8 seconds when the track is longer than
    that, so the playhead is not always in the middle. A shorter track is the
    whole file.
    """

    duration = max(0.0, float(duration))
    playhead = clamp_seek(playhead, duration)
    window = max(0.0, float(half) * 2.0)
    if duration <= window:
        return (0.0, duration)
    start = playhead - window / 2.0
    end = playhead + window / 2.0
    if start < 0.0:
        return (0.0, window)
    if end > duration:
        return (duration - window, duration)
    return (start, end)


def _load_candidate_regions(paths: ProjectPaths) -> MusicEditRegions | None:
    if not _regions_present(paths):
        return None
    return MusicEditRegions.model_validate_json(paths.music_edit_regions.read_text(encoding="utf-8"))


def _region_view(region: MusicEditRegion) -> dict:
    payload = region.model_dump(mode="json")
    payload["kind_label"] = KIND_LABELS.get(region.edit_role, region.edit_role)
    payload["source"] = "user" if region.evidence_basis == "manual" else "analyzer"
    return payload


def _warning_views(codes: list[str], cluster_times: list[float] | None = None) -> list[dict[str, str]]:
    views = []
    for code in codes:
        label = WARNING_LABELS.get(code, "这条分析提示需要看一下")
        if code == "downbeat_cluster" and cluster_times:
            shown = "、".join(f"{moment:.2f}" for moment in cluster_times[:8])
            if len(cluster_times) > 8:
                shown += "…"
            label = f"{label}（{shown}）"
        views.append({"code": code, "label": label})
    return views


def _version_label(status: str, version_id: str) -> str:
    serial = version_id.removeprefix("regions-")
    if status == "draft":
        return f"草稿 {serial}"
    if status == "history":
        return f"历史确认 {serial}"
    return f"已确认 {serial}"


def _desk_view(paths: ProjectPaths, document) -> dict:
    listings = list_regions_versions(paths)
    listing_status = "draft" if document.status == "draft" else "confirmed"
    versions = []
    for item in listings:
        if item.version_id == document.version_id:
            listing_status = item.status
        versions.append(
            {
                **item.model_dump(mode="json"),
                "label": _version_label(item.status, item.version_id),
            }
        )
    unknown = [region.region_id for region in document.regions.regions if region.edit_role == "unknown"]
    blockers = _confirm_blockers(document.regions)
    stored = document.regions
    read_only = listing_status != "draft"
    display = stored
    if not read_only and stored.beats and stored.bpm:
        from director.shot_slots import plan_shot_slots

        display = plan_shot_slots(stored)
    from director.shot_slots import drop_contrast_zh, snapshot_notice

    return {
        "revision": document.regions_sha256,
        "version_id": document.version_id,
        "edited_at": document.edited_at,
        "duration_seconds": document.regions.duration_seconds,
        "warnings": _warning_views(list(display.warnings), list(display.downbeat_cluster_times)),
        "regions": [_region_view(region) for region in display.regions],
        "read_only": read_only,
        "status": listing_status,
        "snapshot_notice": snapshot_notice(stored, read_only=read_only),
        "source_music_sha8": document.source_music_sha8,
        "confirmed_at": document.confirmed_at,
        "has_draft": any(item.status == "draft" for item in listings),
        "acceptance": {
            "ok": not blockers,
            "unknown_region_ids": unknown,
            "blockers": blockers,
        },
        "versions": versions,
        "bpm": display.bpm,
        "beats_seconds": list(display.beats_seconds),
        "downbeats_seconds": list(display.downbeats_seconds),
        "downbeat_cluster_times": list(display.downbeat_cluster_times),
        "provider": display.provider,
        "shot_style": display.shot_style or "narrative",
        "shot_rules_version": display.shot_rules_version,
        "drop_contrast_zh": drop_contrast_zh(display),
        "shot_slots": [slot.model_dump(mode="json") for slot in display.shot_slots],
        "phrases": [phrase.model_dump(mode="json") for phrase in display.phrases],
        "region_cut_anchors": [
            anchor.model_dump(mode="json") for anchor in display.region_cut_anchors
        ],
        "breath_marks": list(display.breath_marks),
        "beat_grid": (
            display.beat_grid.model_dump(mode="json") if display.beat_grid is not None else None
        ),
        "beat_backend": display.beat_backend,
        "beat_backend_note": display.beat_backend_note,
        "downbeat_confidence": display.downbeat_confidence,
        "downbeat_detector": display.downbeat_detector,
        "schema_version": display.schema_version,
        "confidence": display.confidence,
    }


def _ensure_draft(paths: ProjectPaths) -> tuple[object | None, ServeResponse | None]:
    with _DRAFT_LOCK:
        return _ensure_draft_unlocked(paths)


def _ensure_draft_unlocked(paths: ProjectPaths) -> tuple[object | None, ServeResponse | None]:
    draft = load_regions_draft(paths)
    if draft is not None:
        return draft, None
    candidates = _load_candidate_regions(paths)
    if candidates is None:
        return None, _error(404, "music_edit_regions.json is missing", _regions_hint(paths.root))
    try:
        return save_regions_draft(paths, candidates), None
    except (ValidationError, ValueError, RegionsVersionError, ProjectConflict) as exc:
        return None, _error(400, _validation_message(exc), _regions_hint(paths.root))


def _apply_role_edits(base: MusicEditRegions, payload: list) -> MusicEditRegions:
    """Apply edit_role changes. Every other field, add, and delete is refused."""

    if not isinstance(payload, list) or len(payload) != len(base.regions):
        raise ValueError(_ROLE_ONLY)
    current = {region.region_id: region for region in base.regions}
    chosen: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"region_id", "edit_role"}:
            raise ValueError(_ROLE_ONLY)
        region_id = item["region_id"]
        role = item["edit_role"]
        if not isinstance(region_id, str) or not isinstance(role, str):
            raise ValueError(_ROLE_ONLY)
        if region_id not in current or region_id in chosen or role not in KIND_LABELS:
            raise ValueError(_ROLE_ONLY)
        chosen[region_id] = role
    if set(chosen) != set(current):
        raise ValueError(_ROLE_ONLY)
    updated: list[MusicEditRegion] = []
    changed = False
    for region in base.regions:
        role = chosen[region.region_id]
        if role != region.edit_role:
            changed = True
            region = region.model_copy(update={"edit_role": role, "evidence_basis": "manual"})
        updated.append(region)
    document = base.model_copy(update={"regions": updated})
    if changed and document.beats:
        from director.shot_slots import plan_shot_slots

        document = plan_shot_slots(document)
    return document


def _client_write_path(payload: dict) -> bool:
    return any(isinstance(payload.get(key), str) and str(payload.get(key)).strip() for key in _CLIENT_PATH_KEYS)


def _select_desk_unlocked(
    paths: ProjectPaths, version_id: str | None
) -> tuple[dict | None, ServeResponse | None]:
    """Pick the draft, or the latest confirmed snapshot once a lock exists.

    A draft is created from analyzer candidates only when the project has no
    confirmed version yet. Opening a locked version never rewrites it.
    """

    listings = list_regions_versions(paths)
    requested = (version_id or "").strip()
    draft_listing = next((item for item in listings if item.status == "draft"), None)
    latest = next((item for item in listings if item.status == "confirmed"), None)
    if requested == "draft":
        if draft_listing is None:
            return None, _error(404, "没有打开的草稿。", _regions_hint(paths.root))
        document = load_regions_version(paths, draft_listing.version_id)
        return _desk_view(paths, document), None
    if requested:
        match = next((item for item in listings if item.version_id == requested), None)
        if match is None:
            return None, _error(404, f"没有这个分段版本：{requested}", _regions_hint(paths.root))
        document = load_regions_version(paths, requested)
        return _desk_view(paths, document), None
    if draft_listing is not None:
        document = load_regions_version(paths, draft_listing.version_id)
        return _desk_view(paths, document), None
    if latest is not None:
        document = load_regions_version(paths, latest.version_id)
        return _desk_view(paths, document), None
    draft, failure = _ensure_draft_unlocked(paths)
    if failure is not None or draft is None:
        return None, failure
    return _desk_view(paths, draft), None


def _music_desk_response(project: Path, version_id: str | None = None) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    with _DRAFT_LOCK:
        view, failure = _select_desk_unlocked(paths, version_id)
    if failure is not None or view is None:
        assert failure is not None
        return failure
    return _json_response(200, view)


def _save_draft_request(project: Path, body: bytes) -> ServeResponse:
    with _DRAFT_LOCK:
        return _save_draft_unlocked(project, body)


def _save_draft_unlocked(project: Path, body: bytes) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    try:
        payload = _json_body(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _error(400, f"invalid draft request: {exc}", "POST /api/regions-draft")
    if _client_write_path(payload):
        return _error(
            400,
            "refusing to write a client path; drafts stay inside the project root",
            "POST /api/regions-draft",
        )
    extra = set(payload) - {"expected_revision", "regions", "version_id"}
    if extra:
        return _error(400, _ROLE_ONLY, "POST /api/regions-draft")
    regions_payload = payload.get("regions")
    if not isinstance(regions_payload, list):
        return _error(400, _ROLE_ONLY, "POST /api/regions-draft")
    expected = payload.get("expected_revision")
    requested_version = payload.get("version_id")
    confirmed_ids = [
        item.version_id
        for item in list_regions_versions(paths)
        if item.status in {"confirmed", "history"}
    ]
    if isinstance(requested_version, str) and requested_version in confirmed_ids:
        return _error(409, "已确认的版本不能修改。", "GET /music")
    draft = load_regions_draft(paths)
    if draft is None and confirmed_ids:
        return _error(409, "已确认的版本不能修改。", "GET /music")
    if draft is None:
        base = _load_candidate_regions(paths)
        if base is None:
            return _error(404, "music_edit_regions.json is missing", _regions_hint(paths.root))
        if expected not in (None, ""):
            return _error(409, _STALE_REVISION, "GET /api/music-desk")
    else:
        if expected != draft.regions_sha256:
            return _error(409, _STALE_REVISION, "GET /api/music-desk")
        base = draft.regions
    try:
        updated = _apply_role_edits(base, regions_payload)
        saved = save_regions_draft(paths, updated)
    except (ValidationError, ValueError, RegionsVersionError, ProjectConflict) as exc:
        return _error(400, _validation_message(exc), "POST /api/regions-draft")
    return _json_response(200, _desk_view(paths, saved))


def _discard_draft_request(project: Path, body: bytes) -> ServeResponse:
    with _DRAFT_LOCK:
        return _discard_draft_unlocked(project, body)


def _discard_draft_unlocked(project: Path, body: bytes) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    try:
        payload = _json_body(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _error(400, f"invalid discard request: {exc}", "POST /api/regions-draft/discard")
    if _client_write_path(payload):
        return _error(
            400,
            "refusing to write a client path; drafts stay inside the project root",
            "POST /api/regions-draft/discard",
        )
    draft = load_regions_draft(paths)
    if draft is None:
        return _error(404, "no draft to discard", _regions_hint(paths.root))
    if payload.get("expected_revision") != draft.regions_sha256:
        return _error(409, _STALE_REVISION, "GET /api/music-desk")
    baseline = discard_regions_draft(paths)
    return _json_response(
        200,
        {"discarded": True, "baseline": baseline.model_dump(mode="json"), "revision": None},
    )


def _confirm_error(exc: RegionsVersionError) -> tuple[int, str]:
    text = str(exc)
    if "nothing to confirm" in text:
        return 400, "没有可确认的草稿。"
    if "force-confirm requires" in text:
        return 400, "强制确认需要填写原因。"
    if "reason is only accepted" in text:
        return 400, "原因只在强制确认时才记录。请打开强制确认。"
    if text.startswith("confirm refused:"):
        detail = text.removeprefix("confirm refused:").strip()
        marker = "unknown regions:"
        if marker in detail:
            ids = detail.split(marker, 1)[1].split(";")[0].strip()
            return 400, f"这些分段的角色还没定：{ids}。普通确认已停用。"
        return 400, f"还不能确认：{detail}。普通确认已停用，可打开强制确认并填写原因。"
    return 400, f"确认失败：{text}"


def _confirm_draft_request(project: Path, body: bytes) -> ServeResponse:
    with _DRAFT_LOCK:
        return _confirm_draft_unlocked(project, body)


def _confirm_draft_unlocked(project: Path, body: bytes) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    try:
        payload = _json_body(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _error(400, f"invalid confirm request: {exc}", "POST /api/regions-draft/confirm")
    if _client_write_path(payload):
        return _error(
            400,
            "refusing to write a client path; drafts stay inside the project root",
            "POST /api/regions-draft/confirm",
        )
    draft = load_regions_draft(paths)
    if draft is None:
        return _error(400, "没有可确认的草稿。", _regions_hint(paths.root))
    if payload.get("expected_revision") != draft.regions_sha256:
        return _error(409, _STALE_REVISION, "GET /api/music-desk")
    force = bool(payload.get("force"))
    reason = payload.get("reason")
    try:
        confirm_regions_draft(paths, force=force, reason=reason if isinstance(reason, str) else None)
    except RegionsVersionError as exc:
        status, message = _confirm_error(exc)
        return _error(status, message, _regions_hint(paths.root))
    document = load_regions_version(paths, draft.version_id)
    return _json_response(200, _desk_view(paths, document))


_DRAFT_OPEN = "已经有打开的草稿。先确认或丢弃它，再基于确认版另开。"


def _adopt_boundaries_request(project: Path, body: bytes) -> ServeResponse:
    with _DRAFT_LOCK:
        return _adopt_boundaries_unlocked(project, body)


def _adopt_boundaries_unlocked(project: Path, body: bytes) -> ServeResponse:
    """Apply pending boundary suggestions. Confirmed bytes stay untouched."""

    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    try:
        payload = _json_body(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _error(400, f"invalid adopt request: {exc}", "POST /api/regions-draft/adopt-boundaries")
    if _client_write_path(payload):
        return _error(
            400,
            "refusing to write a client path; drafts stay inside the project root",
            "POST /api/regions-draft/adopt-boundaries",
        )
    extra = set(payload) - {"expected_revision", "version_id", "boundaries"}
    if extra:
        return _error(400, "只能提交要采纳的边界。", "POST /api/regions-draft/adopt-boundaries")
    boundaries = payload.get("boundaries")
    if boundaries == "all":
        ids = None
    elif isinstance(boundaries, list) and all(isinstance(item, str) and item.strip() for item in boundaries):
        ids = {item.strip() for item in boundaries}
    else:
        return _error(400, "要写明采纳哪些边界：all，或分段 id 列表。", "POST /api/regions-draft/adopt-boundaries")
    version_id = payload.get("version_id")
    if not isinstance(version_id, str) or not version_id.strip():
        return _error(400, "要写明基于哪一版分段采纳边界。", "POST /api/regions-draft/adopt-boundaries")
    version_id = version_id.strip()
    try:
        document = load_regions_version(paths, version_id)
    except RegionsVersionError:
        return _error(404, f"没有这个分段版本：{version_id}", _regions_hint(paths.root))
    if payload.get("expected_revision") != document.regions_sha256:
        return _error(409, _STALE_REVISION, "GET /api/music-desk")
    from director.shot_slots import apply_boundary_snaps

    updated = apply_boundary_snaps(document.regions, ids)
    unchanged = updated.model_dump() == document.regions.model_dump()
    if document.status == "draft":
        if unchanged:
            return _json_response(200, _desk_view(paths, document))
        try:
            saved = save_regions_draft(paths, updated)
        except (ValidationError, ValueError, RegionsVersionError, ProjectConflict) as exc:
            return _error(400, _validation_message(exc), "POST /api/regions-draft/adopt-boundaries")
        return _json_response(200, _desk_view(paths, saved))
    if document.status not in {"confirmed", "history"}:
        return _error(409, "只能在草稿里改，或基于已确认的版本另开草稿。", "GET /music")
    if load_regions_draft(paths) is not None:
        return _error(409, _DRAFT_OPEN, "GET /music")
    if unchanged:
        return _json_response(200, _desk_view(paths, document))
    try:
        saved = save_regions_draft(paths, updated)
    except (ValidationError, ValueError, RegionsVersionError, ProjectConflict) as exc:
        return _error(400, _validation_message(exc), "POST /api/regions-draft/adopt-boundaries")
    return _json_response(200, _desk_view(paths, saved))


def _shot_style_request(project: Path, body: bytes) -> ServeResponse:
    with _DRAFT_LOCK:
        return _shot_style_unlocked(project, body)


def _shot_style_unlocked(project: Path, body: bytes) -> ServeResponse:
    """Replan the shot track. Confirmed bytes stay untouched."""

    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    try:
        payload = _json_body(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _error(400, f"invalid shot-style request: {exc}", "POST /api/regions-draft/shot-style")
    if _client_write_path(payload):
        return _error(
            400,
            "refusing to write a client path; drafts stay inside the project root",
            "POST /api/regions-draft/shot-style",
        )
    extra = set(payload) - {"expected_revision", "version_id", "style"}
    if extra:
        return _error(400, "只能提交剪法。", "POST /api/regions-draft/shot-style")
    style = payload.get("style")
    if style not in {"narrative", "travel", "event"}:
        return _error(400, "剪法只能是慢叙事、旅拍快剪或活动快剪。", "POST /api/regions-draft/shot-style")
    version_id = payload.get("version_id")
    if not isinstance(version_id, str) or not version_id.strip():
        return _error(400, "要写明基于哪一版分段更换剪法。", "POST /api/regions-draft/shot-style")
    version_id = version_id.strip()
    try:
        document = load_regions_version(paths, version_id)
    except RegionsVersionError:
        return _error(404, f"没有这个分段版本：{version_id}", _regions_hint(paths.root))
    if payload.get("expected_revision") != document.regions_sha256:
        return _error(409, _STALE_REVISION, "GET /api/music-desk")
    if not document.regions.beats or not document.regions.bpm:
        return _error(400, "还没有节拍，不能换剪法。", "POST /api/regions-draft/shot-style")
    current = document.regions.shot_style or "narrative"
    if current == style:
        return _json_response(200, _desk_view(paths, document))
    from director.shot_slots import plan_shot_slots

    try:
        updated = plan_shot_slots(
            document.regions.model_copy(update={"shot_style": style, "shot_rules_version": None}),
            style=style,
        )
    except (ValidationError, ValueError) as exc:
        return _error(400, _validation_message(exc), "POST /api/regions-draft/shot-style")
    if document.status == "draft":
        try:
            saved = save_regions_draft(paths, updated)
        except (ValidationError, ValueError, RegionsVersionError, ProjectConflict) as exc:
            return _error(400, _validation_message(exc), "POST /api/regions-draft/shot-style")
        return _json_response(200, _desk_view(paths, saved))
    if document.status not in {"confirmed", "history"}:
        return _error(409, "只能在草稿里改，或基于已确认的版本另开草稿。", "GET /music")
    if load_regions_draft(paths) is not None:
        return _error(409, _DRAFT_OPEN, "GET /music")
    try:
        saved = save_regions_draft(paths, updated)
    except (ValidationError, ValueError, RegionsVersionError, ProjectConflict) as exc:
        return _error(400, _validation_message(exc), "POST /api/regions-draft/shot-style")
    return _json_response(200, _desk_view(paths, saved))


def _draft_from_confirmed_request(project: Path, body: bytes) -> ServeResponse:
    with _DRAFT_LOCK:
        return _draft_from_confirmed_unlocked(project, body)


def _draft_from_confirmed_unlocked(project: Path, body: bytes) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    try:
        payload = _json_body(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _error(400, f"invalid draft request: {exc}", "POST /api/regions-draft/from-confirmed")
    if _client_write_path(payload):
        return _error(
            400,
            "refusing to write a client path; drafts stay inside the project root",
            "POST /api/regions-draft/from-confirmed",
        )
    version_id = payload.get("version_id")
    if not isinstance(version_id, str) or not version_id.strip():
        return _error(400, "要写明基于哪一版已确认分段另开草稿。", "POST /api/regions-draft/from-confirmed")
    version_id = version_id.strip()
    if load_regions_draft(paths) is not None:
        return _error(409, _DRAFT_OPEN, "GET /music")
    try:
        document = load_regions_version(paths, version_id)
    except RegionsVersionError:
        return _error(404, f"没有这个分段版本：{version_id}", _regions_hint(paths.root))
    if document.status != "confirmed":
        return _error(409, "只能基于已确认的版本另开草稿。", "GET /music")
    from director.shot_slots import confirmed_snapshot_should_replan, plan_shot_slots

    regions = document.regions
    if not regions.shot_track_locked:
        try:
            saved = migrate_unlocked_confirmed_regions(paths, version_id)
        except RegionsVersionError as exc:
            return _error(409, str(exc), "GET /music")
        return _json_response(200, _desk_view(paths, saved))
    if confirmed_snapshot_should_replan(regions):
        regions = plan_shot_slots(regions)
    saved = save_regions_draft(paths, regions)
    return _json_response(200, _desk_view(paths, saved))


def _regions_export_request(project: Path, body: bytes) -> ServeResponse:
    from director.music_edit_regions_versions import (
        RegionsConfirmGateError,
        export_fcpxml_for_confirmed_regions,
    )
    from director.regions_fcpxml import JIANYING_FCPXML_NOTICE

    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    try:
        payload = _json_body(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _error(400, f"invalid export request: {exc}", "POST /api/regions-export")
    if _client_write_path(payload):
        return _error(
            400,
            "refusing to write a client path; the package stays inside the project root",
            "POST /api/regions-export",
        )
    version_id = payload.get("version_id")
    if not isinstance(version_id, str) or not version_id.strip():
        return _error(400, "要写明导出哪一版已确认分段。", "POST /api/regions-export")
    version_id = version_id.strip()
    output = paths.root / "delivery" / "regions" / version_id
    try:
        result = export_fcpxml_for_confirmed_regions(paths, version_id, output)
    except RegionsConfirmGateError:
        return _error(400, "草稿不能导出。请先确认。", "POST /api/regions-export")
    except RegionsVersionError as exc:
        return _error(400, str(exc), "POST /api/regions-export")
    except ProjectConflict as exc:
        return _error(409, str(exc), "POST /api/regions-export")
    root = paths.root.resolve()
    return _json_response(
        200,
        {
            "version_id": result.version_id,
            "fcpxml": result.fcpxml_path.resolve().relative_to(root).as_posix(),
            "sheet": result.sheet_path.resolve().relative_to(root).as_posix(),
            "frame_rate": result.frame_rate,
            "notice": JIANYING_FCPXML_NOTICE,
        },
    )


def render_music_page(
    project: Path,
    version_id: str | None = None,
    *,
    selected: str | None = None,
    playhead: str | None = None,
) -> str:
    from director.music_timeline import brief_title, render_timeline_page

    name, full = _resolved_project(project)
    paths, error = _open(project)
    view = None
    message = ""
    if error is not None:
        payload = json.loads(error.body.decode("utf-8"))
        message = str(payload.get("error") or "")
    else:
        assert paths is not None
        with _DRAFT_LOCK:
            view, failure = _select_desk_unlocked(paths, version_id)
        if failure is not None or view is None:
            assert failure is not None
            payload = json.loads(failure.body.decode("utf-8"))
            message = str(payload.get("error") or "")
            view = None
    title = name if paths is None else brief_title(paths.brief, name)
    track_label = "未导入配乐"
    if paths is not None and view is not None:
        frozen = _frozen_music(paths)
        if frozen is not None:
            track_label = Path(frozen[1].frozen_relative_path).name
    family = list_music_family(paths.root) if paths is not None else []
    return render_timeline_page(
        project_title=title,
        project_id=name,
        project_path=full,
        track_label=track_label,
        view=view,
        message=message,
        selected=selected,
        playhead=playhead,
        kind_labels=KIND_LABELS,
        snap_labels=SNAP_LABELS,
        warning_labels=WARNING_LABELS,
        music_family=family,
    )


def project_status(project: Path) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    try:
        frozen = _frozen_music(paths)
    except (FrozenMusicPathError, ProjectConflict) as exc:
        return _error(400, str(exc), _music_hint(paths.root))
    regions_present = _regions_present(paths)
    listings = list_regions_versions(paths)
    confirmed = [item for item in listings if item.status == "confirmed"]
    fcpxml_paths, receipt_paths = _discover_fcpxml(paths.root)
    missing: list[dict[str, str]] = []
    if frozen is None:
        missing.append({"artifact": "frozen_music", "hint": _music_hint(paths.root)})
    if not regions_present:
        missing.append({"artifact": "music_edit_regions", "hint": _regions_hint(paths.root)})
    asset = frozen[1] if frozen is not None else None
    state = load_project_state(paths)
    payload = {
        "project_path": str(paths.root.resolve()),
        "project_id": state.project_id,
        "frozen_music": {
            "present": asset is not None,
            "relative_path": None if asset is None else asset.frozen_relative_path,
            "source_sha256": None if asset is None else asset.source_sha256,
            "source_sha8": None if asset is None else asset.source_sha256[:8],
            "mime_type": None if asset is None else asset.mime_type,
            "duration_seconds": None if asset is None else asset.duration_seconds,
            "audio_url": None if asset is None else "/audio/frozen",
        },
        "music_edit_regions": {
            "present": regions_present,
            "path": "music_edit_regions.json",
            "hint": None if regions_present else _regions_hint(paths.root),
        },
        "regions_versions": {
            "draft_count": sum(item.status == "draft" for item in listings),
            "confirmed_count": len(confirmed),
            "history_count": sum(item.status == "history" for item in listings),
            "latest_confirmed_id": None if not confirmed else confirmed[-1].version_id,
        },
        "fcpxml": {
            "present": bool(fcpxml_paths),
            "paths": fcpxml_paths,
            "receipt_present": bool(receipt_paths),
            "receipt_paths": receipt_paths,
        },
        "missing": missing,
        "project_name": paths.root.name,
        "hints": collect_hints(
            [item["hint"] for item in missing],
            [] if regions_present else [_regions_hint(paths.root)],
        ),
        "progress": build_progress(
            music_ready=asset is not None,
            analysis_ready=regions_present,
            confirmed_ready=bool(confirmed),
            export_ready=bool(fcpxml_paths),
        ),
    }
    return _json_response(200, payload)


def _regions_document(project: Path) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    if not _regions_present(paths):
        return _error(404, "music_edit_regions.json is missing", _regions_hint(paths.root))
    payload = json.loads(paths.music_edit_regions.read_text(encoding="utf-8"))
    return _json_response(200, payload)


def _version_list(project: Path) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    versions = [item.model_dump(mode="json") for item in list_regions_versions(paths)]
    return _json_response(200, {"versions": versions})


def _version_one(project: Path, version_id: str) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    hint = _regions_hint(paths.root)
    if version_id == "draft":
        draft = load_regions_draft(paths)
        if draft is None:
            return _error(404, "no regions draft is open", hint)
        return _json_response(200, draft.model_dump(mode="json"))
    if not _VERSION_ID_RE.fullmatch(version_id):
        return _error(404, f"unknown regions version: {version_id}", hint)
    try:
        document = load_regions_version(paths, version_id)
    except RegionsVersionError as exc:
        return _error(404, str(exc), hint)
    return _json_response(200, document.model_dump(mode="json"))


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Return an inclusive byte span, None for the whole file, or raise ValueError."""

    if header is None:
        return None
    match = _RANGE_RE.fullmatch(header.strip())
    if match is None or size <= 0:
        raise ValueError("unsatisfiable range")
    start_text, end_text = match.group(1), match.group(2)
    if start_text == "" and end_text == "":
        raise ValueError("unsatisfiable range")
    if start_text == "":
        suffix = int(end_text)
        if suffix <= 0:
            raise ValueError("unsatisfiable range")
        length = min(suffix, size)
        return size - length, size - 1
    start = int(start_text)
    end = size - 1 if end_text == "" else int(end_text)
    if start >= size or start > end:
        raise ValueError("unsatisfiable range")
    return start, min(end, size - 1)


def _audio(project: Path, range_header: str | None) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    try:
        frozen = _frozen_music(paths)
    except FrozenMusicPathError as exc:
        return _error(400, str(exc), "frozen music must stay inside the project")
    except ProjectConflict as exc:
        return _error(409, str(exc), _music_hint(paths.root))
    if frozen is None:
        return _error(404, "frozen music is missing", _music_hint(paths.root))
    path, asset = frozen
    size = path.stat().st_size
    try:
        span = _parse_range(range_header, size)
    except ValueError:
        refused = _error(416, "unsatisfiable range", "Range: bytes=0-")
        refused.headers["Content-Range"] = f"bytes */{size}"
        return refused
    start, end = (0, size - 1) if span is None else span
    with path.open("rb") as source:
        source.seek(start)
        chunk = source.read(end - start + 1)
    status = 200 if span is None else 206
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{size}",
    }
    return ServeResponse(status, chunk, asset.mime_type, headers)


def _json_body(body: bytes) -> dict:
    if not body.strip():
        return {}
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    return payload


def _switch_project(server: ThreadingHTTPServer, body: bytes) -> ServeResponse:
    try:
        payload = _json_body(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _error(400, f"invalid project request: {exc}", "POST /api/project")
    raw = payload.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return _error(400, "project path is required", "POST /api/project {\"path\": \"/absolute/project\"}")
    resolved = Path(raw.strip()).expanduser().resolve()
    server.project_root = str(resolved)  # type: ignore[attr-defined]
    status = project_status(resolved)
    if status.status == 200:
        _remember_recent(_recent_file(server), resolved)
    return status


def _reveal_project(server: ThreadingHTTPServer, body: bytes) -> ServeResponse:
    try:
        payload = _json_body(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _error(400, f"invalid reveal request: {exc}", "POST /api/reveal")
    project = Path(server.project_root)  # type: ignore[attr-defined]
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    root = paths.root.resolve()
    requested = payload.get("path")
    if requested not in (None, ""):
        if not isinstance(requested, str):
            return _error(400, "reveal path must be a string", "POST /api/reveal")
        resolved = Path(requested.strip()).expanduser().resolve()
        if resolved != root:
            return _error(
                400,
                "refusing to open a path that is not the project root",
                f"only the project root can be opened: {root}",
            )
    try:
        command = file_manager_command(root)
    except OSError as exc:
        return _error(501, str(exc), "macOS: open <project>; Linux: xdg-open <project>")
    opener: Callable[[list[str]], object] = getattr(server, "directory_opener", None) or _default_opener
    try:
        opener(command)
    except OSError as exc:
        return _error(500, str(exc), " ".join(command))
    return _json_response(200, {"opened": str(root), "command": command})


def _recent_response(server: ThreadingHTTPServer) -> ServeResponse:
    return _json_response(200, {"paths": _read_recent(_recent_file(server))})


def _html(page: str) -> ServeResponse:
    return ServeResponse(200, page.encode("utf-8"), "text/html; charset=utf-8")


_WAVESURFER_DIR = Path(__file__).resolve().parent / "vendor" / "wavesurfer"


def _waveform_peaks_response(project: Path) -> ServeResponse:
    """Serve cached display peaks for the frozen track. Not a project artifact."""

    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    frozen = _frozen_music(paths)
    if frozen is None:
        return _error(404, "还没有固定的配乐，画不出音量条。", _music_hint(paths.root))
    media, asset = frozen
    try:
        payload = load_or_build_peaks(media, asset.source_sha256)
    except (OSError, ValueError) as exc:
        return _error(
            500,
            f"音量条没能算出来：{exc}。需要 ffmpeg，或者 16-bit wav。",
            _music_hint(paths.root),
        )
    return _json_response(200, payload)


def _wavesurfer_file(relative: str) -> ServeResponse:
    """Serve a vendored wavesurfer file. Nothing is loaded from a CDN."""

    root = _WAVESURFER_DIR.resolve()
    if not relative or relative.endswith("/"):
        return _error(404, "unknown path", "GET /music")
    candidate = (root / relative).resolve()
    if not candidate.is_file() or not candidate.is_relative_to(root):
        return _error(404, "unknown path", "GET /music")
    if candidate.suffix.lower() == ".js":
        content_type = "text/javascript; charset=utf-8"
    else:
        content_type = "text/plain; charset=utf-8"
    return ServeResponse(200, candidate.read_bytes(), content_type)


def _header_value(headers: Mapping[str, str] | None, name: str) -> str:
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value
    return ""


def _music_import_request(
    server: ThreadingHTTPServer,
    headers: Mapping[str, str] | None,
    body: bytes,
    client_host: str | None,
) -> ServeResponse:
    if not is_loopback_host(client_host):
        return _error(403, "导入只接受本机请求。", "请在运行确认台的这台电脑上打开页面。")
    try:
        filename, payload = parse_music_upload(_header_value(headers, "content-type"), body)
    except ValueError as exc:
        return _error(400, str(exc), "选择 mp3、m4a 或 wav，且不超过 100MB。")
    project = Path(server.project_root)  # type: ignore[attr-defined]
    try:
        parent = resolve_family_parent(project)
        paths = open_project(parent)
        if load_music_evidence(paths) is None:
            raise ValueError("还没有固定的配乐，不能换音乐。")
    except FileNotFoundError:
        return _error(400, "当前目录不是一个项目。", "先打开已经有配乐的项目。")
    except (ProjectConflict, ValueError, OSError) as exc:
        return _error(400, chinese_import_error(exc), "先打开已经冻结配乐、并且视觉阶段完整的项目。")
    status = start_music_import(parent, filename, payload, import_jobs(server))
    return _json_response(202, status.as_dict())


def _music_import_status(server: ThreadingHTTPServer, query: str) -> ServeResponse:
    job_id = _query_value(query, "id")
    if not job_id:
        return _error(400, "缺少导入任务编号。", "GET /api/music-import/status?id=")
    status = import_jobs(server).get(job_id)
    if status is None:
        return _error(404, "没有这个导入任务。", "任务只留在这次确认台进程里。")
    return _json_response(200, status.as_dict())


def handle_confirm_request(
    server: ThreadingHTTPServer,
    method: str,
    target: str,
    headers: Mapping[str, str] | None = None,
    body: bytes = b"",
    client_host: str | None = None,
) -> ServeResponse:
    """Answer one confirm-desk request. ``target`` is the raw request path.

    Any exception becomes a Chinese HTML page or JSON body. The socket always
    gets a response.
    """

    project = Path(getattr(server, "project_root", "."))
    try:
        return _dispatch_confirm_request(server, method, target, headers, body, client_host)
    except Exception as exc:
        return _failure_response(target, exc, project)


def _dispatch_confirm_request(
    server: ThreadingHTTPServer,
    method: str,
    target: str,
    headers: Mapping[str, str] | None = None,
    body: bytes = b"",
    client_host: str | None = None,
) -> ServeResponse:
    project = Path(server.project_root)  # type: ignore[attr-defined]
    if _traversal_requested(target):
        return _error(400, "path traversal refused", "GET /audio/frozen")
    parsed = urlsplit(target)
    path = unquote(parsed.path)
    version = _query_value(parsed.query, "version")
    selected = _query_value(parsed.query, "sel")
    playhead = _query_value(parsed.query, "t")
    if method == "POST" and path == "/api/project":
        return _switch_project(server, body)
    if method == "POST" and path == "/api/reveal":
        return _reveal_project(server, body)
    if method == "POST" and path == "/api/regions-draft":
        return _save_draft_request(project, body)
    if method == "POST" and path == "/api/regions-draft/confirm":
        return _confirm_draft_request(project, body)
    if method == "POST" and path == "/api/regions-draft/from-confirmed":
        return _draft_from_confirmed_request(project, body)
    if method == "POST" and path == "/api/regions-draft/discard":
        return _discard_draft_request(project, body)
    if method == "POST" and path == "/api/regions-draft/adopt-boundaries":
        return _adopt_boundaries_request(project, body)
    if method == "POST" and path == "/api/regions-draft/shot-style":
        return _shot_style_request(project, body)
    if method == "POST" and path == "/api/regions-export":
        return _regions_export_request(project, body)
    if method == "POST" and path == "/api/music-import":
        return _music_import_request(server, headers, body, client_host)
    if method not in {"GET", "HEAD"}:
        return _error(405, "method is not allowed", "GET /api/status")
    if path == "/":
        return _html(render_project_page(project))
    if path == "/music":
        return _html(render_music_page(project, version, selected=selected, playhead=playhead))
    if path == "/api/waveform-peaks":
        return _waveform_peaks_response(project)
    vendor_prefix = "/vendor/wavesurfer/"
    if path.startswith(vendor_prefix):
        return _wavesurfer_file(path.removeprefix(vendor_prefix))
    if path == "/export":
        return _html(_EXPORT_HTML)
    if path == "/api/music-import/status":
        return _music_import_status(server, parsed.query)
    if path == "/api/music-desk":
        return _music_desk_response(project, version)
    if path == "/api/status":
        return project_status(project)
    if path == "/api/recent":
        return _recent_response(server)
    if path == "/api/regions-versions":
        return _version_list(project)
    if path == "/api/music-edit-regions":
        return _regions_document(project)
    prefix = "/api/regions-versions/"
    if path.startswith(prefix):
        return _version_one(project, path.removeprefix(prefix))
    if path == "/audio/frozen":
        header_map = {key.lower(): value for key, value in (headers or {}).items()}
        return _audio(project, header_map.get("range"))
    return _error(404, f"unknown path: {path}", "GET /api/status")


class _ConfirmDeskHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        self._serve("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        self._serve("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._serve("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._serve("DELETE")

    def _serve(self, method: str) -> None:
        body = b""
        peer = str(self.client_address[0]) if self.client_address else ""
        if method in {"POST", "PUT", "DELETE"}:
            path = unquote(urlsplit(self.path).path)
            importing = method == "POST" and path == "/api/music-import"
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = -1
            if importing and not is_loopback_host(peer):
                response = _error(403, "导入只接受本机请求。", "请在运行确认台的这台电脑上打开页面。")
                response.headers["Connection"] = "close"
                self.close_connection = True
                self._write(method, response)
                return
            limit = MAX_MUSIC_IMPORT_BYTES if importing else _MAX_BODY_BYTES
            if length < 0 or length > limit:
                if importing:
                    response = _error(
                        400,
                        "文件太大。导入上限是 100MB。",
                        "请换一首更短的 mp3、m4a 或 wav。",
                    )
                else:
                    response = _error(400, "request body is too large", "POST /api/project")
                response.headers["Connection"] = "close"
                self.close_connection = True
                self._write(method, response)
                return
            if length:
                body = self.rfile.read(length)
        try:
            response = handle_confirm_request(
                self.server,
                method,
                self.path,
                dict(self.headers.items()),
                body,
                client_host=peer,
            )
        except Exception as exc:
            root = Path(getattr(self.server, "project_root", "."))
            response = _failure_response(self.path, exc, root)
        self._write(method, response)

    def _write(self, method: str, response: ServeResponse) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(response.body)


def _configure_server(server: ThreadingHTTPServer, project: Path, recent_path: Path | None) -> None:
    server.daemon_threads = True
    server.project_root = str(project)  # type: ignore[attr-defined]
    server.recent_path = None if recent_path is None else str(recent_path)  # type: ignore[attr-defined]
    server.directory_opener = None  # type: ignore[attr-defined]


def start_confirm_desk(
    project: Path,
    host: str | None = None,
    port: int = 0,
    lan: bool = False,
    recent_path: Path | None = None,
) -> ThreadingHTTPServer:
    """Bind a daemon server and return it. ``port=0`` asks the OS for a free port."""

    bind_host = serve_bind_host(lan) if host is None else host
    server = ThreadingHTTPServer((bind_host, port), _ConfirmDeskHandler)
    _configure_server(server, project, recent_path)
    thread = threading.Thread(target=server.serve_forever, name="confirm-desk", daemon=True)
    thread.start()
    return server


def serve_confirm_desk(project: Path, *, host: str, port: int) -> None:
    """Serve until the process is interrupted. Used by ``travel-director serve``."""

    server = ThreadingHTTPServer((host, port), _ConfirmDeskHandler)
    _configure_server(server, project, None)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
