"""Materialize a concise edit decision as a validated FCPXML package."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

from pydantic import Field, model_validator

from director.schema import StrictModel


class FcpxmlCanvasDecision(StrictModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0, le=120)
    duration_seconds: float = Field(gt=0)


class FcpxmlClipDecision(StrictModel):
    kind: Literal["video", "music", "sfx"]
    source_path: Path
    track: str = Field(min_length=1, max_length=80)
    timeline_in: float = Field(ge=0)
    source_in: float = Field(ge=0)
    duration: float = Field(gt=0)
    gain: float = Field(ge=0, le=4)


class FcpxmlEditDecision(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    project_name: str = Field(min_length=1, max_length=120)
    canvas: FcpxmlCanvasDecision
    clips: list[FcpxmlClipDecision] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_timeline(self) -> "FcpxmlEditDecision":
        if not any(clip.kind == "video" for clip in self.clips):
            raise ValueError("at least one video clip is required")
        for clip in self.clips:
            if clip.timeline_in + clip.duration > self.canvas.duration_seconds + 0.000_001:
                raise ValueError(f"clip exceeds project duration on track {clip.track}")
        for track in {clip.track for clip in self.clips}:
            clips = sorted(
                (clip for clip in self.clips if clip.track == track),
                key=lambda clip: clip.timeline_in,
            )
            for previous, current in zip(clips, clips[1:]):
                if current.timeline_in < previous.timeline_in + previous.duration - 0.000_001:
                    raise ValueError(f"overlap on track {track}")
        video_tracks = {clip.track for clip in self.clips if clip.kind == "video"}
        if len(video_tracks) != 1:
            raise ValueError("exactly one video track is supported")
        return self


class FcpxmlExportResult(StrictModel):
    status: Literal["fcpxml_generated"] = "fcpxml_generated"
    fcpxml_path: Path
    receipt_path: Path
    decision_path: Path
    video_segments: int
    audio_segments: int
    external_call_count: Literal[0] = 0


class FcpxmlAcceptanceResult(StrictModel):
    status: Literal["fcpxml_client_accepted"] = "fcpxml_client_accepted"
    receipt_path: Path
    draft_name: str
    external_call_count: Literal[0] = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timecode_frames(value: str, fps: int) -> int:
    parts = value.split(":")
    if len(parts) != 4 or any(not part.isdigit() for part in parts):
        raise ValueError(f"invalid timecode: {value}")
    hours, minutes, seconds, frames = (int(part) for part in parts)
    if minutes >= 60 or seconds >= 60 or frames >= fps:
        raise ValueError(f"invalid timecode: {value}")
    return (((hours * 60) + minutes) * 60 + seconds) * fps + frames


def _atomic_write_json(path: Path, payload: dict) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _seconds(value: float) -> str:
    value = Fraction(round(value * 1_000_000), 1_000_000)
    if value.denominator == 1:
        return f"{value.numerator}s"
    return f"{value.numerator}/{value.denominator}s"


def _volume_db(gain: float) -> str:
    if gain == 0:
        return "-96dB"
    value = round(20 * math.log10(gain), 3)
    if value == 0:
        return "0dB"
    return f"{value:g}dB"


def _probe(path: Path) -> dict:
    try:
        payload = subprocess.check_output(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_type,width,height,r_frame_rate,sample_rate,channels",
                "-of", "json", str(path),
            ],
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"unable to probe media: {path}") from exc
    return json.loads(payload)


def _inspect_sources(decision: FcpxmlEditDecision) -> list[dict]:
    inspected = []
    for index, clip in enumerate(decision.clips, start=1):
        source = clip.source_path.expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"media does not exist: {source}")
        probe = _probe(source)
        source_duration = float(probe["format"]["duration"])
        if clip.source_in + clip.duration > source_duration + 0.001:
            raise ValueError(f"source range exceeds media: {source}")
        stream_types = {stream["codec_type"] for stream in probe["streams"]}
        required = "video" if clip.kind == "video" else "audio"
        if required not in stream_types:
            raise ValueError(f"{clip.kind} clip requires a {required} stream: {source}")
        inspected.append(
            {
                "id": f"asset-{index}",
                "clip": clip,
                "source": source,
                "source_duration": source_duration,
                "streams": probe["streams"],
            }
        )
    return inspected


def _build_xml(decision: FcpxmlEditDecision, inspected: list[dict], linked: dict[str, Path]) -> bytes:
    fcpxml = ET.Element("fcpxml", version="1.9")
    resources = ET.SubElement(fcpxml, "resources")
    ET.SubElement(
        resources,
        "format",
        id="project-format",
        name=f"FFVideoFormat{decision.canvas.height}p{decision.canvas.fps}",
        frameDuration=f"1/{decision.canvas.fps}s",
        width=str(decision.canvas.width),
        height=str(decision.canvas.height),
        colorSpace="1-1-1 (Rec. 709)",
    )
    for item in inspected:
        clip = item["clip"]
        streams = item["streams"]
        video = next((stream for stream in streams if stream["codec_type"] == "video"), None)
        audio = next((stream for stream in streams if stream["codec_type"] == "audio"), None)
        attrs = {
            "id": item["id"],
            "name": item["source"].name,
            "src": linked[item["id"]].as_uri(),
            "start": "0s",
            "duration": _seconds(item["source_duration"]),
        }
        if video is not None:
            rate = Fraction(video["r_frame_rate"])
            format_id = f"format-{item['id']}"
            ET.SubElement(
                resources,
                "format",
                id=format_id,
                frameDuration=f"{rate.denominator}/{rate.numerator}s",
                width=str(video["width"]),
                height=str(video["height"]),
                colorSpace="1-1-1 (Rec. 709)",
            )
            attrs.update(hasVideo="1", format=format_id)
        if audio is not None:
            attrs.update(
                hasAudio="1",
                audioSources="1",
                audioChannels=str(audio.get("channels", 2)),
                audioRate=str(audio.get("sample_rate", 48_000)),
            )
        ET.SubElement(resources, "asset", **attrs)

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name="Travel Director")
    project = ET.SubElement(event, "project", name=decision.project_name)
    sequence = ET.SubElement(
        project,
        "sequence",
        format="project-format",
        duration=_seconds(decision.canvas.duration_seconds),
        tcStart="0s",
        tcFormat="NDF",
        audioLayout="stereo",
        audioRate="48k",
    )
    spine = ET.SubElement(sequence, "spine")
    primary: list[ET.Element] = []
    cursor = 0.0
    video_items = sorted(
        (item for item in inspected if item["clip"].kind == "video"),
        key=lambda item: item["clip"].timeline_in,
    )
    for item in video_items:
        clip = item["clip"]
        if clip.timeline_in > cursor + 0.000_001:
            primary.append(
                ET.SubElement(
                    spine,
                    "gap",
                    name="Gap",
                    offset=_seconds(cursor),
                    start="0s",
                    duration=_seconds(clip.timeline_in - cursor),
                )
            )
        node = ET.SubElement(
            spine,
            "asset-clip",
            ref=item["id"],
            name=item["source"].name,
            offset=_seconds(clip.timeline_in),
            start=_seconds(clip.source_in),
            duration=_seconds(clip.duration),
            audioRole="dialogue",
        )
        ET.SubElement(node, "adjust-volume", amount=_volume_db(clip.gain))
        primary.append(node)
        cursor = clip.timeline_in + clip.duration
    if cursor < decision.canvas.duration_seconds - 0.000_001:
        primary.append(
            ET.SubElement(
                spine,
                "gap",
                name="Gap",
                offset=_seconds(cursor),
                start="0s",
                duration=_seconds(decision.canvas.duration_seconds - cursor),
            )
        )

    anchor = primary[0]
    audio_tracks = sorted({item["clip"].track for item in inspected if item["clip"].kind != "video"})
    lanes = {track: -(index + 1) for index, track in enumerate(audio_tracks)}
    for item in sorted(
        (item for item in inspected if item["clip"].kind != "video"),
        key=lambda item: (lanes[item["clip"].track], item["clip"].timeline_in),
    ):
        clip = item["clip"]
        node = ET.SubElement(
            anchor,
            "asset-clip",
            ref=item["id"],
            name=item["source"].name,
            lane=str(lanes[clip.track]),
            offset=_seconds(clip.timeline_in),
            start=_seconds(clip.source_in),
            duration=_seconds(clip.duration),
            audioRole="music" if clip.kind == "music" else "effects",
        )
        ET.SubElement(node, "adjust-volume", amount=_volume_db(clip.gain))
    ET.indent(fcpxml, space="  ")
    return ET.tostring(fcpxml, encoding="utf-8", xml_declaration=True)


def _validate_serialized(
    fcpxml_path: Path,
    decision: FcpxmlEditDecision,
    inspected: list[dict],
) -> dict[str, bool]:
    root = ET.parse(fcpxml_path).getroot()
    assets = {asset.attrib["id"]: asset for asset in root.findall(".//asset")}
    clips = root.findall(".//asset-clip")
    if len(assets) != len(inspected) or len(clips) != len(inspected):
        raise ValueError("serialized material or segment count differs from decision")
    if {clip.attrib["ref"] for clip in clips} != set(assets):
        raise ValueError("serialized segment references are incomplete")
    for asset in assets.values():
        target = Path(unquote(urlparse(asset.attrib["src"]).path))
        if not target.is_file():
            raise ValueError(f"serialized material reference is missing: {target}")
    if root.find(".//sequence").attrib["duration"] != _seconds(decision.canvas.duration_seconds):
        raise ValueError("serialized duration differs from decision")
    return {
        "xml_well_formed": True,
        "source_ranges_within_media": True,
        "timeline_ranges_within_project": True,
        "same_track_non_overlapping": True,
        "material_references_exist": True,
    }


def export_fcpxml_decision(decision_path: Path, output_dir: Path) -> FcpxmlExportResult:
    """Validate a concise JSON edit decision and write an importable FCPXML package."""

    decision_path = decision_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not decision_path.is_file():
        raise ValueError(f"decision does not exist: {decision_path}")
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite output: {output_dir}")
    decision = FcpxmlEditDecision.model_validate_json(decision_path.read_text(encoding="utf-8"))
    inspected = _inspect_sources(decision)

    assets_dir = output_dir / "asset"
    assets_dir.mkdir(parents=True)
    linked: dict[str, Path] = {}
    for item in inspected:
        target = assets_dir / f"{item['id']}-{item['source'].name}"
        try:
            os.link(item["source"], target)
        except OSError as exc:
            raise ValueError(f"cannot hard-link material into package: {item['source']}") from exc
        linked[item["id"]] = target

    fcpxml_path = output_dir / "project.fcpxml"
    fcpxml_path.write_bytes(_build_xml(decision, inspected, linked))
    validation = _validate_serialized(fcpxml_path, decision, inspected)
    receipt_path = output_dir / "receipt.json"
    receipt = {
        "schema_version": "0.1.0",
        "status": "fcpxml_generated",
        "client_import": "not_tested",
        "client_playback": "not_tested",
        "client_edit_save": "not_tested",
        "decision_path": str(decision_path),
        "decision_sha256": _sha256(decision_path),
        "fcpxml_path": str(fcpxml_path),
        "fcpxml_sha256": _sha256(fcpxml_path),
        "external_call_count": 0,
        "video_segments": sum(clip.kind == "video" for clip in decision.clips),
        "audio_segments": sum(clip.kind != "video" for clip in decision.clips),
        "track_lanes": {
            track: -(index + 1)
            for index, track in enumerate(sorted({clip.track for clip in decision.clips if clip.kind != "video"}))
        },
        "validation": validation,
        "materials": [
            {
                "asset_id": item["id"],
                "source_path": str(item["source"]),
                "source_sha256": _sha256(item["source"]),
                "source_duration_seconds": item["source_duration"],
                "packaged_path": str(linked[item["id"]]),
            }
            for item in inspected
        ],
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return FcpxmlExportResult(
        fcpxml_path=fcpxml_path,
        receipt_path=receipt_path,
        decision_path=decision_path,
        video_segments=receipt["video_segments"],
        audio_segments=receipt["audio_segments"],
    )


def record_fcpxml_acceptance(
    receipt_path: Path,
    *,
    application: str,
    application_version: str,
    draft_name: str,
    observed_video_segments: int,
    observed_audio_segments: int,
    playhead_before: str,
    playhead_after: str,
    edit_asset: str,
    edit_field: str,
    edit_before: float,
    edit_after: float,
    reopen_value: float,
    accepted_at: str,
) -> FcpxmlAcceptanceResult:
    """Record client acceptance only after import, playback, edit, save and reopen evidence."""

    receipt_path = receipt_path.expanduser().resolve()
    if not receipt_path.is_file():
        raise ValueError(f"receipt does not exist: {receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "fcpxml_generated":
        raise ValueError("acceptance requires an unaccepted fcpxml_generated receipt")
    fcpxml_path = Path(receipt["fcpxml_path"])
    if not fcpxml_path.is_file() or _sha256(fcpxml_path) != receipt.get("fcpxml_sha256"):
        raise ValueError("FCPXML is missing or differs from the generated receipt")
    if observed_video_segments != receipt.get("video_segments"):
        raise ValueError("observed video segment count differs from generated receipt")
    if observed_audio_segments != receipt.get("audio_segments"):
        raise ValueError("observed audio segment count differs from generated receipt")
    fps = FcpxmlEditDecision.model_validate_json(
        Path(receipt["decision_path"]).read_text(encoding="utf-8")
    ).canvas.fps
    if _timecode_frames(playhead_after, fps) <= _timecode_frames(playhead_before, fps):
        raise ValueError("playhead must advance during client playback")
    if math.isclose(edit_before, edit_after, abs_tol=0.000_001):
        raise ValueError("client acceptance requires one observable edit")
    if not math.isclose(edit_after, reopen_value, abs_tol=0.000_001):
        raise ValueError("reopened value differs from the saved edit")
    if not all((application.strip(), application_version.strip(), draft_name.strip(), edit_asset.strip(), edit_field.strip(), accepted_at.strip())):
        raise ValueError("client acceptance text fields must be non-empty")

    receipt.update(
        status="fcpxml_client_accepted",
        client_import="passed",
        client_playback="passed",
        client_edit_save="passed",
        client_acceptance={
            "application": application,
            "application_version": application_version,
            "draft_name": draft_name,
            "verified_video_segments": observed_video_segments,
            "verified_audio_segments": observed_audio_segments,
            "playback_observation": {
                "playhead_before": playhead_before,
                "playhead_after": playhead_after,
            },
            "edit_observation": {
                "asset": edit_asset,
                "field": edit_field,
                "before": edit_before,
                "after": edit_after,
            },
            "save_reopen_observation": {
                "reopened_value": reopen_value,
                "matches_saved_edit": True,
            },
            "accepted_at": accepted_at,
        },
    )
    _atomic_write_json(receipt_path, receipt)
    return FcpxmlAcceptanceResult(receipt_path=receipt_path, draft_name=draft_name)
