"""Local confirm desk: project page, music draft edits, confirm/lock, and audio.

The server is a stdlib ThreadingHTTPServer bound to one project. Slice 6 locks
a draft into a confirmed version. It does not re-run analysis or export FCPXML.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import re
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


def _post_json(port: int, path: str, payload: dict, timeout: float = 5) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
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
    assert "导出剪辑" in export_page.decode("utf-8")
    assert "还没在这台机器上验证" in export_page.decode("utf-8")


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


def _role_payload(document):
    return [{"region_id": region.region_id, "edit_role": region.edit_role} for region in document.regions]


def test_region_schema_round_trip_has_no_enabled_field() -> None:
    from pydantic import ValidationError

    from director.music_edit_regions_schema import MusicEditRegion, MusicEditRegions

    document = _document()
    dumped = document.model_dump(mode="json")
    assert "enabled" not in dumped["regions"][0]
    assert MusicEditRegions.model_validate(dumped).model_dump(mode="json") == dumped
    with pytest.raises(ValidationError):
        MusicEditRegion.model_validate({**dumped["regions"][0], "enabled": False})


def test_role_edit_sets_manual_and_edited_at_and_rejects_other_edits(desk) -> None:
    from datetime import datetime

    from director.music_edit_regions_versions import load_regions_draft

    paths, server = desk
    document = _record_regions(paths)
    port = _port(server)

    status, opened = _json(port, "/api/music-desk")
    assert status == 200
    assert [item["region_id"] for item in opened["regions"]] == ["r1", "r2", "r3"]
    assert opened["regions"][0]["kind_label"] == "铺陈"
    assert opened["regions"][0]["source"] == "analyzer"
    assert "enabled" not in opened["regions"][0]
    revision = opened["revision"]

    roles = _role_payload(document)
    roles[1]["edit_role"] = "peak_cut"
    status, saved = _post_json(
        port, "/api/regions-draft", {"expected_revision": revision, "regions": roles}
    )
    assert status == 200, saved
    assert saved["revision"] != revision
    assert saved["regions"][1]["edit_role"] == "peak_cut"
    assert saved["regions"][1]["kind_label"] == "高潮"
    assert saved["regions"][1]["evidence_basis"] == "manual"
    assert saved["regions"][1]["source"] == "user"
    assert saved["regions"][0]["evidence_basis"] == "energy"
    assert saved["regions"][1]["start"] == 10.0
    assert saved["regions"][1]["end"] == 22.0
    assert saved["regions"][1]["musical_proxy"] == "rise"
    assert "enabled" not in saved["regions"][1]
    datetime.fromisoformat(saved["edited_at"])
    kept = load_regions_draft(paths)
    assert kept is not None
    assert kept.edited_at == saved["edited_at"]
    assert kept.regions.regions[1].evidence_basis == "manual"
    assert kept.regions.regions[0].evidence_basis == "energy"

    stale, stale_body = _post_json(
        port, "/api/regions-draft", {"expected_revision": revision, "regions": roles}
    )
    assert stale == 409
    assert "revision" in stale_body["error"]

    timed = _role_payload(document)
    timed[1]["edit_role"] = "peak_cut"
    timed[0]["end"] = 12.0
    code, body = _post_json(
        port, "/api/regions-draft", {"expected_revision": saved["revision"], "regions": timed}
    )
    assert code == 400
    assert "时间" in body["error"] or "角色" in body["error"]
    assert load_regions_draft(paths).regions_sha256 == saved["revision"]

    added = _role_payload(document) + [{"region_id": "r9", "edit_role": "hook"}]
    added[1]["edit_role"] = "peak_cut"
    code, body = _post_json(
        port, "/api/regions-draft", {"expected_revision": saved["revision"], "regions": added}
    )
    assert code == 400
    assert "删除" in body["error"] or "增加" in body["error"] or "角色" in body["error"]

    shortened = [item for item in roles if item["region_id"] != "r3"]
    code, body = _post_json(
        port, "/api/regions-draft", {"expected_revision": saved["revision"], "regions": shortened}
    )
    assert code == 400
    assert load_regions_draft(paths).regions.regions[1].edit_role == "peak_cut"


def test_discard_draft_removes_it_and_stale_discard_is_refused(desk) -> None:
    from director.music_edit_regions_versions import load_regions_draft

    paths, server = desk
    document = _record_regions(paths)
    port = _port(server)
    _status, opened = _json(port, "/api/music-desk")
    edited = _role_payload(document)
    edited[1]["edit_role"] = "build"
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
            "regions": _role_payload(document),
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
        {"expected_revision": None, "regions": _role_payload(document)},
    )
    assert code == 200, saved
    draft = paths.root / "music_edit_regions_versions" / "draft.json"
    assert draft.is_file()
    assert draft.resolve().is_relative_to(paths.root.resolve())
    assert any(
        destination.endswith("draft.json") and ".tmp" in Path(source).name
        for source, destination in replaced
    )


def test_music_page_renders_role_rows_warnings_and_loop(desk) -> None:
    from director.confirm_serve import playback_span_step

    paths, server = desk
    document = _document()
    regions = [
        region.model_copy(update={"edit_role": "unknown"}) if region.region_id == "r2" else region
        for region in document.regions
    ]
    document = document.model_copy(
        update={"regions": regions, "warnings": ["onset_rate_from_beat_grid_proxy"]}
    )
    _record_regions(paths, document)
    port = _port(server)
    status, _headers, page = _request(port, "/music")
    text = page.decode("utf-8")

    assert status == 200
    assert "r1" in text
    assert "铺陈" in text
    assert "高潮" in text
    assert "开场" in text
    assert "建议镜长" in text
    assert "snap_policy" in text
    assert "置信度" in text
    assert "警告" in text
    assert "时段" in text
    assert "0.0" in text and "10.0" in text
    assert "onset_rate_from_beat_grid_proxy" in text
    assert "节奏密度来自节拍网格" in text
    assert "is-unknown" in text
    assert "播放本段" in text
    assert "循环" in text
    assert "循环本段" in text
    assert 'id="loop"' in text
    assert 'id="loop" checked' not in text
    assert 'id="playhead"' in text
    assert 'id="now-shot"' in text
    assert "playbackSpanStep" in text
    assert "clampSeek" in text
    assert "seekFromFraction" in text
    assert "neighborMark" in text
    assert "detailWindow" in text
    assert "ArrowLeft" in text
    assert "drag:true" not in text
    assert 'draggable="true"' not in text
    assert "保存草稿" in text
    assert "丢弃草稿" in text
    assert "分析" in text
    assert "/audio/frozen" in text
    assert "currentTime" in text
    assert "confirm(" in text
    assert "expected_revision" in text
    assert "加一段" not in text
    assert 'type="number"' not in text
    assert '"enabled"' not in text
    assert "锁定版本" not in text
    assert "waveform" not in text.lower()
    assert paths.root.name in text
    assert playback_span_step(9.96, 0.0, 10.0, True) == "seek"
    assert playback_span_step(9.96, 0.0, 10.0, False) == "pause"
    assert playback_span_step(3.0, 0.0, 10.0, True) == "continue"
    assert playback_span_step(-0.2, 0.0, 10.0, False) == "seek"


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


def _versions_dir(paths: Path):
    return paths.root / "music_edit_regions_versions"


def _retarget_hash(paths, path: Path, state_key: str) -> None:
    from director.project import _sha256_file, _write_state, load_project_state

    state = load_project_state(paths)
    state.completed_artifact_hashes[state_key] = _sha256_file(path)
    _write_state(paths, state)


def _open_analyzer_draft(paths, server, document=None):
    document = _record_regions(paths, document)
    status, opened = _json(_port(server), "/api/music-desk")
    assert status == 200, opened
    return document, opened


def _assert_explained_failure(status: int, headers: dict, body: bytes, *, code: int) -> str:
    assert status == code, body
    assert body
    assert "html" in headers.get("content-type", "") or "json" in headers.get("content-type", "")
    text = body.decode("utf-8")
    assert "travel-director" in text
    assert any("\u4e00" <= char <= "\u9fff" for char in text)
    return text


def test_invalid_draft_json_returns_chinese_error_page_and_json(desk) -> None:
    paths, server = desk
    _open_analyzer_draft(paths, server)
    draft = _versions_dir(paths) / "draft.json"
    draft.write_text("{", encoding="utf-8")
    _retarget_hash(paths, draft, "music_edit_regions_version_draft")
    port = _port(server)

    status, headers, body = _request(port, "/music")
    text = _assert_explained_failure(status, headers, body, code=400)
    assert "JSON" in text
    assert 'id="error"' in text

    status, headers, body = _request(port, "/api/music-desk")
    text = _assert_explained_failure(status, headers, body, code=400)
    assert "JSON" in text
    payload = json.loads(body.decode("utf-8"))
    assert payload["hint"].startswith("travel-director ")


def test_index_hash_drift_returns_chinese_conflict(desk) -> None:
    paths, server = desk
    _open_analyzer_draft(paths, server)
    index = _versions_dir(paths) / "index.json"
    index.write_text(index.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    port = _port(server)

    status, headers, body = _request(port, "/music")
    text = _assert_explained_failure(status, headers, body, code=409)
    assert "music_edit_regions_versions_index" in text
    assert "校验和" in text

    status, headers, body = _request(port, "/api/status")
    text = _assert_explained_failure(status, headers, body, code=409)
    assert "music_edit_regions_versions_index" in text
    assert "校验和" in json.loads(body.decode("utf-8"))["error"]


def test_extra_enabled_field_returns_chinese_validation_error(desk) -> None:
    paths, server = desk
    _open_analyzer_draft(paths, server)
    draft = _versions_dir(paths) / "draft.json"
    payload = json.loads(draft.read_text(encoding="utf-8"))
    payload["regions"]["regions"][0]["enabled"] = False
    draft.write_text(json.dumps(payload), encoding="utf-8")
    _retarget_hash(paths, draft, "music_edit_regions_version_draft")
    port = _port(server)

    status, headers, body = _request(port, "/music")
    text = _assert_explained_failure(status, headers, body, code=400)
    assert "enabled" in text
    assert "字段" in text

    status, headers, body = _request(port, "/api/music-desk")
    text = _assert_explained_failure(status, headers, body, code=400)
    assert "enabled" in text
    payload = json.loads(body.decode("utf-8"))
    assert "travel-director" in payload["hint"]


def test_confirm_passes_validator_locks_version_and_updates_project_step(desk) -> None:
    from director.music_edit_regions_versions import (
        RegionsConfirmGateError,
        list_regions_receipts,
        load_regions_draft,
        load_regions_version,
        require_confirmed_regions_version,
    )

    paths, server = desk
    _open_analyzer_draft(paths, server)
    port = _port(server)
    _status, opened = _json(port, "/api/music-desk")
    assert opened["acceptance"]["ok"] is True
    assert opened["read_only"] is False
    assert opened["source_music_sha8"] == "aaaaaaaa"

    page_status, _headers, page = _request(port, "/music")
    text = page.decode("utf-8")
    assert page_status == 200
    assert 'id="acceptance"' in text and "验收通过" in text
    assert "确认分区" in text
    confirm_tag = re.search(r'<button[^>]*id="confirm-version"[^>]*>', text)
    assert confirm_tag is not None and "disabled" not in confirm_tag.group(0)
    assert 'id="force-confirm"' in text
    assert re.search(r'id="force-confirm"[^>]*checked', text) is None
    assert "对比上次" in text and 'title="后续版本开放"' in text
    assert 'id="version-picker"' in text and "草稿" in text

    stale, stale_body = _post_json(
        port,
        "/api/regions-draft/confirm",
        {"expected_revision": "0" * 64, "force": False, "reason": ""},
    )
    assert stale == 409
    assert "revision" in stale_body["error"]
    assert load_regions_draft(paths) is not None

    code, locked = _post_json(
        port,
        "/api/regions-draft/confirm",
        {"expected_revision": opened["revision"], "force": False, "reason": ""},
    )
    assert code == 200, locked
    assert locked["read_only"] is True
    assert locked["status"] == "confirmed"
    assert locked["version_id"] == "regions-v01"
    assert locked["confirmed_at"]
    assert load_regions_draft(paths) is None

    stored = load_regions_version(paths, "regions-v01")
    assert stored.status == "confirmed"
    assert stored.confirmed_by == "user"
    receipts = [item for item in list_regions_receipts(paths) if item.action == "confirm"]
    assert len(receipts) == 1
    assert receipts[0].override is False
    assert receipts[0].reason is None

    assert require_confirmed_regions_version(paths, "regions-v01").version_id == "regions-v01"
    with pytest.raises(RegionsConfirmGateError):
        require_confirmed_regions_version(paths, "latest")
    with pytest.raises(RegionsConfirmGateError):
        require_confirmed_regions_version(paths, "draft")

    status_code, payload = _json(port, "/api/status")
    assert status_code == 200
    assert payload["regions_versions"]["confirmed_count"] == 1
    assert payload["progress"]["steps"][2]["title"] == "分段已确认"
    assert payload["progress"]["steps"][2]["state"] == "完成"

    page_status, _headers, page = _request(port, "/music")
    text = page.decode("utf-8")
    assert page_status == 200
    assert "已确认 v01" in text
    assert "aaaaaaaa" in text
    assert locked["confirmed_at"] in text
    assert "基于此版另开草稿" in text
    assert "<select disabled>" in text
    assert not (_versions_dir(paths) / "draft.json").exists()

    code, listing = _json(port, "/api/regions-versions")
    assert code == 200
    assert listing["versions"][0]["status"] == "confirmed"
    assert listing["versions"][0]["source_music_sha8"] == "aaaaaaaa"
    assert listing["versions"][0]["confirmed_at"] == locked["confirmed_at"]


def test_unknown_blocks_confirm_until_force_records_reason(desk) -> None:
    from director.music_edit_regions_versions import (
        list_regions_receipts,
        load_regions_draft,
        load_regions_version,
    )

    paths, server = desk
    document = _document()
    regions = [
        region.model_copy(update={"edit_role": "unknown"}) if region.region_id == "r2" else region
        for region in document.regions
    ]
    document = document.model_copy(update={"regions": regions})
    _open_analyzer_draft(paths, server, document)
    port = _port(server)
    _status, opened = _json(port, "/api/music-desk")
    assert opened["acceptance"]["ok"] is False
    assert opened["acceptance"]["unknown_region_ids"] == ["r2"]

    _page_status, _headers, page = _request(port, "/music")
    text = page.decode("utf-8")
    assert "还有 1 段待定角色" in text
    assert 'id="pick-unknown"' in text
    assert "验收未通过" not in text
    assert 'id="unknown-warning"' in text
    assert "这些分段的角色还没定" in text and "r2" in text
    confirm_tag = re.search(r'<button[^>]*id="confirm-version"[^>]*>', text)
    assert confirm_tag is not None and "disabled" in confirm_tag.group(0)

    code, body = _post_json(
        port,
        "/api/regions-draft/confirm",
        {"expected_revision": opened["revision"], "force": False, "reason": ""},
    )
    assert code == 400
    assert "r2" in body["error"]
    assert "普通确认" in body["error"]
    assert load_regions_draft(paths) is not None

    code, body = _post_json(
        port,
        "/api/regions-draft/confirm",
        {"expected_revision": opened["revision"], "force": True, "reason": "   "},
    )
    assert code == 400
    assert "原因" in body["error"]
    assert load_regions_draft(paths) is not None

    code, body = _post_json(
        port,
        "/api/regions-draft/confirm",
        {"expected_revision": opened["revision"], "force": False, "reason": "听过了"},
    )
    assert code == 400
    assert load_regions_draft(paths) is not None

    code, locked = _post_json(
        port,
        "/api/regions-draft/confirm",
        {
            "expected_revision": opened["revision"],
            "force": True,
            "reason": "听过了，先按未定角色锁定",
        },
    )
    assert code == 200, locked
    assert locked["read_only"] is True
    stored = load_regions_version(paths, locked["version_id"])
    assert stored.confirmed_by == "user"
    receipts = [item for item in list_regions_receipts(paths) if item.action == "confirm"]
    assert receipts[-1].override is True
    assert receipts[-1].reason == "听过了，先按未定角色锁定"


def test_confirmed_write_is_409_and_new_draft_copies_without_mutating(desk) -> None:
    from director.music_edit_regions_versions import load_regions_draft

    paths, server = desk
    document, opened = _open_analyzer_draft(paths, server)
    port = _port(server)
    code, locked = _post_json(
        port,
        "/api/regions-draft/confirm",
        {"expected_revision": opened["revision"], "force": False, "reason": ""},
    )
    assert code == 200, locked
    confirmed = _versions_dir(paths) / "confirmed" / "regions-v01.json"
    before = confirmed.read_bytes()

    code, body = _post_json(
        port,
        "/api/regions-draft",
        {"expected_revision": locked["revision"], "regions": _role_payload(document)},
    )
    assert code == 409
    assert "已确认" in body["error"]
    assert "不能修改" in body["error"]
    assert confirmed.read_bytes() == before
    assert load_regions_draft(paths) is None

    code, viewed = _json(port, "/api/music-desk?version=regions-v01")
    assert code == 200
    assert viewed["read_only"] is True
    assert viewed["version_id"] == "regions-v01"
    assert viewed["status"] == "confirmed"

    code, copied = _post_json(
        port, "/api/regions-draft/from-confirmed", {"version_id": "regions-v01"}
    )
    assert code == 200, copied
    assert copied["read_only"] is False
    assert copied["status"] == "draft"
    assert copied["version_id"] == "regions-v02"
    assert [item["edit_role"] for item in copied["regions"]] == [
        region.edit_role for region in document.regions
    ]
    assert confirmed.read_bytes() == before
    draft = load_regions_draft(paths)
    assert draft is not None
    assert draft.parent_version_id == "regions-v01"
    assert draft.regions_sha256 != "" 

    code, again = _post_json(
        port, "/api/regions-draft/from-confirmed", {"version_id": "regions-v01"}
    )
    assert code == 409
    assert "草稿" in again["error"]
    assert confirmed.read_bytes() == before

    _page_status, _headers, page = _request(port, "/music")
    text = page.decode("utf-8")
    assert "草稿" in text
    assert "已确认 v01" in text
    assert "<select disabled>" not in text


def test_version_picker_lists_history_confirmed_and_bound_track(desk) -> None:
    paths, server = desk
    document, opened = _open_analyzer_draft(paths, server)
    port = _port(server)
    code, _locked = _post_json(
        port,
        "/api/regions-draft/confirm",
        {"expected_revision": opened["revision"], "force": False, "reason": ""},
    )
    assert code == 200
    code, copied = _post_json(
        port, "/api/regions-draft/from-confirmed", {"version_id": "regions-v01"}
    )
    assert code == 200, copied
    roles = _role_payload(document)
    roles[1]["edit_role"] = "build"
    code, saved = _post_json(
        port,
        "/api/regions-draft",
        {"expected_revision": copied["revision"], "regions": roles},
    )
    assert code == 200, saved
    code, second = _post_json(
        port,
        "/api/regions-draft/confirm",
        {"expected_revision": saved["revision"], "force": False, "reason": ""},
    )
    assert code == 200, second
    assert second["version_id"] == "regions-v02"

    code, listing = _json(port, "/api/regions-versions")
    statuses = {item["version_id"]: item["status"] for item in listing["versions"]}
    assert statuses == {"regions-v01": "history", "regions-v02": "confirmed"}
    assert {item["source_music_sha8"] for item in listing["versions"]} == {"aaaaaaaa"}

    _page_status, _headers, page = _request(port, "/music")
    text = page.decode("utf-8")
    assert "已确认 v02" in text
    assert "历史确认 v01" in text
    assert "aaaaaaaa" in text
    assert second["confirmed_at"] in text
    assert "<select disabled>" in text
    assert "基于此版另开草稿" in text

    _page_status, _headers, older = _request(port, "/music?version=regions-v01")
    older_text = older.decode("utf-8")
    assert "历史确认 v01" in text or "历史确认 v01" in older_text
    assert "<select disabled>" in older_text
    selected = re.search(r'<option[^>]*value="regions-v01"[^>]*>', older_text)
    assert selected is not None and "selected" in selected.group(0)


def _pcm_wav(seconds: float = 0.5, rate: int = 8000) -> bytes:
    import math
    import struct
    import wave
    from io import BytesIO

    frames = bytearray()
    for index in range(int(rate * seconds)):
        sample = int(16000 * math.sin(2 * math.pi * 440 * index / rate))
        frames.extend(struct.pack("<h", sample))
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)
    return buffer.getvalue()


def test_peak_buckets_stay_bounded_for_a_ten_minute_track() -> None:
    import array

    from director.waveform_peaks import peak_buckets

    samples = array.array("h", [0]) * (8000 * 600)
    samples[8000] = 20000
    peaks = peak_buckets(samples, 8000)
    assert len(peaks) == 12000
    assert max(peaks) <= 1
    assert max(peaks) > 0


def test_waveform_peaks_are_cached_outside_project_state(desk, tmp_path: Path, monkeypatch) -> None:
    from director.project import load_project_state

    cache = tmp_path / "peaks-cache"
    monkeypatch.setenv("TRAVEL_DIRECTOR_PEAKS_CACHE", str(cache))
    paths, server = desk
    _freeze_wav(paths, _pcm_wav())
    _record_regions(paths)
    port = _port(server)

    status, payload = _json(port, "/api/waveform-peaks")
    assert status == 200, payload
    assert len(payload["source_sha256"]) == 64
    assert payload["peaks"]
    assert all(0 <= value <= 1 for value in payload["peaks"])
    cached = list(cache.glob("*.json"))
    assert len(cached) == 1
    assert cached[0].name == payload["source_sha256"] + ".json"
    assert not cached[0].resolve().is_relative_to(paths.root.resolve())
    state = load_project_state(paths)
    assert not any("peak" in key or "waveform" in key for key in state.completed_artifact_hashes)
    again, second = _json(port, "/api/waveform-peaks")
    assert again == 200
    assert second["peaks"] == payload["peaks"]


def test_music_timeline_tracks_positions_unknown_hatch_and_no_drag(desk) -> None:
    paths, server = desk
    document = _document()
    regions = [
        region.model_copy(update={"edit_role": "unknown"}) if region.region_id == "r2" else region
        for region in document.regions
    ]
    document = document.model_copy(
        update={
            "regions": regions,
            "beats_seconds": [0.5, 1.0],
            "downbeats_seconds": [0.5],
            "warnings": ["onset_rate_from_beat_grid_proxy"],
        }
    )
    _record_regions(paths, document)
    port = _port(server)
    status, headers, page = _request(port, "/music")
    text = page.decode("utf-8")

    assert status == 200
    assert "秋日骑行" not in text
    assert "60秒旅行视频" in text
    assert paths.root.name in text
    for label in ("音乐轨", "节拍", "分区轨", "镜头轨", "预留·未启用", "空槽·未选片"):
        assert label in text
    assert 'id="track-wave"' in text
    assert 'id="track-beats"' in text
    assert 'id="track-regions"' in text
    assert 'id="track-shots"' in text
    assert 'data-region-id="r1"' in text
    assert "left:0.000%;width:33.333%" in text
    assert "left:33.333%;width:40.000%" in text
    assert "left:73.333%;width:26.667%" in text
    assert 'class="blk unknown is-unknown"' in text or 'class="blk is-unknown unknown"' in text
    assert "repeating-linear-gradient" in text
    assert 'class="beat db"' in text
    assert "left:1.667%" in text
    assert "/vendor/wavesurfer/wavesurfer.min.js" in text
    assert "/vendor/wavesurfer/plugins/regions.min.js" in text
    assert "/vendor/wavesurfer/plugins/timeline.min.js" in text
    assert "cdn." not in text and "unpkg" not in text
    assert "drag:false" in text and "resize:false" in text
    assert "drag:true" not in text
    assert 'draggable="true"' not in text
    assert "<table" not in text
    assert "列表视图" in text
    assert "边界拖动：里程碑 B" in text
    script, _script_headers, body = _request(port, "/vendor/wavesurfer/wavesurfer.min.js")
    assert script == 200
    assert "javascript" in _script_headers.get("content-type", "")
    assert b"WaveSurfer" in body
    license_path = Path(__file__).resolve().parents[2] / "director" / "vendor" / "wavesurfer" / "LICENSE"
    assert "BSD" in license_path.read_text(encoding="utf-8")
