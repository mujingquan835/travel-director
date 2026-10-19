"""Local confirm desk: project page, music draft edits, and frozen audio.

The server is a stdlib ThreadingHTTPServer bound to one project. Slice 4 writes
the regions draft only. It does not confirm, re-run analysis, or export FCPXML.
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


def _post_json(port: int, path: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        response = connection.getresponse()
        raw = response.read()
        return response.status, json.loads(raw.decode("utf-8"))
    finally:
        connection.close()


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


def test_project_page_shows_status_fields_refresh_and_stub_links(desk) -> None:
    paths, server = desk
    port = _port(server)
    status, _headers, page = _request(port, "/")
    text = page.decode("utf-8")

    assert status == 200
    assert "刷新产物" in text
    assert "访达打开目录" in text
    assert "配乐已定" in text
    assert "音乐分段分析" in text
    assert "分段已确认" in text
    assert "已导出剪映工程" in text
    assert 'id="error"' in text
    assert 'id="hints"' in text
    assert 'id="project-path-input"' in text
    assert 'id="project-name"' in text
    assert 'id="refresh"' in text
    assert 'fetch("/api/status"' in text
    assert "data.hints" in text
    assert 'href="/music"' in text
    assert 'href="/export"' in text
    assert paths.root.name in text

    export_status, _export_headers, export_page = _request(port, "/export")
    assert export_status == 200
    assert "导出：后续版本开放" in export_page.decode("utf-8")


def test_refresh_refetch_sees_new_fcpxml_and_receipt(desk) -> None:
    paths, server = desk
    port = _port(server)
    before_code, before = _json(port, "/api/status")
    assert before_code == 200
    assert before["fcpxml"]["present"] is False
    assert before["fcpxml"]["receipt_present"] is False

    package = paths.root / "delivery"
    package.mkdir()
    (package / "project.fcpxml").write_text("<fcpxml/>", encoding="utf-8")
    (package / "receipt.json").write_text("{}\n", encoding="utf-8")
    after_code, after = _json(port, "/api/status")

    assert after_code == 200
    assert after["fcpxml"]["present"] is True
    assert after["fcpxml"]["paths"] == ["delivery/project.fcpxml"]
    assert after["fcpxml"]["receipt_present"] is True
    assert after["fcpxml"]["receipt_paths"] == ["delivery/receipt.json"]
    assert after["regions_versions"]["confirmed_count"] == 0


def test_reveal_opens_resolved_project_root_and_refuses_other_paths(desk, tmp_path: Path) -> None:
    from director.confirm_serve import file_manager_command

    paths, server = desk
    calls: list[list[str]] = []
    server.directory_opener = lambda command: calls.append(list(command))
    port = _port(server)
    root = str(paths.root.resolve())

    status, payload = _post_json(port, "/api/reveal", {})

    assert status == 200
    assert payload["opened"] == root
    assert calls == [file_manager_command(paths.root)]
    assert calls[0][0] in {"open", "xdg-open"}
    assert calls[0][-1] == root

    calls.clear()
    status, payload = _post_json(port, "/api/reveal", {"path": str(tmp_path / "elsewhere")})
    assert status == 400
    assert "project root" in payload["error"]
    assert calls == []

    status, payload = _post_json(port, "/api/reveal", {"path": "../secret"})
    assert status == 400
    assert calls == []


def test_open_project_switches_desk_and_records_recent_paths(tmp_path: Path) -> None:
    from director.project import create_visual_project
    from director.visual_schema import RawCreativeBrief

    first = _project(tmp_path)
    second = create_visual_project(
        tmp_path / "runs", "other", RawCreativeBrief(raw_description="另一段旅行")
    )
    recent = tmp_path / "recent.json"
    server = start_confirm_desk(first.root, host="127.0.0.1", port=0, recent_path=recent)
    try:
        port = _port(server)
        status, payload = _post_json(port, "/api/project", {"path": str(second.root)})
        assert status == 200
        assert payload["project_path"] == str(second.root.resolve())

        recent_status, recent_payload = _json(port, "/api/recent")
        assert recent_status == 200
        assert recent_payload["paths"][0] == str(second.root.resolve())

        bad = tmp_path / "not-a-project"
        bad_status, bad_payload = _post_json(port, "/api/project", {"path": str(bad)})
        assert bad_status == 404
        assert "project_state.json" in bad_payload["error"]
        assert bad_payload["hint"].startswith("travel-director ")
        _again, recent_after = _json(port, "/api/recent")
        assert str(bad) not in recent_after["paths"]
    finally:
        server.shutdown()
        server.server_close()


def test_bad_path_page_is_not_blank_and_api_hint_remains(tmp_path: Path) -> None:
    server = start_confirm_desk(tmp_path / "not-a-project", host="127.0.0.1", port=0)
    try:
        port = _port(server)
        status, _headers, page = _request(port, "/")
        text = page.decode("utf-8")
        assert status == 200
        assert len(page) > 400
        assert 'id="error"' in text
        assert "刷新产物" in text
        assert "访达打开目录" in text
        api_status, payload = _json(port, "/api/status")
    finally:
        server.shutdown()
        server.server_close()

    assert api_status == 404
    assert "project_state.json" in payload["error"]
    assert payload["hint"].startswith("travel-director ")


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


def _record_regions(paths, document=None):
    from director.project import record_supporting_artifact

    document = _document() if document is None else document
    record_supporting_artifact(
        paths, paths.music_edit_regions, document, state_key="music_edit_regions"
    )
    return document


def _region_payloads(document):
    return [region.model_dump(mode="json") for region in document.regions]


def test_draft_edit_accepts_valid_changes_and_rejects_invalid_and_stale(desk) -> None:
    from director.music_edit_regions_versions import load_regions_draft

    paths, server = desk
    document = _record_regions(paths)
    port = _port(server)

    status, opened = _json(port, "/api/music-desk")
    assert status == 200
    assert opened["revision"]
    assert [item["region_id"] for item in opened["regions"]] == ["r1", "r2", "r3"]
    assert opened["regions"][0]["kind_label"] == "前奏"
    assert opened["regions"][0]["source"] == "analyzer"
    assert opened["regions"][0]["enabled"] is True
    revision = opened["revision"]
    assert load_regions_draft(paths) is not None

    edited = _region_payloads(document)
    edited[1]["edit_role"] = "peak_cut"
    edited[1]["musical_proxy"] = "climax"
    edited[1]["enabled"] = False
    edited[1]["evidence_basis"] = "manual"
    edited[0]["end"] = 12.0
    edited[1]["start"] = 12.0
    status, saved = _post_json(
        port, "/api/regions-draft", {"expected_revision": revision, "regions": edited}
    )
    assert status == 200, saved
    assert saved["revision"] != revision
    assert saved["regions"][0]["end"] == 12.0
    assert saved["regions"][1]["edit_role"] == "peak_cut"
    assert saved["regions"][1]["kind_label"] == "高潮"
    assert saved["regions"][1]["enabled"] is False
    assert saved["regions"][1]["source"] == "user"
    kept = load_regions_draft(paths)
    assert kept is not None
    assert kept.regions.regions[1].enabled is False

    stale, stale_body = _post_json(
        port, "/api/regions-draft", {"expected_revision": revision, "regions": edited}
    )
    assert stale == 409
    assert "revision" in stale_body["error"]

    invalid = _region_payloads(saved_document(saved))
    invalid[0]["end"] = invalid[0]["start"]
    code, body = _post_json(
        port, "/api/regions-draft", {"expected_revision": saved["revision"], "regions": invalid}
    )
    assert code == 400
    assert "start" in body["error"]
    assert load_regions_draft(paths).regions_sha256 == saved["revision"]

    outside = _region_payloads(saved_document(saved))
    outside[0]["end"] = 100.0
    outside[1]["start"] = 100.0
    code, body = _post_json(
        port, "/api/regions-draft", {"expected_revision": saved["revision"], "regions": outside}
    )
    assert code == 400
    assert "duration" in body["error"]

    nan_regions = _region_payloads(saved_document(saved))
    nan_regions[0]["start"] = float("nan")
    code, body = _post_json(
        port,
        "/api/regions-draft",
        {"expected_revision": saved["revision"], "regions": nan_regions},
    )
    assert code == 400
    assert "finite" in body["error"]
    assert load_regions_draft(paths).regions_sha256 == saved["revision"]


def saved_document(view: dict):
    """Rebuild a MusicEditRegions-like object is unnecessary; copy view regions."""

    from director.music_edit_regions_schema import MusicEditRegions

    payload = {
        "source_sha256": "a" * 64,
        "duration_seconds": view["duration_seconds"],
        "bpm": 120.0,
        "provider": "heuristic_v1",
        "downbeat_detector": "every_fourth_beat",
        "regions": [
            {key: value for key, value in region.items() if key not in {"kind_label", "source"}}
            for region in view["regions"]
        ],
        "ending": {"last_onset_seconds": 28.0, "behavior": "decay"},
        "confidence": 0.5,
    }
    return MusicEditRegions.model_validate(payload)


def test_discard_draft_removes_it_and_stale_discard_is_refused(desk) -> None:
    from director.music_edit_regions_versions import load_regions_draft

    paths, server = desk
    document = _record_regions(paths)
    port = _port(server)
    _status, opened = _json(port, "/api/music-desk")
    edited = _region_payloads(document)
    edited[1]["edit_role"] = "build"
    edited[1]["evidence_basis"] = "manual"
    status, saved = _post_json(
        port,
        "/api/regions-draft",
        {"expected_revision": opened["revision"], "regions": edited},
    )
    assert status == 200, saved

    stale, body = _post_json(
        port, "/api/regions-draft/discard", {"expected_revision": opened["revision"]}
    )
    assert stale == 409
    assert "revision" in body["error"]
    assert load_regions_draft(paths) is not None
    assert load_regions_draft(paths).regions_sha256 == saved["revision"]

    status, payload = _post_json(
        port, "/api/regions-draft/discard", {"expected_revision": saved["revision"]}
    )
    assert status == 200
    assert payload["discarded"] is True
    assert load_regions_draft(paths) is None


def test_draft_write_refuses_traversal_and_replaces_atomically(desk, tmp_path: Path, monkeypatch) -> None:
    import os

    from director.music_edit_regions_versions import load_regions_draft

    paths, server = desk
    document = _record_regions(paths)
    port = _port(server)
    outside = tmp_path / "escaped" / "draft.json"
    status, payload = _post_json(
        port,
        "/api/regions-draft",
        {
            "expected_revision": None,
            "path": "../secret",
            "regions": _region_payloads(document),
        },
    )
    assert status == 400
    assert "project" in payload["error"]
    assert not outside.exists()
    assert load_regions_draft(paths) is None

    status, _headers, _body = _request(port, "/api/regions-draft/../../secret.txt", method="POST")
    assert status == 400

    replaced: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src, dst):
        replaced.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr("director.project.os.replace", spy)
    code, saved = _post_json(
        port,
        "/api/regions-draft",
        {"expected_revision": None, "regions": _region_payloads(document)},
    )
    assert code == 200, saved
    draft = paths.root / "music_edit_regions_versions" / "draft.json"
    assert draft.is_file()
    assert draft.resolve().is_relative_to(paths.root.resolve())
    assert any(
        destination.endswith("draft.json") and ".tmp" in Path(source).name
        for source, destination in replaced
    )


def test_music_page_renders_regions_and_edit_controls(desk) -> None:
    paths, server = desk
    _record_regions(paths)
    port = _port(server)
    status, _headers, page = _request(port, "/music")
    text = page.decode("utf-8")

    assert status == 200
    assert "r1" in text
    assert "前奏" in text
    assert "高潮" in text
    assert "可卡点" in text
    assert "保存草稿" in text
    assert "丢弃草稿" in text
    assert "分析" in text
    assert "/audio/frozen" in text
    assert "currentTime" in text
    assert "confirm(" in text
    assert "expected_revision" in text
    assert "锁定版本" not in text
    assert "waveform" not in text.lower()
    assert paths.root.name in text


def test_project_page_chinese_steps_next_step_and_unique_hints(desk) -> None:
    from director.music_edit_regions_versions import confirm_regions_draft, save_regions_draft

    paths, server = desk
    port = _port(server)
    status, _headers, page = _request(port, "/")
    text = page.decode("utf-8")
    full = str(paths.root.resolve())

    assert status == 200
    assert "配乐自动分段" in text
    assert "你听并修改确认" in text
    assert "用确认版导出剪映" in text
    assert "显示命令" in text
    assert 'id="copy-commands"' in text
    assert "完成" in text and "未完成" in text
    assert "下一步" in text
    assert f'id="project-name"' in text
    assert paths.root.name in text
    assert f'title="{full}"' in text
    assert "music_edit_regions" not in text
    assert "receipt" not in text.lower()
    assert text.count("analyze-music-edit-regions") == 0

    code, payload = _json(port, "/api/status")
    assert code == 200
    analyze = [hint for hint in payload["hints"] if "analyze-music-edit-regions" in hint]
    assert analyze == [payload["music_edit_regions"]["hint"]]
    assert len(analyze) == 1
    assert payload["hints"].count(analyze[0]) == 1
    assert payload["progress"]["next"]["title"] == "配乐已定"
    assert payload["progress"]["steps"][0]["state"] == "未完成"
    assert "music_edit_regions" not in payload["progress"]["next"]["instruction"]
    assert "receipt" not in payload["progress"]["next"]["instruction"]

    _freeze_wav(paths, b"RIFF" + b"\x00" * 32)
    code, payload = _json(port, "/api/status")
    assert payload["progress"]["next"]["title"] == "音乐分段分析"
    assert payload["progress"]["steps"][0]["state"] == "完成"

    document = _record_regions(paths)
    code, payload = _json(port, "/api/status")
    assert payload["progress"]["next"]["title"] == "分段已确认"
    assert payload["progress"]["steps"][1]["state"] == "完成"

    save_regions_draft(paths, document)
    confirm_regions_draft(paths)
    code, payload = _json(port, "/api/status")
    assert payload["progress"]["next"]["title"] == "已导出剪映工程"
    assert payload["progress"]["steps"][2]["state"] == "完成"

    package = paths.root / "delivery"
    package.mkdir()
    (package / "project.fcpxml").write_text("<fcpxml/>", encoding="utf-8")
    code, payload = _json(port, "/api/status")
    assert payload["progress"]["next"] is None
    assert payload["progress"]["steps"][3]["state"] == "完成"
    assert all(step["state"] == "完成" for step in payload["progress"]["steps"])
