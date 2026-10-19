"""Local confirm desk: project page and thin music-region editor.

HTTP stack: the stdlib ``http.server.ThreadingHTTPServer``. One process, no
extra dependency, no authentication, and no upload. The default bind address
is ``127.0.0.1``. ``--lan`` binds ``0.0.0.0`` for other machines on the same
network. This is not a public internet service.

``/`` explains the desk in Chinese and shows four steps. ``/music`` lists the
open draft (created from analyzer candidates when none is open) and writes
that draft. ``/export`` says the export page is not open yet.

``POST /api/regions-draft`` replaces the draft when ``expected_revision``
matches. Writes go through the Slice 1 store, which renames a temp file into
the project. A client-supplied path is refused. ``POST /api/regions-draft/discard``
drops the open draft. This module does not confirm a version, re-run analysis,
or export.
"""

from __future__ import annotations

import html
import json
import math
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from director.audio_import import ImportedMusicAsset
from director.music_edit_regions_schema import MusicEditRegion, MusicEditRegions
from director.music_edit_regions_versions import (
    RegionsVersionError,
    discard_regions_draft,
    list_regions_versions,
    load_regions_draft,
    load_regions_version,
    save_regions_draft,
)
from director.project import ProjectConflict, ProjectPaths, _sha256_file, load_project_state, open_project


DEFAULT_BIND_HOST = "127.0.0.1"
LAN_BIND_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
RECENT_FILE_NAME = ".confirm-desk-recent.json"
_MAX_RECENT = 8
_MAX_BODY_BYTES = 65536

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_VERSION_ID_RE = re.compile(r"^regions-v[0-9]{2,}$")
_BOUNDARY_TOLERANCE = 0.001
_DRAFT_LOCK = threading.Lock()
_STALE_REVISION = "stale draft revision; refresh and edit again"
_VIEW_KEYS = frozenset({"kind_label", "source"})
_CLIENT_PATH_KEYS = ("path", "destination", "output", "target")

