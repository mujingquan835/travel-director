"""Local cataloging and indexing of SFX and Music library."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Literal

from pydantic import Field

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from director.schema import StrictModel


class CatalogVersion(StrictModel):
    version_tag: Literal["czg1", "czg2", "czg3", "full", "30s", "60s", "other"]
    relative_path: str
    duration_seconds: float = Field(ge=0.0)
    format: Literal["wav", "mp3", "m4a"]


class CatalogTrack(StrictModel):
    track_id: str
    title: str
    category: str
    versions: dict[str, CatalogVersion]
    keywords: list[str]


class SfxEntry(StrictModel):
    sfx_id: str
    name: str
    category: Literal["上升音效", "风声", "收尾", "DJi无人机音效", "环境"]
    role: Literal[
        "hook_hit",
        "hook_subdrop",
        "riser",
        "whoosh",
        "outro_hit",
        "outro_piano",
        "env_drone",
        "env_ambient",
    ]
    relative_path: str
    duration_seconds: float = Field(ge=0.0)


class AudioCatalog(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    music_root: str
    sfx_root: str
    tracks: list[CatalogTrack]
    sfx: list[SfxEntry]
    scan_timestamp: str


def resolve_audio_root() -> Path:
    """Resolve the root directory of the audio library."""
    env_root = os.environ.get("TRAVEL_DIRECTOR_AUDIO_ROOT")
    if env_root:
        path = Path(env_root).resolve()
        if not path.exists() or not path.is_dir():
            raise ValueError(f"TRAVEL_DIRECTOR_AUDIO_ROOT does not exist or is not a directory: {path}")
        return path

    config_path = Path.home() / ".config" / "travel-director" / "audio.toml"
    if config_path.exists() and config_path.is_file():
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            if "audio_root" in config:
                path = Path(config["audio_root"]).resolve()
                if not path.exists() or not path.is_dir():
                    raise ValueError(f"audio_root from config does not exist or is not a directory: {path}")
                return path
        except Exception:
            pass

    fallback = Path("/Users/meimaodawang/Documents/音效及音乐").resolve()
    if not fallback.exists() or not fallback.is_dir():
        raise ValueError(f"Fallback audio root does not exist or is not a directory: {fallback}")
    return fallback


def _probe_duration(path: Path) -> float:
    """Measure duration of an audio file in seconds using ffprobe."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
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
        raise ValueError("ffprobe is required") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or "ffprobe error"
        raise ValueError(f"could not probe {path.name}: {message}")
    try:
        payload = json.loads(completed.stdout)
        duration = float(payload["format"]["duration"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid duration format for {path.name}") from exc
    return duration


def _classify_version_tag(filename: str) -> str:
    """Parse the filename to determine version tag."""
    name = filename.lower()
    if "czg1" in name:
        return "czg1"
    if "czg2" in name:
        return "czg2"
    if "czg3" in name:
        return "czg3"
    if "full" in name:
        return "full"
    if "30s" in name:
        return "30s"
    if "60s" in name:
        return "60s"
    
    # Check numbers like 55s-64s range + '_缩混'
    if re.search(r'\d+s.*_缩混', name):
        # Determine if it's closer to 30 or 60 based on rules, or simply assume 60s as per instructions.
        # Instruction: Contains '60s' or starts with a number like 55s-64s range + '_缩混' -> "60s"
        # We'll map anything matching `\d+s` that isn't 30s to 60s if it has _缩混 or similar, 
        # but let's be more precise:
        if re.search(r'(?:[5-6][0-9]s|60s).*缩混', name):
            return "60s"
        if re.search(r'(?:[2-3][0-9]s|30s).*缩混', name):
            return "30s"
        return "60s" # Fallback for this specific rule
        
    return "full"


def _classify_sfx_role(filename: str, category: str) -> str:
    """Map filenames to roles based on category and name patterns."""
    name = filename.lower()
    
    if category == "上升音效":
        if "hit" in name:
            return "hook_hit"
        if "subdrop" in name:
            return "hook_subdrop"
        return "riser" # default fallback
        
    if category == "风声":
        if "riser" in name:
            return "riser"
        if "whoosh" in name:
            return "whoosh"
        return "env_ambient"

    if category == "收尾":
        if "hit" in name or "cliff" in name or "event" in name:
            return "outro_hit"
        if "piano" in name:
            return "outro_piano"
        return "outro_hit"
        
    if "dji" in category.lower() or "dji" in name:
        return "env_drone"
        
    return "env_ambient"


def _extract_keywords(category: str) -> list[str]:
    """Split category name by delimiters into keywords."""
    # Split by delimiters: "｜", " ", "、"
    tokens = re.split(r'[｜ 、]+', category)
    return [t.strip() for t in tokens if t.strip()]


def scan_music_catalog(music_root: Path) -> list[CatalogTrack]:
    """Walk the directory tree and build the music catalog."""
    tracks: dict[str, CatalogTrack] = {}
    valid_exts = {".wav", ".mp3", ".m4a"}
    
    for root_dir, dirs, files in os.walk(music_root):
        root_path = Path(root_dir)
        rel_root = root_path.relative_to(music_root)
        
        # Determine category and track title
        parts = rel_root.parts
        if not parts:
            continue
            
        category = parts[0]
        keywords = _extract_keywords(category)
        
        # Find audio files in current directory
        audio_files = [f for f in files if Path(f).suffix.lower() in valid_exts]
        if not audio_files:
            continue
            
        if len(parts) > 1:
            # We are in a subdirectory, treat the subdirectory name as the track title
            title = parts[1]
            track_id = str(rel_root) # use relative path as track_id
        else:
            # Files directly in category dir
            for f in audio_files:
                title = Path(f).stem
                track_id = f"{category}/{title}"
                f_path = root_path / f
                rel_path = f_path.relative_to(music_root).as_posix()
                try:
                    duration = _probe_duration(f_path)
                except ValueError:
                    continue
                version_tag = _classify_version_tag(f)
                fmt = f_path.suffix.lower()[1:]
                if fmt not in ["wav", "mp3", "m4a"]:
                    continue
                
                version = CatalogVersion(
                    version_tag=version_tag, # type: ignore
                    relative_path=rel_path,
                    duration_seconds=duration,
                    format=fmt # type: ignore
                )
                
                tracks[track_id] = CatalogTrack(
                    track_id=track_id,
                    title=title,
                    category=category,
                    versions={version_tag: version},
                    keywords=keywords
                )
            continue
            
        # Add files from subdirectory as versions
        if track_id not in tracks:
            tracks[track_id] = CatalogTrack(
                track_id=track_id,
                title=title,
                category=category,
                versions={},
                keywords=keywords
            )
            
        for f in audio_files:
            f_path = root_path / f
            rel_path = f_path.relative_to(music_root).as_posix()
            try:
                duration = _probe_duration(f_path)
            except ValueError:
                continue
            version_tag = _classify_version_tag(f)
            fmt = f_path.suffix.lower()[1:]
            if fmt not in ["wav", "mp3", "m4a"]:
                continue
                
            version = CatalogVersion(
                version_tag=version_tag, # type: ignore
                relative_path=rel_path,
                duration_seconds=duration,
                format=fmt # type: ignore
            )
            tracks[track_id].versions[version_tag] = version

    # Filter out empty tracks
    return [t for t in tracks.values() if t.versions]


def scan_sfx_catalog(sfx_root: Path) -> list[SfxEntry]:
    """Walk the SFX directory and build the SFX catalog."""
    sfx_list: list[SfxEntry] = []
    valid_exts = {".wav", ".mp3", ".m4a"}
    
    # Note: Allowed categories are limited by SfxEntry model.
    # We will map directory names to allowed categories or ignore them.
    allowed_categories = {"上升音效", "风声", "收尾", "DJi无人机音效", "环境"}
    
    for root_dir, _, files in os.walk(sfx_root):
        root_path = Path(root_dir)
        try:
            rel_root = root_path.relative_to(sfx_root)
        except ValueError:
            continue
            
        parts = rel_root.parts
        if not parts:
            continue
            
        raw_category = parts[0]
        # Map or validate category
        category = raw_category if raw_category in allowed_categories else "环境"
        
        for f in files:
            if Path(f).suffix.lower() not in valid_exts:
                continue
                
            f_path = root_path / f
            rel_path = f_path.relative_to(sfx_root).as_posix()
            try:
                duration = _probe_duration(f_path)
            except ValueError:
                continue
                
            role = _classify_sfx_role(f, raw_category)
            sfx_id = str(Path(rel_path).with_suffix(""))
            
            sfx_list.append(SfxEntry(
                sfx_id=sfx_id,
                name=Path(f).stem,
                category=category, # type: ignore
                role=role, # type: ignore
                relative_path=rel_path,
                duration_seconds=duration
            ))
            
    return sfx_list


def build_audio_catalog(root: Path | None = None) -> AudioCatalog:
    """Main entry point to scan both catalogs and build AudioCatalog."""
    if root is None:
        root = resolve_audio_root()
        
    music_root = root / "BGM"
    sfx_root = root / "SFX"
    
    if not music_root.exists():
        music_root.mkdir(parents=True, exist_ok=True)
    if not sfx_root.exists():
        sfx_root.mkdir(parents=True, exist_ok=True)
        
    tracks = scan_music_catalog(music_root)
    sfx = scan_sfx_catalog(sfx_root)
    
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()
    
    return AudioCatalog(
        schema_version="1.0.0",
        music_root=str(music_root),
        sfx_root=str(sfx_root),
        tracks=tracks,
        sfx=sfx,
        scan_timestamp=timestamp
    )


def load_catalog_cache(cache_path: Path) -> AudioCatalog | None:
    """Load cached catalog from JSON if it exists and is recent (< 24h)."""
    if not cache_path.exists() or not cache_path.is_file():
        return None
        
    # Check if < 24h old
    mtime = cache_path.stat().st_mtime
    if time.time() - mtime > 24 * 3600:
        return None
        
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AudioCatalog.model_validate(data)
    except Exception:
        return None


def save_catalog_cache(catalog: AudioCatalog, cache_path: Path) -> None:
    """Save catalog to JSON cache."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(catalog.model_dump_json(indent=2))

