"""Import one local track into a new music-version project.

The desk accepts the file only from a loopback client. ``create_music_version``
forks the original parent (a child is never nested under another child) and
``freeze_and_analyze_music`` measures beats. Region analysis then opens a draft.
The parent project is not rewritten.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from director.audio_import import (
    CONTAINER_NAMES,
    MAX_MUSIC_DURATION_SECONDS,
    SUPPORTED_MUSIC_SUFFIXES,
    _probe_audio,
    freeze_and_analyze_music,
    load_music_evidence,
)
from director.music_edit_regions import EditRegionConfig, build_project_music_edit_regions, load_music_edit_regions
from director.music_version import create_music_version
from director.project import ProjectConflict, open_project


MAX_MUSIC_IMPORT_BYTES = 100 * 1024 * 1024
_BOUNDARY_RE = re.compile(r"""boundary=(?:"([^"]+)"|([^;\s]+))""", re.IGNORECASE)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def is_loopback_host(host: str | None) -> bool:
    """True only for this machine. LAN clients are refused even if the port is open."""

    if not host:
        return False
    text = host.strip().lower()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if text.startswith("::ffff:"):
        text = text.removeprefix("::ffff:")
    if "%" in text:
        text = text.split("%", 1)[0]
    return text in _LOOPBACK_HOSTS


def parse_music_upload(content_type: str, body: bytes) -> tuple[str, bytes]:
    """Return ``(filename, bytes)`` for the ``music`` part. Raises ``ValueError``."""

    if "multipart/form-data" not in (content_type or "").lower():
        raise ValueError("请用表单上传音乐文件。")
    match = _BOUNDARY_RE.search(content_type)
    if match is None:
        raise ValueError("上传没有 boundary。")
    boundary = (match.group(1) or match.group(2)).encode("utf-8", "surrogateescape")
    filename: str | None = None
    payload: bytes | None = None
    for chunk in body.split(b"--" + boundary):
        if chunk.startswith(b"--"):
            break
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        elif chunk.startswith(b"\n"):
            chunk = chunk[1:]
        if b"\r\n\r\n" in chunk:
            header_blob, rest = chunk.split(b"\r\n\r\n", 1)
            separator = b"\r\n"
        elif b"\n\n" in chunk:
            header_blob, rest = chunk.split(b"\n\n", 1)
            separator = b"\n"
        else:
            continue
        if rest.endswith(separator):
            rest = rest[: -len(separator)]
        disposition = ""
        for line in header_blob.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("content-disposition:"):
                disposition = line.split(":", 1)[1].strip()
        if _disposition_param(disposition, "name") != "music":
            continue
        filename = _disposition_param(disposition, "filename") or ""
        payload = rest
        break
    if payload is None:
        raise ValueError("表单里没有音乐文件。")
    safe = _safe_filename(filename or "")
    suffix = Path(safe).suffix.lower()
    if suffix not in SUPPORTED_MUSIC_SUFFIXES:
        raise ValueError("只接受 mp3、m4a、wav。")
    if not payload:
        raise ValueError("音乐文件是空的。")
    if len(payload) > MAX_MUSIC_IMPORT_BYTES:
        raise ValueError("文件太大。导入上限是 100MB。")
    return safe, payload


