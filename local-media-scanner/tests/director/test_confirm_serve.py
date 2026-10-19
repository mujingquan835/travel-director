"""Read-only local confirm desk (Slice 2).

The server is a stdlib ThreadingHTTPServer bound to one project. It does not
write drafts, confirm, re-run analysis, or export FCPXML.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import time
from pathlib import Path

import pytest

from director.confirm_serve import (
    DEFAULT_BIND_HOST,
    DEFAULT_PORT,
    LAN_BIND_HOST,
    serve_bind_host,
    start_confirm_desk,
)
from tests.director.test_music_edit_regions_versions import _document, _project, _with_role


def _request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        header_map = {key.lower(): value for key, value in response.getheaders()}
        return response.status, header_map, body
    finally:
        connection.close()


def _json(port: int, path: str) -> tuple[int, dict]:
    status, _headers, body = _request(port, path)
    return status, json.loads(body.decode("utf-8"))


@pytest.fixture
def desk(tmp_path: Path):
    paths = _project(tmp_path)
    server = start_confirm_desk(paths.root, host=DEFAULT_BIND_HOST, port=0)
    try:
        yield paths, server
    finally:
        server.shutdown()
        server.server_close()


def _port(server) -> int:
    return int(server.server_address[1])


def test_default_bind_host_is_loopback_and_port_is_8765() -> None:
    assert DEFAULT_BIND_HOST == "127.0.0.1"
    assert DEFAULT_PORT == 8765
    assert serve_bind_host(False) == "127.0.0.1"
    assert serve_bind_host(True) == LAN_BIND_HOST == "0.0.0.0"

    from typer.main import get_command

    from director.cli import app

    command = get_command(app).commands["serve"]
    params = {parameter.name: parameter for parameter in command.params}
    assert params["port"].default == 8765
    assert params["lan"].default is False


def test_ephemeral_server_status_shape_and_placeholder(desk) -> None:
    paths, server = desk
    assert server.server_address[0] == "127.0.0.1"
    port = _port(server)
    assert port != 0

    status_code, payload = _json(port, "/api/status")

    assert status_code == 200
    assert payload["project_path"] == str(paths.root.resolve())
    assert payload["frozen_music"]["present"] is False
    assert payload["frozen_music"]["audio_url"] is None
    assert payload["music_edit_regions"]["present"] is False
    assert "analyze-music-edit-regions" in payload["music_edit_regions"]["hint"]
    assert str(paths.root) in payload["music_edit_regions"]["hint"]
    assert payload["regions_versions"] == {
        "draft_count": 0,
        "confirmed_count": 0,
        "history_count": 0,
        "latest_confirmed_id": None,
    }
    assert payload["fcpxml"]["present"] is False
    assert payload["fcpxml"]["paths"] == []
    assert any(item["artifact"] == "music_edit_regions" for item in payload["missing"])

    page_status, page_headers, page = _request(port, "/")
    assert page_status == 200
    assert "text/html" in page_headers["content-type"]
    assert b"<audio" in page
    assert b"/audio/frozen" in page
    assert b"/api/status" in page


def test_versions_list_and_get_draft_and_confirmed(desk) -> None:
    from director.music_edit_regions_versions import confirm_regions_draft, save_regions_draft

    paths, server = desk
    port = _port(server)
    original = _document()
    save_regions_draft(paths, original)
    confirmed = confirm_regions_draft(paths)
    draft = save_regions_draft(paths, _with_role(original, "r1", "narrative_hold"))

    status_code, listing = _json(port, "/api/regions-versions")
    assert status_code == 200
    by_id = {item["version_id"]: item for item in listing["versions"]}
    assert by_id[confirmed.version_id]["status"] == "confirmed"
    assert by_id[confirmed.version_id]["source_music_sha8"] == "a" * 8
    assert by_id[confirmed.version_id]["confirmed_at"]
    assert by_id[draft.version_id]["status"] == "draft"
    assert by_id[draft.version_id]["confirmed_at"] is None

    _status, project_status = _json(port, "/api/status")
    summary = project_status["regions_versions"]
    assert summary["draft_count"] == 1
    assert summary["confirmed_count"] == 1
    assert summary["history_count"] == 0
    assert summary["latest_confirmed_id"] == confirmed.version_id

    code, document = _json(port, f"/api/regions-versions/{confirmed.version_id}")
    assert code == 200
    assert document["version_id"] == confirmed.version_id
    assert document["status"] == "confirmed"
    assert [region["region_id"] for region in document["regions"]["regions"]] == ["r1", "r2", "r3"]

    code, draft_body = _json(port, "/api/regions-versions/draft")
    assert code == 200
    assert draft_body["version_id"] == draft.version_id
    assert draft_body["regions"]["regions"][0]["edit_role"] == "narrative_hold"


def test_bad_project_path_returns_json_hint(tmp_path: Path) -> None:
    missing = tmp_path / "not-a-project"
    server = start_confirm_desk(missing, host="127.0.0.1", port=0)
    try:
        status, payload = _json(_port(server), "/api/status")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 404
    assert "project_state.json" in payload["error"]
    assert payload["hint"].startswith("travel-director ")


def test_missing_regions_artifact_returns_copyable_cli_hint(desk) -> None:
    _paths, server = desk
    status, payload = _json(_port(server), "/api/music-edit-regions")

    assert status == 404
    assert "music_edit_regions" in payload["error"]
    assert "travel-director analyze-music-edit-regions --project " in payload["hint"]


def test_fcpxml_inside_project_is_discovered_and_outside_symlink_is_not(desk, tmp_path: Path) -> None:
    paths, server = desk
    package = paths.root / "delivery" / "project.fcpxml"
    package.parent.mkdir(parents=True)
    package.write_text("<fcpxml/>", encoding="utf-8")
    outside = tmp_path / "outside.fcpxml"
    outside.write_text("OUTSIDE", encoding="utf-8")
    (paths.root / "linked.fcpxml").symlink_to(outside)

    _status, payload = _json(_port(server), "/api/status")

    assert payload["fcpxml"]["present"] is True
    assert payload["fcpxml"]["paths"] == ["delivery/project.fcpxml"]


def _freeze_wav(paths, payload: bytes) -> Path:
    from director.audio_import import ImportedMusicAsset
    from director.project import record_supporting_artifact

    digest = hashlib.sha256(payload).hexdigest()
    relative = Path("generation") / "assets" / f"music-{digest[:16]}.wav"
    target = paths.root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    asset = ImportedMusicAsset(
        original_absolute_path=str(target.resolve()),
        frozen_relative_path=relative.as_posix(),
        source_sha256=digest,
        size_bytes=len(payload),
        duration_seconds=1.0,
        sample_rate=8000,
        channels=1,
        mime_type="audio/wav",
    )
    record_supporting_artifact(paths, paths.generated_music, asset, state_key="music_asset")
    return target


def test_frozen_audio_range_is_partial_content_and_quick(desk) -> None:
    paths, server = desk
    payload = b"RIFF" + b"\x00" * 28 + b"WAVE" + b"0123456789abcdef"
    target = _freeze_wav(paths, payload)
    port = _port(server)

    started = time.perf_counter()
    status, headers, body = _request(port, "/audio/frozen", headers={"Range": "bytes=0-3"})
    elapsed = time.perf_counter() - started

    assert status == 206
    assert headers["content-type"].startswith("audio/wav")
    assert headers["accept-ranges"] == "bytes"
    assert headers["content-range"] == f"bytes 0-3/{len(payload)}"
    assert headers["content-length"] == "4"
    assert body == payload[:4]
    assert elapsed < 1.0
    print(f"serve_audio_seconds={elapsed:.4f}")

    status, _headers, body = _request(port, "/audio/frozen", headers={"Range": "bytes=4-7"})
    assert status == 206
    assert body == payload[4:8]
    assert target.read_bytes() == payload

    code, project_status = _json(port, "/api/status")
    assert code == 200
    assert project_status["frozen_music"]["present"] is True
    assert project_status["frozen_music"]["audio_url"] == "/audio/frozen"
    assert project_status["frozen_music"]["mime_type"] == "audio/wav"
    assert project_status["frozen_music"]["source_sha8"] == hashlib.sha256(payload).hexdigest()[:8]


def test_audio_path_traversal_is_refused(desk, tmp_path: Path) -> None:
    paths, server = desk
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"SECRET-BYTES")
    _freeze_wav(paths, b"RIFFsafe-audio-bytes")
    port = _port(server)

    for path in (
        "/audio/../../secret.txt",
        "/audio/frozen/../../secret.txt",
        "/api/../../../secret.txt",
        "/audio/frozen?path=../secret.txt",
        "/audio/%2e%2e/secret.txt",
    ):
        status, _headers, body = _request(port, path)
        assert status in {400, 404}, path
        assert b"SECRET-BYTES" not in body

    from director.audio_import import ImportedMusicAsset
    from director.project import record_supporting_artifact

    escaped = ImportedMusicAsset(
        original_absolute_path=str(secret.resolve()),
        frozen_relative_path="../secret.txt",
        source_sha256=hashlib.sha256(secret.read_bytes()).hexdigest(),
        size_bytes=secret.stat().st_size,
        duration_seconds=1.0,
        sample_rate=8000,
        channels=1,
        mime_type="audio/wav",
    )
    record_supporting_artifact(paths, paths.generated_music, escaped, state_key="music_asset")
    status, _headers, body = _request(port, "/audio/frozen")
    assert status == 400
    assert b"SECRET-BYTES" not in body
    assert b"traversal" in body.lower() or b"outside" in body.lower()
