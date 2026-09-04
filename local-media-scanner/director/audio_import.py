"""Immutable import and local analysis of user-provided music."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field

from director.music_analysis import AudioAnalysisConfig, analyze_music
from director.project import (
    ProjectConflict,
    ProjectPaths,
    _sha256_file,
    load_project_state,
    record_supporting_artifact,
)
from director.schema import MusicStructure, StrictModel


SUPPORTED_MUSIC_SUFFIXES = {".wav", ".mp3", ".m4a"}
MAX_MUSIC_DURATION_SECONDS = 600.0
MIME_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}
CONTAINER_NAMES = {
    ".wav": {"wav"},
    ".mp3": {"mp3"},
    ".m4a": {"m4a", "mov", "mp4"},
}


class ImportedMusicAsset(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    source_kind: Literal["user_provided"] = "user_provided"
    original_absolute_path: str = Field(min_length=1)
    frozen_relative_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    duration_seconds: float = Field(gt=0.0)
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)
    mime_type: Literal["audio/wav", "audio/mpeg", "audio/mp4"]
    license_status: Literal["unverified"] = "unverified"


def _probe_audio(path: Path) -> tuple[float, int, int, str]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name:stream=codec_type,codec_name,sample_rate,channels",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("ffprobe is required to validate uploaded music") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or "ffprobe could not decode uploaded music"
        raise ValueError(f"uploaded music is not decodable: {message}")
    try:
        payload = json.loads(completed.stdout)
        stream = next(
            item
            for item in payload.get("streams", [])
            if item.get("codec_type") == "audio"
        )
        duration = float(payload["format"]["duration"])
        format_name = str(payload["format"]["format_name"])
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        raise ValueError("uploaded music has incomplete audio metadata") from exc
    if duration <= 0 or sample_rate <= 0 or channels <= 0:
        raise ValueError("uploaded music has invalid audio metadata")
    return duration, sample_rate, channels, format_name


def _atomic_copy_verified(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_file, tempfile.NamedTemporaryFile(
        mode="wb",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
        digest = hashlib.sha256()
        try:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
                temporary.write(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    if digest.hexdigest() != expected_sha256:
        temporary_path.unlink(missing_ok=True)
        raise ProjectConflict("uploaded music changed while it was being frozen")
    os.replace(temporary_path, destination)


def _load_recorded_json(
    paths: ProjectPaths,
    path: Path,
    state_key: str,
    model: type[ImportedMusicAsset] | type[MusicStructure],
) -> ImportedMusicAsset | MusicStructure | None:
    state = load_project_state(paths)
    recorded_hash = state.completed_artifact_hashes.get(state_key)
    if recorded_hash is None:
        if path.exists():
            raise ProjectConflict(f"untracked supporting artifact exists: {state_key}")
        return None
    if not path.is_file() or _sha256_file(path) != recorded_hash:
        raise ProjectConflict(f"supporting artifact hash drifted: {state_key}")
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def load_music_evidence(
    paths: ProjectPaths,
) -> tuple[ImportedMusicAsset, MusicStructure] | None:
    """Read and verify a complete frozen-music checkpoint without writing."""

    asset = _load_recorded_json(
        paths,
        paths.generated_music,
        "music_asset",
        ImportedMusicAsset,
    )
    structure = _load_recorded_json(
        paths,
        paths.music_structure,
        "music_structure",
        MusicStructure,
    )
    if asset is None and structure is None:
        return None
    if asset is None or structure is None:
        raise ProjectConflict("music import checkpoint is incomplete")
    assert isinstance(asset, ImportedMusicAsset)
    assert isinstance(structure, MusicStructure)
    frozen = (paths.root / asset.frozen_relative_path).resolve()
    if not frozen.is_relative_to(paths.root.resolve()) or not frozen.is_file():
        raise ProjectConflict("frozen music asset is missing")
    if _sha256_file(frozen) != asset.source_sha256:
        raise ProjectConflict("frozen music asset hash drifted")
    if structure.source_sha256 != asset.source_sha256:
        raise ProjectConflict("music analysis is bound to a different source")
    return asset, structure


def freeze_and_analyze_music(
    paths: ProjectPaths,
    source: Path,
) -> tuple[ImportedMusicAsset, MusicStructure]:
    """Freeze one local music file and reuse or create its measured analysis."""

    resolved = source.resolve()
    if not resolved.is_file():
        raise ValueError(f"music file does not exist: {resolved}")
    suffix = resolved.suffix.lower()
    if suffix not in SUPPORTED_MUSIC_SUFFIXES:
        raise ValueError("music must be WAV, MP3, or M4A")
    source_sha256 = _sha256_file(resolved)

    existing_asset = _load_recorded_json(
        paths,
        paths.generated_music,
        "music_asset",
        ImportedMusicAsset,
    )
    if existing_asset is not None:
        assert isinstance(existing_asset, ImportedMusicAsset)
        if existing_asset.source_sha256 != source_sha256:
            raise ProjectConflict(
                "a different music file is already bound to this project"
            )
        frozen = (paths.root / existing_asset.frozen_relative_path).resolve()
        if not frozen.is_relative_to(paths.root.resolve()) or not frozen.is_file():
            raise ProjectConflict("frozen music asset is missing")
        if _sha256_file(frozen) != existing_asset.source_sha256:
            raise ProjectConflict("frozen music asset hash drifted")
        asset = existing_asset
    else:
        duration, sample_rate, channels, format_name = _probe_audio(resolved)
        detected_containers = set(format_name.lower().split(","))
        if not detected_containers.intersection(CONTAINER_NAMES[suffix]):
            raise ValueError(
                f"music container does not match {suffix} extension: {format_name}"
            )
        if duration > MAX_MUSIC_DURATION_SECONDS:
            raise ValueError("uploaded music must not exceed 10 minutes")
        relative = Path("generation") / "assets" / f"music-{source_sha256[:16]}{suffix}"
        frozen = paths.root / relative
        if frozen.exists():
            if not frozen.is_file() or _sha256_file(frozen) != source_sha256:
                raise ProjectConflict("frozen music destination already differs")
        else:
            _atomic_copy_verified(resolved, frozen, source_sha256)
        asset = ImportedMusicAsset(
            original_absolute_path=str(resolved),
            frozen_relative_path=relative.as_posix(),
            source_sha256=source_sha256,
            size_bytes=frozen.stat().st_size,
            duration_seconds=round(duration, 6),
            sample_rate=sample_rate,
            channels=channels,
            mime_type=MIME_TYPES[suffix],
        )
        record_supporting_artifact(
            paths,
            paths.generated_music,
            asset,
            state_key="music_asset",
        )

    existing_structure = _load_recorded_json(
        paths,
        paths.music_structure,
        "music_structure",
        MusicStructure,
    )
    if existing_structure is not None:
        assert isinstance(existing_structure, MusicStructure)
        if existing_structure.source_sha256 != asset.source_sha256:
            raise ProjectConflict("music analysis is bound to a different source")
        return asset, existing_structure

    try:
        structure = analyze_music(frozen, AudioAnalysisConfig())
    except Exception as exc:
        raise ValueError(f"local music analysis failed: {exc}") from exc
    if structure.source_sha256 != asset.source_sha256:
        raise ProjectConflict("music analysis source hash does not match frozen asset")
    record_supporting_artifact(
        paths,
        paths.music_structure,
        structure,
        state_key="music_structure",
    )
    return asset, structure
