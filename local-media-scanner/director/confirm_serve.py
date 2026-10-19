"""Local confirm desk, project page.

HTTP stack: the stdlib ``http.server.ThreadingHTTPServer``. One process, no
extra dependency, no authentication, and no upload. The default bind address
is ``127.0.0.1``. ``--lan`` binds ``0.0.0.0`` for other machines on the same
network. This is not a public internet service.

``/`` is the project page: path input, recent projects, status bar, refresh,
and a file-manager open of the resolved project root. ``/music`` and
``/export`` are stubs. JSON reads and ``/audio/frozen`` stay as in Slice 2.

``POST /api/project`` only changes which local project this process is
showing. ``POST /api/reveal`` runs ``open`` on macOS or ``xdg-open`` on Linux
with that resolved root and nothing else. Windows is not implemented.
Confirmed versions are read through the Slice 1 store; this module does not
save, confirm, discard, re-run, or export.
"""

from __future__ import annotations

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
from urllib.parse import unquote, urlsplit

from director.audio_import import ImportedMusicAsset
from director.music_edit_regions_versions import (
    RegionsVersionError,
    list_regions_versions,
    load_regions_draft,
    load_regions_version,
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

_PROJECT_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>确认台 · 项目</title>
  <style>
    :root { color-scheme: light; font-family: "Iowan Old Style", Palatino, "Songti SC", serif; }
    body { margin: 0; background: #f4f0e6; color: #1c1915; }
    header, main { max-width: 52rem; margin: 0 auto; padding: 1.25rem; }
    header { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }
    nav a { margin-left: 0.75rem; color: #6b4423; }
    h1 { font-size: 1.6rem; margin: 0; }
    form, .bar, .panel { background: #fffdf8; border: 1px solid #ddd4c4; border-radius: 8px; padding: 0.9rem 1rem; margin-bottom: 0.9rem; }
    label { display: block; font-size: 0.85rem; margin-bottom: 0.35rem; }
    input[type="text"] { width: 100%; box-sizing: border-box; padding: 0.45rem 0.55rem; }
    .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.6rem; }
    button { font: inherit; background: #243024; color: #f4f0e6; border: 0; border-radius: 6px; padding: 0.4rem 0.75rem; cursor: pointer; }
    button.secondary { background: #6b4423; }
    .bar { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.75rem; }
    .bar span { display: block; font-size: 0.75rem; letter-spacing: 0.04em; color: #6b6256; }
    .bar strong { font-size: 1.15rem; }
    #error { border-color: #9a3412; background: #fff1eb; }
    #hints code, #recent button { display: block; font-family: ui-monospace, monospace; font-size: 0.82rem; margin: 0.35rem 0; white-space: pre-wrap; }
    #recent button { width: 100%; text-align: left; background: transparent; color: #1c1915; border: 1px solid #ddd4c4; }
    audio { width: 100%; margin-top: 0.5rem; }
    @media (max-width: 720px) { .bar { grid-template-columns: 1fr 1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>确认台</h1>
    <nav>
      <a href="/" aria-current="page">项目</a>
      <a href="/music">音乐分区</a>
      <a href="/export">导出</a>
    </nav>
  </header>
  <main>
    <form id="open-form">
      <label for="project-path-input">打开本机项目路径</label>
      <input id="project-path-input" type="text" name="path" autocomplete="off" spellcheck="false">
      <div class="actions">
        <button type="submit">打开项目</button>
        <button type="button" id="refresh" class="secondary">刷新产物</button>
        <button type="button" id="reveal" class="secondary">访达打开目录</button>
      </div>
    </form>
    <section class="bar" aria-label="状态条">
      <div><span>冻结曲</span><strong data-field="frozen-music">…</strong></div>
      <div><span>music_edit_regions</span><strong data-field="music-edit-regions">…</strong></div>
      <div><span>确认版</span><strong data-field="confirmed-count">…</strong></div>
      <div><span>FCPXML</span><strong data-field="fcpxml">…</strong></div>
    </section>
    <section id="error" class="panel" hidden></section>
    <section id="hints" class="panel" aria-label="可复制命令"></section>
    <section id="recent" class="panel" aria-label="最近项目"></section>
    <section class="panel">
      <div>冻结曲试听</div>
      <audio id="track" controls src="/audio/frozen"></audio>
      <p><a href="/music">音乐分区（Slice 4+/8 coming）</a> · <a href="/export">导出（Slice 4+/8 coming）</a></p>
    </section>
  </main>
  <script>
    function field(name, text) {
      document.querySelector('[data-field="' + name + '"]').textContent = text;
    }
    function yesNo(present) { return present ? "有" : "无"; }
    function showHint(text) {
      if (!text) return;
      var code = document.createElement("code");
      code.textContent = text;
      document.getElementById("hints").appendChild(code);
    }
    function show(data) {
      var errorBox = document.getElementById("error");
      var hints = document.getElementById("hints");
      hints.textContent = "";
      if (data.error) {
        errorBox.hidden = false;
        errorBox.textContent = data.error;
        field("frozen-music", "无");
        field("music-edit-regions", "无");
        field("confirmed-count", "0");
        field("fcpxml", "无");
        showHint(data.hint);
        return;
      }
      errorBox.hidden = true;
      errorBox.textContent = "";
      field("frozen-music", yesNo(data.frozen_music && data.frozen_music.present));
      field("music-edit-regions", yesNo(data.music_edit_regions && data.music_edit_regions.present));
      var versions = data.regions_versions || {};
      field("confirmed-count", String(versions.confirmed_count || 0));
      var pack = data.fcpxml || {};
      field("fcpxml", yesNo(pack.present) + " · receipt " + yesNo(pack.receipt_present));
      (data.missing || []).forEach(function (item) { showHint(item.hint); });
      if (data.music_edit_regions && !data.music_edit_regions.present) showHint(data.music_edit_regions.hint);
      var input = document.getElementById("project-path-input");
      if (!input.value && data.project_path) input.value = data.project_path;
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
    refresh().then(loadRecent);
  </script>
</body>
</html>
"""

_STUB_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>确认台</title></head>
<body>
  <p>Slice 4+/8 coming</p>
  <p><a href="/">返回项目页</a></p>
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
    if method not in {"GET", "HEAD"}:
        return _error(405, "confirm desk serve is read-only", "GET /api/status")
    if path == "/":
        return _html(_PROJECT_PAGE_HTML)
    if path in {"/music", "/export"}:
        return _html(_STUB_HTML)
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
