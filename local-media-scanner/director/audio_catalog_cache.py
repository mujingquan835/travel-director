"""Local catalog cache invalidated by source inventory changes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from director.audio_catalog import AudioCatalog, build_audio_catalog, resolve_audio_root


def write_json_if_changed(path: Path, payload: dict) -> None:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as stream:
            name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def inventory_signature(root: Path) -> str:
    if not root.is_dir():
        raise ValueError(f"Audio library does not exist: {root}")
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_dir() or path.suffix.lower() in {".wav", ".mp3", ".m4a"}:
            stat = path.stat()
            rows.append((str(path.relative_to(root)), path.is_dir(), stat.st_size,
                         stat.st_mtime_ns, stat.st_ctime_ns))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def get_audio_catalog(root: Path | None = None) -> tuple[AudioCatalog, str]:
    root = (root or resolve_audio_root()).resolve()
    cache_root = Path(os.environ.get("TRAVEL_DIRECTOR_AUDIO_CACHE", str(
        Path.home() / ".cache" / "travel-director" / "audio")))
    key = hashlib.sha256(str(root).encode()).hexdigest()
    cache_path = cache_root / f"{key}.json"
    signature = inventory_signature(root)
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if (payload["version"] == 1 and payload["root"] == str(root)
                and payload["inventory"] == signature):
            return AudioCatalog.model_validate(payload["catalog"]), signature
    except (OSError, ValueError, KeyError, TypeError):
        pass
    catalog = build_audio_catalog(root)
    if inventory_signature(root) != signature:
        raise ValueError("Audio library changed during scanning; retry to refresh")
    write_json_if_changed(cache_path, {
        "version": 1, "root": str(root), "inventory": signature,
        "catalog": catalog.model_dump(mode="json"),
    })
    return catalog, signature