def resolve_family_parent(project: Path) -> Path:
    """Return the original project. A music-version child points back at it."""

    root = project.resolve()
    record = root / "music_version.json"
    if not record.is_file():
        return root
    try:
        payload = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("这份音乐版本的来源记录读不出来。") from exc
    raw = payload.get("parent_project") if isinstance(payload, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("这份音乐版本没有原来的项目路径。")
    parent = Path(raw).expanduser().resolve()
    if not parent.is_dir():
        raise ValueError("原来的项目目录已经不在了。")
    return parent


def list_music_family(project: Path) -> list[dict[str, object]]:
    """Parent first, then ``{parent}-music-*`` siblings that still point at it."""

    try:
        parent = resolve_family_parent(project)
    except ValueError:
        parent = project.resolve()
    current = project.resolve()
    items = [
        {
            "path": str(parent),
            "label": _family_label(parent, original=True),
            "current": parent == current,
        }
    ]
    prefix = f"{parent.name}-music-"
    try:
        children = sorted(
            path for path in parent.parent.iterdir() if path.is_dir() and path.name.startswith(prefix)
        )
    except OSError:
        children = []
    for child in children:
        record = child / "music_version.json"
        if not record.is_file():
            continue
        try:
            linked = json.loads(record.read_text(encoding="utf-8")).get("parent_project")
            if not isinstance(linked, str) or Path(linked).expanduser().resolve() != parent:
                continue
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        resolved = child.resolve()
        items.append(
            {
                "path": str(resolved),
                "label": _family_label(resolved, original=False),
                "current": resolved == current,
            }
        )
    return items


@dataclass
class MusicImportStatus:
    job_id: str
    phase: str
    message: str
    project_path: str | None = None
    draft_version_id: str | None = None
    error: str | None = None
    beat_backend: str | None = None
    beat_backend_note: str | None = None
    history: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def as_dict(self) -> dict[str, object]:
        with self.lock:
            return {
                "job_id": self.job_id,
                "phase": self.phase,
                "message": self.message,
                "project_path": self.project_path,
                "draft_version_id": self.draft_version_id,
                "error": self.error,
                "beat_backend": self.beat_backend,
                "beat_backend_note": self.beat_backend_note,
                "history": list(self.history),
            }


def import_jobs(server: object) -> dict[str, MusicImportStatus]:
    jobs = getattr(server, "music_import_jobs", None)
    if isinstance(jobs, dict):
        return jobs
    jobs = {}
    setattr(server, "music_import_jobs", jobs)
    return jobs


def start_music_import(
    parent_root: Path,
    filename: str,
    payload: bytes,
    jobs: dict[str, MusicImportStatus],
) -> MusicImportStatus:
    """Accept bytes already stored in memory and analyze them on a daemon thread."""

    import secrets

    job_id = secrets.token_hex(8)
    status = MusicImportStatus(
        job_id=job_id,
        phase="建版本",
        message="正在建立新的音乐版本。",
        history=["建版本"],
    )
    jobs[job_id] = status
    thread = threading.Thread(
        target=run_music_import,
        args=(parent_root, filename, payload, status),
        name=f"music-import-{job_id}",
        daemon=True,
    )
    thread.start()
    return status


def run_music_import(
    parent_root: Path,
    filename: str,
    payload: bytes,
    status: MusicImportStatus,
) -> None:
    """Fork, analyze, and open a draft. Failures stay on ``status`` and do not touch the parent."""

    temporary: Path | None = None
    try:
        parent = open_project(parent_root)
        if load_music_evidence(parent) is None:
            raise ValueError("还没有固定的配乐，不能换音乐。")
        suffix = Path(filename).suffix.lower()
        descriptor, raw_name = tempfile.mkstemp(prefix="music-import-", suffix=suffix)
        temporary = Path(raw_name)
        os.close(descriptor)
        temporary.write_bytes(payload)
        _validate_audio_file(temporary)
        _update(status, phase="建版本", message="正在建立新的音乐版本。")
        child = create_music_version(parent, temporary)
        _update(status, phase="拍点", message="正在分析拍点。")
        _asset, structure = freeze_and_analyze_music(child, temporary)
        note = structure.beat_backend_note or ""
        backend = structure.beat_backend or ""
        _update(
            status,
            phase="分区",
            message=("正在做分区分析。" + note).strip(),
            beat_backend=backend,
            beat_backend_note=note,
        )
        build_project_music_edit_regions(child.root, EditRegionConfig(shot_style="travel"))
        regions = load_music_edit_regions(child)
        if regions is None:
            raise ValueError("分区写完了，但是读不回来。")
        from director.music_edit_regions_versions import save_regions_draft

        draft = save_regions_draft(child, regions)
        _update(
            status,
            phase="完成",
            message=("分析完成，已切到新草稿。" + note).strip(),
            project_path=str(child.root.resolve()),
            draft_version_id=draft.version_id,
            beat_backend=backend,
            beat_backend_note=note,
            error=None,
        )
    except (ProjectConflict, ValueError, OSError) as exc:
        message = chinese_import_error(exc)
        _update(status, phase="失败", message=message, error=message)
    except Exception as exc:
        message = f"导入失败：{exc}"
        _update(status, phase="失败", message=message, error=message)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def chinese_import_error(exc: BaseException) -> str:
    text = str(exc).strip()
    if text.startswith(("还没有", "只接受", "请用", "文件", "表单", "上传", "音乐", "这首", "这份", "原来")):
        return text
    if "must differ" in text:
        return "这首和当前配乐是同一个文件，没有新建版本。"
    if "frozen parent" in text or "music_edit_regions requires frozen music" in text:
        return "还没有固定的配乐，不能换音乐。"
    if "different lineage" in text:
        return "目标目录已经有一份不同的音乐版本。"
    if "creative source artifact missing" in text or "creative source artifact" in text:
        missing = text.split(":")[-1].strip() or "视觉阶段"
        return f"这个项目缺少视觉阶段（{missing}），现有的换音乐版本建不起来。"
    if "10 minutes" in text:
        return "音乐不能超过 10 分钟。"
    if "WAV, MP3, or M4A" in text:
        return "只接受 mp3、m4a、wav。"
    if "container does not match" in text:
        return "文件内容和扩展名对不上。"
    if "not decodable" in text or "ffprobe" in text or "incomplete audio metadata" in text:
        return "这个文件解不出来，请换一首 wav、mp3 或 m4a。"
    if "local music analysis failed" in text:
        return f"拍点分析失败：{text}"
    return f"导入失败：{text}"


def _validate_audio_file(path: Path) -> None:
    suffix = path.suffix.lower()
    duration, _sample_rate, _channels, format_name = _probe_audio(path)
    detected = set(format_name.lower().split(","))
    if not detected.intersection(CONTAINER_NAMES[suffix]):
        raise ValueError(f"music container does not match {suffix} extension: {format_name}")
    if duration > MAX_MUSIC_DURATION_SECONDS:
        raise ValueError("uploaded music must not exceed 10 minutes")


def _update(status: MusicImportStatus, **fields: object) -> None:
    with status.lock:
        phase = fields.get("phase")
        if isinstance(phase, str) and phase != status.phase:
            status.history.append(phase)
        for key, value in fields.items():
            setattr(status, key, value)


def _safe_filename(filename: str) -> str:
    cleaned = filename.replace("\\", "/").split("/")[-1].strip()
    if not cleaned or cleaned in {".", ".."} or "\x00" in cleaned:
        raise ValueError("音乐文件名无效。")
    return cleaned


def _disposition_param(header: str, key: str) -> str | None:
    match = re.search(
        rf'(?:^|;)\s*{re.escape(key)}\s*=\s*(?:"([^"]*)"|([^;]*))',
        header,
        re.IGNORECASE,
    )
    if match is None:
        return None
    value = match.group(1) if match.group(1) is not None else match.group(2)
    return value.strip()


def _family_label(path: Path, *, original: bool) -> str:
    title = "原来的配乐" if original else "换过的配乐"
    digest = ""
    record = path / "music_version.json"
    if record.is_file():
        try:
            raw = json.loads(record.read_text(encoding="utf-8")).get("selected_music_sha256")
            if isinstance(raw, str) and raw:
                digest = raw[:8]
        except (OSError, json.JSONDecodeError, AttributeError):
            digest = ""
    suffix = f" · {digest}" if digest else ""
    return f"{path.name} · {title}{suffix}"