KIND_LABELS = {
    "hook": "可卡点",
    "establish": "前奏",
    "narrative_hold": "叙事",
    "build": "铺垫",
    "peak_cut": "高潮",
    "breath": "换气",
    "settle_outro": "收尾",
    "unknown": "未定",
}
_PROXY_FOR_ROLE = {
    "hook": "intro",
    "establish": "intro",
    "narrative_hold": "rise",
    "build": "rise",
    "peak_cut": "climax",
    "breath": "breath",
    "settle_outro": "outro",
    "unknown": "unknown",
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
        "instruction": "去音乐分段页听每一段，按需要改起点、终点和种类。",
    },
    {
        "id": "confirmed",
        "title": "分段已确认",
        "meaning": "已经有锁定的分段版本，导出时会用这一版。",
        "instruction": "分段改好后需要锁定确认版。确认锁定会在后续版本开放，当前可先保存草稿。",
    },
    {
        "id": "export",
        "title": "已导出剪映工程",
        "meaning": "剪映工程已经生成，可以拿去剪辑。",
        "instruction": "导出剪映工程会在后续版本开放。",
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
    input[type="text"], input[type="number"], select { width: 100%; box-sizing: border-box; padding: 0.35rem 0.45rem; font: inherit; }
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
    <p>导出：后续版本开放</p>
    <p><a href="/">返回项目</a></p>
  </main>
</body>
</html>
"""

_MUSIC_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>确认台 · 音乐分段</title>
  <style>__STYLE__</style>
</head>
<body>
  <header>
    <h1>音乐分段</h1>
    <nav>
      <a href="/">项目</a>
      <a href="/music" aria-current="page">音乐分段</a>
      <a href="/export">导出</a>
    </nav>
  </header>
  <main>
    <p class="lede">听每一段，改起点、终点和种类。这里只保存草稿。</p>
    <p class="project-name" id="project-name" title="__PROJECT_PATH__">__PROJECT_NAME__</p>
    <p class="project-path" id="project-path" title="__PROJECT_PATH__">__PROJECT_PATH__</p>
    <section id="error" class="panel" __ERROR_HIDDEN__>__ERROR_TEXT__</section>
    <div class="strip" id="strip">__STRIP__</div>
    <audio id="track" src="/audio/frozen" preload="metadata"></audio>
    <table>
      <thead>
        <tr><th>种类</th><th>开始</th><th>结束</th><th>把握</th><th>来源</th><th>启用</th><th></th></tr>
      </thead>
      <tbody id="region-body">__ROWS__</tbody>
    </table>
    <div class="actions">
      <button type="button" id="add-region">加一段</button>
      <button type="button" id="save">保存草稿</button>
      <button type="button" id="discard" class="secondary">丢弃草稿</button>
    </div>
    <p id="revision"></p>
  </main>
  <script type="application/json" id="desk-data">__DATA__</script>
  <script>
    var KIND = __KIND_JSON__;
    var PROXY = __PROXY_JSON__;
    var track = document.getElementById("track");
    var state = JSON.parse(document.getElementById("desk-data").textContent);
    function showError(text) {
      var box = document.getElementById("error");
      box.hidden = !text;
      box.textContent = text || "";
    }
    function sourceLabel(source) { return source === "user" ? "已修改" : "分析"; }
    function render() {
      var body = document.getElementById("region-body");
      var strip = document.getElementById("strip");
      body.textContent = "";
      strip.textContent = "";
      if (!state || !state.regions) return;
      var duration = state.duration_seconds || 1;
      state.regions.forEach(function (region, index) {
        var slice = document.createElement("span");
        slice.style.width = ((region.end - region.start) / duration * 100) + "%";
        slice.textContent = region.kind_label || KIND[region.edit_role] || region.edit_role;
        strip.appendChild(slice);
        var tr = document.createElement("tr");
        tr.addEventListener("click", function (event) { playRegion(region, event); });
        var kind = document.createElement("td");
        var select = document.createElement("select");
        Object.keys(KIND).forEach(function (role) {
          var option = document.createElement("option");
          option.value = role;
          option.textContent = KIND[role];
          option.selected = role === region.edit_role;
          select.appendChild(option);
        });
        select.addEventListener("change", function () {
          region.edit_role = select.value;
          region.musical_proxy = PROXY[select.value] || region.musical_proxy;
          region.kind_label = KIND[select.value];
          region.evidence_basis = "manual";
          region.source = "user";
          postDraft();
        });
        kind.appendChild(select);
        tr.appendChild(kind);
        ["start", "end"].forEach(function (field) {
          var cell = document.createElement("td");
          var input = document.createElement("input");
          input.type = "number";
          input.step = "0.01";
          input.value = String(region[field]);
          input.addEventListener("change", function () {
            var value = Number(input.value);
            if (!Number.isFinite(value)) { showError("时间要是有限数字"); return; }
            applyBound(index, field, value);
            postDraft();
          });
          cell.appendChild(input);
          tr.appendChild(cell);
        });
        var confidence = document.createElement("td");
        confidence.textContent = Number(region.confidence).toFixed(2);
        tr.appendChild(confidence);
        var source = document.createElement("td");
        source.textContent = sourceLabel(region.source);
        tr.appendChild(source);
        var enabled = document.createElement("td");
        var checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = region.enabled !== false;
        checkbox.addEventListener("change", function () {
          region.enabled = checkbox.checked;
          region.evidence_basis = "manual";
          region.source = "user";
          postDraft();
        });
        enabled.appendChild(checkbox);
        tr.appendChild(enabled);
        var actions = document.createElement("td");
        var play = document.createElement("button");
        play.type = "button";
        play.textContent = "试听";
        play.addEventListener("click", function (event) { playRegion(region, event); });
        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "secondary";
        remove.textContent = "删除";
        remove.addEventListener("click", function () { deleteRegion(index); });
        actions.appendChild(play);
        actions.appendChild(remove);
        tr.appendChild(actions);
        body.appendChild(tr);
      });
      document.getElementById("revision").textContent = state.revision || "";
    }
    function applyBound(index, field, value) {
      var regions = state.regions;
      var region = regions[index];
      if (field === "start") {
        if (index === 0) value = 0;
        region.start = value;
        if (index > 0) regions[index - 1].end = value;
      } else {
        if (index === regions.length - 1) value = state.duration_seconds;
        region.end = value;
        if (index + 1 < regions.length) regions[index + 1].start = value;
      }
      region.evidence_basis = "manual";
      region.source = "user";
    }
    function playRegion(region, event) {
      if (event && event.target && event.target.closest("input, select, button") && event.target.textContent !== "试听") return;
      if (!track) return;
      track.currentTime = Number(region.start) || 0;
      var end = Number(region.end);
      var stop = function () {
        if (track.currentTime >= end - 0.05) {
          track.pause();
          track.removeEventListener("timeupdate", stop);
        }
      };
      track.addEventListener("timeupdate", stop);
      var playing = track.play();
      if (playing && playing.catch) playing.catch(function () {});
    }
    function postDraft() {
      return fetch("/api/regions-draft", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({expected_revision: state.revision, regions: state.regions})
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) {
            showError(data.error || "保存失败");
            return refreshDesk();
          }
          state = data;
          showError("");
          render();
        });
      });
    }
    function refreshDesk() {
      return fetch("/api/music-desk").then(function (response) { return response.json(); }).then(function (data) {
        if (data.error) { showError(data.error); return; }
        state = data;
        showError("");
        render();
      });
    }
    function deleteRegion(index) {
      if (!state || state.regions.length < 2) { showError("至少保留一段"); return; }
      var region = state.regions[index];
      if (index > 0) {
        state.regions[index - 1].end = region.end;
        state.regions[index - 1].evidence_basis = "manual";
      } else {
        state.regions[1].start = region.start;
        state.regions[1].evidence_basis = "manual";
      }
      state.regions.splice(index, 1);
      postDraft();
    }
    document.getElementById("add-region").addEventListener("click", function () {
      if (!state || !state.regions.length) return;
      var region = state.regions[0];
      var mid = (Number(region.start) + Number(region.end)) / 2;
      if (!(mid > region.start && mid < region.end)) { showError("这段太短，不能再拆"); return; }
      var copy = JSON.parse(JSON.stringify(region));
      copy.region_id = "user-" + Date.now();
      copy.start = mid;
      copy.evidence_basis = "manual";
      copy.source = "user";
      region.end = mid;
      region.evidence_basis = "manual";
      region.source = "user";
      state.regions.splice(1, 0, copy);
      postDraft();
    });
    document.getElementById("save").addEventListener("click", function () { if (state) postDraft(); });
    document.getElementById("discard").addEventListener("click", function () {
      if (!state || !confirm("丢弃草稿？未锁定的修改会丢掉。")) return;
      fetch("/api/regions-draft/discard", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({expected_revision: state.revision})
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) { showError(data.error || "丢弃失败"); return; }
          return refreshDesk();
        });
      });
    });
    if (state) render();
  </script>
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
            message = str(item.get("msg", ""))
            if message.startswith("Value error, "):
                message = message.removeprefix("Value error, ")
            if message:
                parts.append(message)
        return "; ".join(parts) or "invalid regions"
    return str(exc)


def _check_bounds(region_id: str, start: object, end: object, duration: float) -> None:
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
    ):
        raise ValueError(f"region {region_id} bounds must be finite numbers")
    if math.isnan(start) or math.isnan(end) or math.isinf(start) or math.isinf(end):
        raise ValueError(f"region {region_id} bounds must be finite numbers")
    if not start < end:
        raise ValueError(f"region {region_id} start must be less than end")
    if start < -_BOUNDARY_TOLERANCE or end > duration + _BOUNDARY_TOLERANCE:
        raise ValueError(f"region {region_id} must stay inside the track duration")


def _load_candidate_regions(paths: ProjectPaths) -> MusicEditRegions | None:
    if not _regions_present(paths):
        return None
    return MusicEditRegions.model_validate_json(paths.music_edit_regions.read_text(encoding="utf-8"))


def _region_view(region: MusicEditRegion) -> dict:
    payload = region.model_dump(mode="json")
    payload["kind_label"] = KIND_LABELS.get(region.edit_role, region.edit_role)
    payload["source"] = "user" if region.evidence_basis == "manual" else "analyzer"
    return payload


def _desk_view(document) -> dict:
    return {
        "revision": document.regions_sha256,
        "version_id": document.version_id,
        "duration_seconds": document.regions.duration_seconds,
        "regions": [_region_view(region) for region in document.regions.regions],
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


def _apply_region_edits(base: MusicEditRegions, payload: list) -> MusicEditRegions:
    if not payload:
        raise ValueError("regions must be a non-empty list")
    parsed: list[MusicEditRegion] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("region must be an object")
        data = {key: value for key, value in item.items() if key not in _VIEW_KEYS}
        region_id = str(data.get("region_id") or "?")
        _check_bounds(region_id, data.get("start"), data.get("end"), base.duration_seconds)
        parsed.append(MusicEditRegion.model_validate(data))
    return base.model_copy(update={"regions": parsed})


def _client_write_path(payload: dict) -> bool:
    return any(isinstance(payload.get(key), str) and str(payload.get(key)).strip() for key in _CLIENT_PATH_KEYS)


def _music_desk_response(project: Path) -> ServeResponse:
    paths, error = _open(project)
    if error is not None or paths is None:
        assert error is not None
        return error
    draft, failure = _ensure_draft(paths)
    if failure is not None or draft is None:
        assert failure is not None
        return failure
    return _json_response(200, _desk_view(draft))


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
    regions_payload = payload.get("regions")
    if not isinstance(regions_payload, list):
        return _error(400, "regions must be a non-empty list", "POST /api/regions-draft")
    expected = payload.get("expected_revision")
    draft = load_regions_draft(paths)
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
        updated = _apply_region_edits(base, regions_payload)
        saved = save_regions_draft(paths, updated)
    except (ValidationError, ValueError, RegionsVersionError, ProjectConflict) as exc:
        return _error(400, _validation_message(exc), "POST /api/regions-draft")
    return _json_response(200, _desk_view(saved))


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


def _music_rows(view: dict | None) -> tuple[str, str]:
    if not view:
        return "", ""
    duration = float(view["duration_seconds"]) or 1.0
    strips: list[str] = []
    rows: list[str] = []
    options = "".join(
        f'<option value="{html.escape(role)}">{html.escape(label)}</option>'
        for role, label in KIND_LABELS.items()
    )
    for region in view["regions"]:
        width = max(0.0, (float(region["end"]) - float(region["start"])) / duration * 100)
        label = str(region.get("kind_label") or region["edit_role"])
        strips.append(f'<span style="width:{width:.4f}%">{html.escape(label)}</span>')
        selected = options.replace(
            f'value="{html.escape(str(region["edit_role"]))}"',
            f'value="{html.escape(str(region["edit_role"]))}" selected',
            1,
        )
        source = "已修改" if region.get("source") == "user" else "分析"
        checked = " checked" if region.get("enabled", True) else ""
        rows.append(
            "<tr data-region-id=\"{rid}\">"
            "<td><select>{options}</select></td>"
            "<td>{start}</td><td>{end}</td><td>{confidence}</td><td>{source}</td>"
            "<td><input type=\"checkbox\"{checked}></td><td>试听</td>"
            "</tr>".format(
                rid=html.escape(str(region["region_id"])),
                options=selected,
                start=html.escape(str(region["start"])),
                end=html.escape(str(region["end"])),
                confidence=html.escape(f"{float(region['confidence']):.2f}"),
                source=source,
                checked=checked,
            )
        )
    return "".join(strips), "".join(rows)


def render_music_page(project: Path) -> str:
    name, full = _resolved_project(project)
    paths, error = _open(project)
    view = None
    message = ""
    hidden = "hidden"
    if error is not None:
        payload = json.loads(error.body.decode("utf-8"))
        message = str(payload.get("error") or "")
        hidden = ""
    else:
        assert paths is not None
        draft, failure = _ensure_draft(paths)
        if failure is not None or draft is None:
            assert failure is not None
            payload = json.loads(failure.body.decode("utf-8"))
            message = str(payload.get("error") or "")
            hidden = ""
        else:
            view = _desk_view(draft)
    strip, rows = _music_rows(view)
    data = "null" if view is None else json.dumps(view, ensure_ascii=False).replace("<", "\\u003c")
    page = _MUSIC_PAGE_TEMPLATE
    page = page.replace("__STYLE__", _PAGE_STYLE)
    page = page.replace("__PROJECT_NAME__", html.escape(name))
    page = page.replace("__PROJECT_PATH__", html.escape(full))
    page = page.replace("__ERROR_HIDDEN__", hidden)
    page = page.replace("__ERROR_TEXT__", html.escape(message))
    page = page.replace("__STRIP__", strip)
    page = page.replace("__ROWS__", rows)
    page = page.replace("__DATA__", data)
    page = page.replace("__KIND_JSON__", json.dumps(KIND_LABELS, ensure_ascii=False))
    page = page.replace("__PROXY_JSON__", json.dumps(_PROXY_FOR_ROLE, ensure_ascii=False))
    return page


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


def handle_confirm_request(
    server: ThreadingHTTPServer,
    method: str,
    target: str,
    headers: Mapping[str, str] | None = None,
    body: bytes = b"",
) -> ServeResponse:
    """Answer one confirm-desk request. ``target`` is the raw request path."""

    project = Path(server.project_root)  # type: ignore[attr-defined]
    if _traversal_requested(target):
        return _error(400, "path traversal refused", "GET /audio/frozen")
    parsed = urlsplit(target)
    path = unquote(parsed.path)
    if method == "POST" and path == "/api/project":
        return _switch_project(server, body)
    if method == "POST" and path == "/api/reveal":
        return _reveal_project(server, body)
    if method == "POST" and path == "/api/regions-draft":
        return _save_draft_request(project, body)
    if method == "POST" and path == "/api/regions-draft/discard":
        return _discard_draft_request(project, body)
    if method not in {"GET", "HEAD"}:
        return _error(405, "method is not allowed", "GET /api/status")
    if path == "/":
        return _html(render_project_page(project))
    if path == "/music":
        return _html(render_music_page(project))
    if path == "/export":
        return _html(_EXPORT_HTML)
    if path == "/api/music-desk":
        return _music_desk_response(project)
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
        if method in {"POST", "PUT", "DELETE"}:
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = -1
            if length < 0 or length > _MAX_BODY_BYTES:
                response = _error(400, "request body is too large", "POST /api/project")
                self._write(method, response)
                return
            if length:
                body = self.rfile.read(length)
        response = handle_confirm_request(
            self.server, method, self.path, dict(self.headers.items()), body
        )
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
