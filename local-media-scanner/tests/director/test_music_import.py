"""Import a local track as a new music version without touching the parent."""

from __future__ import annotations

import hashlib
import http.client
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from director.audio_import import freeze_and_analyze_music
from director.confirm_serve import handle_confirm_request, start_confirm_desk
from director.music_edit_regions import (
    EditRegionConfig,
    build_project_music_edit_regions,
    load_music_edit_regions,
)
from director.music_edit_regions_versions import load_regions_draft, save_regions_draft
from director.music_import import (
    MAX_MUSIC_IMPORT_BYTES,
    is_loopback_host,
    parse_music_upload,
    resolve_family_parent,
)
from director.project import open_project
from director.schema import MusicStructure
from tests.director.test_skill_summary import completed_project


def _wav(path: Path, *, seconds: float = 8.0, salt: float = 0.0) -> None:
    rate = 22_050
    count = int(seconds * rate)
    audio = np.zeros(count, dtype=np.float32)
    click = np.exp(-np.linspace(0.0, 6.0, int(0.03 * rate))).astype(np.float32)
    step = int(0.5 * rate)
    for start in range(0, count, step):
        end = min(start + len(click), count)
        audio[start:end] += 0.7 * click[: end - start]
    if salt:
        audio[-1] = np.float32(salt)
    sf.write(path, audio, rate, subtype="PCM_16")


def _files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _multipart(filename: str, payload: bytes) -> tuple[bytes, str]:
    boundary = "----travelDirectorMusic"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="music"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    body = head + payload + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _post_file(port: int, filename: str, payload: bytes) -> tuple[int, dict]:
    body, content_type = _multipart(filename, payload)
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.request(
            "POST",
            "/api/music-import",
            body=body,
            headers={"Content-Type": content_type, "Content-Length": str(len(body))},
        )
        response = connection.getresponse()
        raw = response.read()
        return response.status, json.loads(raw.decode("utf-8"))
    finally:
        connection.close()


