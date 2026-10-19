"""Build a small FCPXML interchange project for Jianying import testing."""

from __future__ import annotations

import json
import math
import os
import subprocess
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "TD-P0-12s-FCPXML-20260909-v2"
ASSETS = PACKAGE / "asset"
OUTPUT = PACKAGE / "TD-P0-12s-FCPXML-20260909-v2.fcpxml"

MEDIA = [
    {
        "id": "r2", "kind": "video", "track": "main_video",
        "path": Path("/Users/meimaodawang/Desktop/万岁山素材/2026_02_06_18_40_27_IMG_0235.MOV"),
        "timeline_start": 0, "source_start": 1, "duration": 4, "volume_db": -96,
    },
    {
        "id": "r3", "kind": "video", "track": "main_video",
        "path": Path("/Users/meimaodawang/Desktop/万岁山素材/2026_02_07_13_24_51_IMG_0364.MOV"),
        "timeline_start": 4, "source_start": 1, "duration": 4, "volume_db": -96,
    },
    {
        "id": "r4", "kind": "video", "track": "main_video",
        "path": Path("/Users/meimaodawang/Desktop/万岁山素材/2026_02_07_21_24_44_IMG_0504.MOV"),
        "timeline_start": 8, "source_start": 2, "duration": 4, "volume_db": -96,
    },
    {
        "id": "r5", "kind": "audio", "track": "music",
        "path": Path("/Users/meimaodawang/Documents/旅行导演/local-media-scanner/prototype/runs/travel-project-70811bf416/generation/assets/music-bd40015805a4621c.wav"),
        "timeline_start": 0, "source_start": 0, "duration": 12, "volume_db": -9.119,
    },
    {
        "id": "r6", "kind": "audio", "track": "whoosh",
        "path": Path("/Users/meimaodawang/Documents/音效及音乐/音效/风声/CZG_Whoosh_007.wav"),
        "timeline_start": 0, "source_start": 0, "duration": 2.16, "volume_db": -1.938,
    },
    {
        "id": "r7", "kind": "audio", "track": "subdrop",
        "path": Path("/Users/meimaodawang/Documents/音效及音乐/音效/上升音效/CZG_SubDrop_001.wav"),
        "timeline_start": 7.6, "source_start": 0, "duration": 2.94, "volume_db": -2.499,
    },
]


def seconds(value: float) -> str:
    fraction = Fraction(round(value * 1_000_000), 1_000_000)
    return f"{fraction.numerator}/{fraction.denominator}s" if fraction.denominator != 1 else f"{fraction.numerator}s"


def probe(path: Path) -> dict:
    payload = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json", str(path),
    ])
    return json.loads(payload)


def hardlink_asset(source: Path, asset_id: str) -> Path:
    target = ASSETS / f"{asset_id}-{source.name}"
    os.link(source, target)
    return target


def main() -> None:
    if PACKAGE.exists():
        raise FileExistsError(f"Refusing to overwrite {PACKAGE}")
    ASSETS.mkdir(parents=True)

    fcpxml = ET.Element("fcpxml", version="1.9")
    resources = ET.SubElement(fcpxml, "resources")
    ET.SubElement(resources, "format", id="r1", name="FFVideoFormat1080p30",
                  frameDuration="1/30s", width="1920", height="1080", colorSpace="1-1-1 (Rec. 709)")

    observed = []
    for item in MEDIA:
        path = item["path"]
        assert path.is_file(), path
        data = probe(path)
        duration = float(data["format"]["duration"])
        assert item["source_start"] + item["duration"] <= duration + 0.001
        linked = hardlink_asset(path, item["id"])
        streams = data["streams"]
        video = next((stream for stream in streams if stream["codec_type"] == "video"), None)
        audio = next((stream for stream in streams if stream["codec_type"] == "audio"), None)
        attrs = {
            "id": item["id"], "name": path.name, "src": linked.as_uri(),
            "start": "0s", "duration": seconds(duration),
        }
        if video:
            format_id = f"fmt-{item['id']}"
            rate = Fraction(video["r_frame_rate"])
            ET.SubElement(resources, "format", id=format_id,
                          frameDuration=f"{rate.denominator}/{rate.numerator}s",
                          width=str(video["width"]), height=str(video["height"]),
                          colorSpace="1-1-1 (Rec. 709)")
            attrs.update(hasVideo="1", format=format_id)
        if audio:
            attrs.update(hasAudio="1", audioSources="1", audioChannels=str(audio.get("channels", 2)),
                         audioRate=str(audio.get("sample_rate", 48000)))
        ET.SubElement(resources, "asset", **attrs)
        observed.append({**{k: v for k, v in item.items() if k != "path"},
                         "path": str(path), "linked_path": str(linked), "source_duration": duration})

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name="Travel Director P0")
    project = ET.SubElement(event, "project", name="TD-P0-12s-FCPXML-20260909-v2")
    sequence = ET.SubElement(project, "sequence", format="r1", duration="12s", tcStart="0s",
                             tcFormat="NDF", audioLayout="stereo", audioRate="48k")
    spine = ET.SubElement(sequence, "spine")
    video_nodes = []
    for item in MEDIA[:3]:
        node = ET.SubElement(spine, "asset-clip", ref=item["id"], name=item["path"].name,
                             offset=seconds(item["timeline_start"]), start=seconds(item["source_start"]),
                             duration=seconds(item["duration"]), audioRole="dialogue")
        ET.SubElement(node, "adjust-volume", amount=f"{item['volume_db']}dB")
        video_nodes.append(node)

    for lane, item in enumerate(MEDIA[3:], start=1):
        role = "music" if item["track"] == "music" else "effects"
        node = ET.SubElement(video_nodes[0], "asset-clip", ref=item["id"], name=item["path"].name,
                             lane=str(-lane), offset=seconds(item["timeline_start"]),
                             start=seconds(item["source_start"]), duration=seconds(item["duration"]),
                             audioRole=role)
        ET.SubElement(node, "adjust-volume", amount=f"{item['volume_db']}dB")

    ET.indent(fcpxml, space="  ")
    xml_bytes = ET.tostring(fcpxml, encoding="utf-8", xml_declaration=True)
    OUTPUT.write_bytes(xml_bytes)

    # Independent checks over the serialized interchange document.
    parsed = ET.parse(OUTPUT).getroot()
    assert parsed.tag == "fcpxml" and parsed.attrib["version"] == "1.9"
    assert len(parsed.findall(".//asset")) == 6
    clips = parsed.findall(".//asset-clip")
    assert len(clips) == 6
    assert len(parsed.findall(".//spine/asset-clip")) == 3
    assert len(parsed.findall(".//asset-clip/asset-clip")) == 3
    assert parsed.find(".//sequence").attrib["duration"] == "12s"
    assert all(Path(unquote(urlparse(asset.attrib["src"]).path)).exists()
               for asset in parsed.findall(".//asset"))

    receipt = {
        "status": "fcpxml_generated",
        "client_import": "not_tested",
        "format": "FCPXML 1.9",
        "duration_seconds": 12,
        "video_segments": 3,
        "audio_segments": 3,
        "media_model_calls": 0,
        "scan_count": 0,
        "package": str(PACKAGE),
        "fcpxml": str(OUTPUT),
        "assets_are_hardlinks": True,
        "media": observed,
    }
    (ROOT / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in receipt.items() if k != "media"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
