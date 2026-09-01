"""Bounded local packets for a separately invoked visual agent."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw
from pydantic import Field, model_validator

from director.visual_schema import EvidenceRef, MaterialRef, VisualStrictModel


AGENT_VISUAL_FIELDS = (
    "technical_usability",
    "content_family",
    "setting",
    "lighting",
    "people_presence",
    "people_count_band",
    "subject_candidates",
    "activity_candidates",
)


class MaterialFrameSet(VisualStrictModel):
    material: MaterialRef
    frame_paths: list[str] = Field(max_length=5)


class MaterialFrameMap(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    items: list[MaterialFrameSet] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_material_paths(self) -> "MaterialFrameMap":
        paths = [item.material.relative_path for item in self.items]
        if len(paths) != len(set(paths)):
            raise ValueError("material frame map has duplicate relative paths")
        return self

class AgentMaterialPacket(VisualStrictModel):
    material_id: str
    relative_path: str
    status: Literal["ready", "review_required"]
    contact_sheet_path: str | None
    allowed_fields: list[str]
    source_evidence_refs: list[EvidenceRef]


class AgentBatch(VisualStrictModel):
    batch_id: str
    batch_index: int = Field(ge=0)
    items: list[AgentMaterialPacket] = Field(min_length=1, max_length=10)
    result_path: str


class AgentBatchManifest(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    max_batch_size: Literal[10] = 10
    items: list[AgentMaterialPacket]
    batches: list[AgentBatch]

    def item_by_relative_path(self, relative_path: str) -> AgentMaterialPacket:
        for item in self.items:
            if item.relative_path == relative_path:
                return item
        raise KeyError(relative_path)


def build_contact_sheet(frame_images: list[Path], output: Path, material_filename: str) -> Path:
    """Write a deterministic two-column RGB JPEG from three to five local frames."""
    if not 3 <= len(frame_images) <= 5:
        raise ValueError("contact sheets require three to five representative frames")
    opened = []
    for frame in frame_images:
        with Image.open(frame) as source:
            image = source.convert("RGB")
        image.thumbnail((320, 220))
        opened.append((frame, image))
    cell_width, cell_height, header, label = 340, 260, 34, 22
    rows = (len(frame_images) + 1) // 2
    canvas = Image.new("RGB", (cell_width * 2, header + rows * cell_height), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), material_filename, fill="black")
    for index, (frame, image) in enumerate(opened):
        x, y = (index % 2) * cell_width, header + (index // 2) * cell_height
        x += (cell_width - image.width) // 2
        y += (cell_height - label - image.height) // 2
        canvas.paste(image, (x, y))
        draw.text(((index % 2) * cell_width + 8, header + (index // 2 + 1) * cell_height - label), f"t={frame.stem}", fill="black")
        image.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="JPEG", quality=90)
    canvas.close()
    return output


def build_agent_batch_manifest(frame_map: MaterialFrameMap, output_dir: Path) -> AgentBatchManifest:
    """Create local contact sheets and reserve no-more-than-ten packet results."""
    root = output_dir.resolve()
    sheet_dir = root / "contact_sheets"
    (root / "results").mkdir(parents=True, exist_ok=True)
    packets: list[AgentMaterialPacket] = []
    for item in sorted(frame_map.items, key=lambda value: value.material.relative_path):
        frame_paths = [Path(raw).resolve() for raw in item.frame_paths]
        if len(frame_paths) < 3:
            contact_sheet_path = None
            status: Literal["ready", "review_required"] = "review_required"
        else:
            if len(frame_paths) > 5:
                raise ValueError("material frame paths exceed five")
            filename = f"{item.material.source_sha256[:16]}.jpg"
            contact_sheet_path = str(build_contact_sheet(frame_paths, sheet_dir / filename, Path(item.material.relative_path).name).resolve())
            if not Path(contact_sheet_path).is_relative_to(root):
                raise ValueError("contact sheet path escapes output directory")
            status = "ready"
        packets.append(AgentMaterialPacket(
            material_id=item.material.material_id, relative_path=item.material.relative_path,
            status=status, contact_sheet_path=contact_sheet_path,
            allowed_fields=list(AGENT_VISUAL_FIELDS), source_evidence_refs=[],
        ))
    batches = [
        AgentBatch(
            batch_id=f"batch-{batch_index:03d}", batch_index=batch_index,
            items=packets[start:start + 10],
            result_path=str((root / "results" / f"batch-{batch_index:03d}.json").resolve()),
        )
        for batch_index, start in enumerate(range(0, len(packets), 10))
    ]
    return AgentBatchManifest(items=packets, batches=batches)
