"""Deterministic metadata/CV-stratified benchmark selection."""

from __future__ import annotations

import random
import subprocess
import json
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from scanner.schema import ManifestEntry, TestManifest


def render_manual_review_sheet(sampling_result: Path, output: Path) -> Path:
    """Render sparse frames for human labeling without inferred fields."""

    payload = json.loads(sampling_result.read_text(encoding="utf-8"))
    cards: list[str] = []
    for item in payload["items"]:
        frames: list[str] = []
        for frame in item["representative_frames"]:
            reason = ", ".join(frame["reasons"])
            frames.append(
                '<figure><img src="{}" alt=""><figcaption>{:.3f}s · {}</figcaption></figure>'.format(
                    escape(frame["thumbnail_relpath"]),
                    float(frame["timestamp"]),
                    escape(reason),
                )
            )
        cards.append(
            '<article><h2>{}</h2><div class="frames">{}</div></article>'.format(
                escape(item["file"]),
                "".join(frames),
            )
        )
    html = """<!doctype html><meta charset="utf-8"><title>Manual Ground Truth Review</title>
<style>body{font-family:system-ui;background:#111;color:#eee;margin:24px}article{background:#222;padding:14px;margin:0 0 18px;border-radius:10px}h2{font-size:16px;word-break:break-all}.frames{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}figure{margin:0}img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000}figcaption{font-size:12px;color:#bbb;margin-top:4px}</style>
<h1>Manual Ground Truth Review — no model predictions</h1>""" + "".join(cards)
    output.write_text(html, encoding="utf-8")
    return output


def _duration_bin(duration: float) -> str:
    if duration < 3:
        return "under3"
    if duration < 10:
        return "3to10"
    if duration <= 30:
        return "10to30"
    return "over30"


def _time_tokens(entry: ManifestEntry) -> set[str]:
    raw = entry.technical.creation_time
    if not raw:
        return {"day:unknown", "time:unknown"}
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return {"day:unknown", "time:unknown"}
    if created.hour < 6:
        band = "night"
    elif created.hour < 12:
        band = "morning"
    elif created.hour < 18:
        band = "afternoon"
    else:
        band = "evening"
    return {f"day:{created.date().isoformat()}", f"time:{band}"}


def _base_tokens(entry: ManifestEntry) -> set[str]:
    return {
        f"orientation:{entry.technical.orientation}",
        f"resolution:{entry.technical.width}x{entry.technical.height}",
        f"duration:{_duration_bin(entry.technical.duration)}",
        *_time_tokens(entry),
    }


def _cv_quartile_tokens(cv_rows: Sequence[dict[str, Any]]) -> dict[str, set[str]]:
    fields = ("brightness_score", "laplacian_variance_raw", "motion_intensity_raw")
    result: dict[str, set[str]] = {str(row["file"]): set() for row in cv_rows if "file" in row}
    for field in fields:
        values = [
            float(row[field])
            for row in cv_rows
            if row.get("file") in result and row.get(field) is not None
        ]
        if not values:
            continue
        edges = np.quantile(values, [0.25, 0.5, 0.75])
        for row in cv_rows:
            if row.get("file") not in result or row.get(field) is None:
                continue
            quartile = int(np.searchsorted(edges, float(row[field]), side="right")) + 1
            result[str(row["file"])].add(f"{field}:q{quartile}")
    return result


def propose_stratified_set(
    manifest: TestManifest,
    cv_rows: Sequence[dict[str, Any]],
    count: int,
    seed: int,
) -> TestManifest:
    if count < 1:
        raise ValueError("count must be positive")
    if count > len(manifest.entries):
        raise ValueError("count exceeds manifest size")

    cv_tokens = _cv_quartile_tokens(cv_rows)
    tokens_by_file = {
        entry.file: _base_tokens(entry) | cv_tokens.get(entry.file, set())
        for entry in manifest.entries
    }
    frequencies = Counter(token for tokens in tokens_by_file.values() for token in tokens)
    rng = random.Random(seed)
    tie_order = list(manifest.entries)
    rng.shuffle(tie_order)
    rank = {entry.file: index for index, entry in enumerate(tie_order)}

    selected: list[ManifestEntry] = []
    remaining = list(manifest.entries)
    covered: set[str] = set()
    while len(selected) < count:
        def score(entry: ManifestEntry) -> tuple[float, int]:
            uncovered = tokens_by_file[entry.file] - covered
            rarity = sum(1.0 / frequencies[token] for token in uncovered)
            return rarity, -rank[entry.file]

        chosen = max(remaining, key=score)
        selected.append(chosen)
        remaining.remove(chosen)
        covered.update(tokens_by_file[chosen.file])

    selected.sort(key=lambda entry: entry.source.relative_path.casefold())
    return TestManifest(
        input_root=manifest.input_root,
        entries=selected,
        total_duration_seconds=sum(entry.technical.duration for entry in selected),
        total_size_bytes=sum(entry.source.size_bytes for entry in selected),
    )


def render_contact_sheet(
    manifest: TestManifest,
    output: Path,
    hardware_acceleration: str = "none",
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    assets = output.parent / f"{output.stem}_files"
    assets.mkdir(parents=True, exist_ok=True)
    cards: list[str] = []
    for index, entry in enumerate(manifest.entries):
        source = Path(manifest.input_root) / entry.source.relative_path
        thumbnail = assets / f"{index:03d}.jpg"
        command = [ffmpeg_bin, "-v", "error"]
        if hardware_acceleration != "none":
            command.extend(["-hwaccel", hardware_acceleration])
        command.extend(
            [
                "-ss",
                f"{entry.technical.duration * 0.5:.6f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                "scale='if(gt(iw,ih),480,-2)':'if(gt(iw,ih),-2,480)'",
                "-q:v",
                "3",
                "-y",
                str(thumbnail),
            ]
        )
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"contact sheet thumbnail failed for {entry.file}: {completed.stderr.strip()}")
        relative_thumbnail = thumbnail.relative_to(output.parent).as_posix()
        cards.append(
            "<article><img src=\"{}\" alt=\"\"><h2>{}</h2>"
            "<p>{:.3f}s · {} · {}×{}</p></article>".format(
                escape(relative_thumbnail),
                escape(entry.file),
                entry.technical.duration,
                escape(entry.technical.orientation),
                entry.technical.width,
                entry.technical.height,
            )
        )
    html = """<!doctype html><meta charset="utf-8"><title>Ground Truth Selection</title>
<style>body{font-family:system-ui;background:#111;color:#eee;margin:24px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}article{background:#222;padding:12px;border-radius:10px}img{width:100%;aspect-ratio:16/9;object-fit:cover;background:#000}h2{font-size:14px;word-break:break-all}p{color:#bbb}</style>
<h1>Ground Truth Selection — no model predictions</h1><main>""" + "".join(cards) + "</main>"
    output.write_text(html, encoding="utf-8")
    return output
