"""Read-only local confirm desk.

HTTP stack: the stdlib ``http.server.ThreadingHTTPServer``. One process, no
extra dependency, no authentication, and no upload. The default bind address
is ``127.0.0.1``. ``--lan`` binds ``0.0.0.0`` for other machines on the same
network. This is not a public internet service.

Routes (GET only):

- ``/`` placeholder page with an ``<audio>`` element
- ``/api/status`` frozen music, regions file, version counts, FCPXML
- ``/api/regions-versions`` and ``/api/regions-versions/<id-or-draft>``
- ``/api/music-edit-regions`` analyzer candidate, or a JSON error with a CLI hint
- ``/audio/frozen`` the project's frozen music file, with HTTP Range

Client paths are not accepted. ``..`` and any frozen path that resolves outside
the project are refused. Confirmed versions are read through the Slice 1 store;
this module does not save, confirm, discard, re-run, or export.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Mapping
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

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_VERSION_ID_RE = re.compile(r"^regions-v[0-9]{2,}$")

_PLACEHOLDER_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>确认台</title>
</head>
<body>
  <h1>确认台</h1>
  <p>Local read-only placeholder. Playback of the frozen track only.</p>
  <audio id="track" controls src="/audio/frozen"></audio>
  <pre id="status">loading /api/status</pre>
  <script>
    fetch("/api/status").then(function (response) { return response.json(); }).then(function (data) {
      document.getElementById("status").textContent = JSON.stringify(data, null, 2);
    });
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


def _discover_fcpxml(root: Path) -> list[str]:
    found: list[str] = []
    base = root.resolve()
    for directory, dirnames, filenames in os.walk(base, followlinks=False):
        current = Path(directory)
        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
        for name in filenames:
            if name != "project.fcpxml":
                continue
            candidate = current / name
            if candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            if resolved.is_file() and resolved.is_relative_to(base):
                found.append(resolved.relative_to(base).as_posix())
    return sorted(found)


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
    fcpxml_paths = _discover_fcpxml(paths.root)
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
        "fcpxml": {"present": bool(fcpxml_paths), "paths": fcpxml_paths},
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


def handle_confirm_request(
    project: Path,
    method: str,
    target: str,
    headers: Mapping[str, str] | None = None,
) -> ServeResponse:
    """Answer one read-only request. ``target`` is the raw request path."""

    if method not in {"GET", "HEAD"}:
        return _error(405, "confirm desk serve is read-only", "GET /api/status")
    if _traversal_requested(target):
        return _error(400, "path traversal refused", "GET /audio/frozen")
    parsed = urlsplit(target)
    path = unquote(parsed.path)
    if path == "/":
        body = _PLACEHOLDER_HTML.encode("utf-8")
        return ServeResponse(200, body, "text/html; charset=utf-8")
    if path == "/api/status":
        return project_status(project)
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
        project = Path(self.server.project_root)  # type: ignore[attr-defined]
        response = handle_confirm_request(project, method, self.path, dict(self.headers.items()))
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(response.body)


def start_confirm_desk(
    project: Path,
    host: str | None = None,
    port: int = 0,
    lan: bool = False,
) -> ThreadingHTTPServer:
    """Bind a daemon server and return it. ``port=0`` asks the OS for a free port."""

    bind_host = serve_bind_host(lan) if host is None else host
    server = ThreadingHTTPServer((bind_host, port), _ConfirmDeskHandler)
    server.daemon_threads = True
    server.project_root = str(project)  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, name="confirm-desk", daemon=True)
    thread.start()
    return server


def serve_confirm_desk(project: Path, *, host: str, port: int) -> None:
    """Serve until the process is interrupted. Used by ``travel-director serve``."""

    server = ThreadingHTTPServer((host, port), _ConfirmDeskHandler)
    server.daemon_threads = True
    server.project_root = str(project)  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