def _json(port: int, path: str) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def _post_json(port: int, path: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def _poll(port: int, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    payload: dict = {}
    while time.time() < deadline:
        status, payload = _json(port, f"/api/music-import/status?id={job_id}")
        assert status == 200, payload
        if payload["phase"] in {"完成", "失败"}:
            return payload
        time.sleep(0.2)
    raise AssertionError(payload)


def _children(parent: Path) -> list[Path]:
    prefix = f"{parent.name}-music-"
    return sorted(path for path in parent.parent.iterdir() if path.is_dir() and path.name.startswith(prefix))


def test_loopback_and_upload_limits() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("::ffff:127.0.0.1")
    assert not is_loopback_host("192.0.2.10")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("")
    body, content_type = _multipart("../outside.wav", b"RIFFxxxx")
    filename, payload = parse_music_upload(content_type, body)
    assert filename == "outside.wav"
    assert payload == b"RIFFxxxx"
    body, content_type = _multipart("notes.txt", b"hello")
    try:
        parse_music_upload(content_type, body)
    except ValueError as exc:
        assert "只接受" in str(exc)
    else:
        raise AssertionError("txt was accepted")


def test_import_refuses_non_loopback_oversize_and_unfrozen_parent(tmp_path: Path) -> None:
    root = completed_project(tmp_path)
    server = start_confirm_desk(root, host="127.0.0.1", port=0, recent_path=tmp_path / "recent.json")
    port = int(server.server_address[1])
    try:
        refused = handle_confirm_request(
            server,
            "POST",
            "/api/music-import",
            {"Content-Type": "multipart/form-data; boundary=abc"},
            b"ignored",
            client_host="192.0.2.10",
        )
        assert refused.status == 403
        assert "本机" in refused.body.decode("utf-8")
        assert _children(root) == []

        status, payload = _post_file(port, "clip.wav", b"not-a-real-wav")
        assert status == 400, payload
        assert "固定的配乐" in payload["error"]
        assert _children(root) == []

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.putrequest("POST", "/api/music-import")
        connection.putheader("Content-Type", "multipart/form-data; boundary=abc")
        connection.putheader("Content-Length", str(MAX_MUSIC_IMPORT_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()
        assert response.status == 400
        assert "太大" in body

        other = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        other.putrequest("POST", "/api/project")
        other.putheader("Content-Type", "application/json")
        other.putheader("Content-Length", "70000")
        other.endheaders()
        limited = other.getresponse()
        limited_body = limited.read().decode("utf-8")
        other.close()
        assert limited.status == 400
        assert "too large" in limited_body
    finally:
        server.shutdown()
        server.server_close()


def test_import_analyzes_a_new_draft_and_keeps_the_old_version(tmp_path: Path) -> None:
    root = completed_project(tmp_path)
    paths = open_project(root)
    wav_a = tmp_path / "first.wav"
    wav_b = tmp_path / "second.wav"
    _wav(wav_a, salt=0.02)
    _wav(wav_b, salt=0.2)
    freeze_and_analyze_music(paths, wav_a)
    build_project_music_edit_regions(paths.root, EditRegionConfig(shot_style="travel"))
    regions = load_music_edit_regions(paths)
    assert regions is not None
    save_regions_draft(paths, regions)
    parent_draft = (paths.root / "music_edit_regions_versions" / "draft.json").read_bytes()
    before = _files(paths.root)

    server = start_confirm_desk(
        paths.root, host="127.0.0.1", port=0, recent_path=tmp_path / "recent.json"
    )
    port = int(server.server_address[1])
    try:
        page = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        page.request("GET", "/music")
        opened = page.getresponse()
        html = opened.read().decode("utf-8")
        page.close()
        assert opened.status == 200
        assert "导入 / 换音乐" in html
        assert 'id="import-music"' in html
        assert 'id="music-picker"' in html

        same_status, same = _post_file(port, "first.wav", wav_a.read_bytes())
        assert same_status == 202, same
        same_done = _poll(port, same["job_id"])
        assert same_done["phase"] == "失败"
        assert "同一个文件" in same_done["error"]
        assert _children(paths.root) == []

        bad_status, bad = _post_file(port, "broken.wav", b"this is not audio")
        assert bad_status == 202, bad
        bad_done = _poll(port, bad["job_id"])
        assert bad_done["phase"] == "失败"
        assert "解不出来" in bad_done["error"]
        assert _children(paths.root) == []

        text_status, text = _post_file(port, "notes.txt", b"hello")
        assert text_status == 400
        assert "只接受" in text["error"]

        status, started = _post_file(port, "second.wav", wav_b.read_bytes())
        assert status == 202, started
        done = _poll(port, started["job_id"])
        assert done["phase"] == "完成", done
        assert done["history"] == ["建版本", "拍点", "分区", "完成"]
        assert done["beat_backend"] == "librosa"
        assert "回退" in (done["beat_backend_note"] or "")

        child = Path(str(done["project_path"]))
        digest = hashlib.sha256(wav_b.read_bytes()).hexdigest()
        assert child.name == f"{paths.root.name}-music-{digest[:16]}"
        assert child.parent == paths.root.parent
        assert _files(paths.root) == before
        assert (paths.root / "music_edit_regions_versions" / "draft.json").read_bytes() == parent_draft

        child_paths = open_project(child)
        draft = load_regions_draft(child_paths)
        assert draft is not None
        assert draft.status == "draft"
        assert draft.version_id == done["draft_version_id"]
        structure = MusicStructure.model_validate_json(child_paths.music_structure.read_text())
        assert structure.beat_backend == "librosa"
        assert structure.source_sha256 != regions.source_sha256
        assert resolve_family_parent(child) == paths.root.resolve()

        switched, child_status = _post_json(port, "/api/project", {"path": str(child)})
        assert switched == 200, child_status
        assert child_status["project_path"] == str(child.resolve())
        back, parent_status = _post_json(port, "/api/project", {"path": str(paths.root)})
        assert back == 200, parent_status
        assert parent_status["project_path"] == str(paths.root.resolve())
        music = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        music.request("GET", "/music")
        music_page = music.getresponse().read().decode("utf-8")
        music.close()
        assert child.name in music_page
        assert "原来的配乐" in music_page
        assert "换过的配乐" in music_page
        assert _files(paths.root) == before
    finally:
        server.shutdown()
        server.server_close()
