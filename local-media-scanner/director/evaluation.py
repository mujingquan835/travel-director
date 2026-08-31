"""Frozen evaluation packs and manual-label contracts for the V0.2 workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import ConfigDict, Field, model_validator

from director.visual_schema import (
    ClipObservation,
    ClipObservationBatch,
    MaterialRef,
    RawCreativeBrief,
    VisualStrictModel,
    derive_material_id,
)
from scanner.schema import TestManifest
from scanner.selection import propose_stratified_set


ContentFamily = Literal[
    "urban",
    "nature",
    "culture_architecture",
    "food",
    "transport",
    "lodging",
    "attraction_activity",
    "performance_event",
    "people",
    "detail",
    "other",
    "unknown",
]


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def membership_hash(manifest: TestManifest) -> str:
    paths = sorted(row.source.relative_path for row in manifest.entries)
    return hashlib.sha256(_canonical_bytes(paths)).hexdigest()


def _subset_manifest(inventory: TestManifest, paths: set[str]) -> TestManifest:
    entries = [
        row for row in inventory.entries if row.source.relative_path in paths
    ]
    return TestManifest(
        input_root=inventory.input_root,
        entries=entries,
        total_duration_seconds=sum(row.technical.duration for row in entries),
        total_size_bytes=sum(row.source.size_bytes for row in entries),
    )


class DirectorVisualSplit(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dev_seed: int
    blind_seed: int
    dev_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    blind_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reserve_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dev: TestManifest
    blind: TestManifest
    reserve: TestManifest

    @model_validator(mode="after")
    def partitions_are_exact_and_disjoint(self) -> "DirectorVisualSplit":
        groups = [
            {row.source.relative_path for row in manifest.entries}
            for manifest in (self.dev, self.blind, self.reserve)
        ]
        if [len(group) for group in groups] != [12, 12, 6]:
            raise ValueError("evaluation split must contain exactly 12/12/6 files")
        if not (
            groups[0].isdisjoint(groups[1])
            and groups[0].isdisjoint(groups[2])
            and groups[1].isdisjoint(groups[2])
        ):
            raise ValueError("evaluation split memberships must be disjoint")
        expected_hashes = (
            self.dev_membership_sha256,
            self.blind_membership_sha256,
            self.reserve_membership_sha256,
        )
        actual_hashes = tuple(
            membership_hash(manifest)
            for manifest in (self.dev, self.blind, self.reserve)
        )
        if expected_hashes != actual_hashes:
            raise ValueError("evaluation membership hash mismatch")
        return self


def build_evaluation_split(
    inventory: TestManifest,
    cv_rows: list[dict[str, Any]],
    *,
    source_manifest_sha256: str,
    dev_seed: int = 20260831,
    blind_seed: int = 20260901,
) -> DirectorVisualSplit:
    """Create deterministic, non-overlapping development/blind/reserve sets."""

    if len(inventory.entries) != 30:
        raise ValueError("director visual inventory must contain exactly 30 files")
    dev = propose_stratified_set(inventory, cv_rows, count=12, seed=dev_seed)
    dev_paths = {row.source.relative_path for row in dev.entries}
    eligible_paths = {
        row.source.relative_path
        for row in inventory.entries
        if row.source.relative_path not in dev_paths
    }
    eligible = _subset_manifest(inventory, eligible_paths)
    eligible_cv = [row for row in cv_rows if row.get("file") in eligible_paths]
    blind = propose_stratified_set(
        eligible, eligible_cv, count=12, seed=blind_seed
    )
    used = dev_paths | {row.source.relative_path for row in blind.entries}
    reserve = _subset_manifest(
        inventory,
        {
            row.source.relative_path
            for row in inventory.entries
            if row.source.relative_path not in used
        },
    )
    return DirectorVisualSplit(
        source_manifest_sha256=source_manifest_sha256,
        dev_seed=dev_seed,
        blind_seed=blind_seed,
        dev_membership_sha256=membership_hash(dev),
        blind_membership_sha256=membership_hash(blind),
        reserve_membership_sha256=membership_hash(reserve),
        dev=dev,
        blind=blind,
        reserve=reserve,
    )


class GroundTruthRecord(VisualStrictModel):
    material_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file: str = Field(min_length=1)
    split: Literal["dev", "blind"]
    frame_paths: list[str] = Field(default_factory=list)
    technical_usability: Literal[
        "unreviewed", "usable", "unusable", "review_required"
    ] = "unreviewed"
    content_families: list[ContentFamily] = Field(default_factory=lambda: ["unknown"])
    setting: Literal["indoor", "outdoor", "mixed", "unknown"] = "unknown"
    lighting: Literal["daylight", "night", "artificial", "mixed", "unknown"] = (
        "unknown"
    )
    people_presence: Literal["present", "absent", "unknown"] = "unknown"
    people_count_band: Literal["none", "single", "few", "crowd", "unknown"] = (
        "unknown"
    )
    subject_candidates: list[str] = Field(default_factory=list)
    activity_candidates: list[str] = Field(default_factory=list)
    reviewer_note: str = ""
    completed: bool = False

    @model_validator(mode="after")
    def identity_and_people_fields_are_consistent(self) -> "GroundTruthRecord":
        if self.material_id != derive_material_id(self.source_sha256):
            raise ValueError("ground truth material_id does not match source_sha256")
        if self.people_presence == "absent" and self.people_count_band not in {
            "none",
            "unknown",
        }:
            raise ValueError("absent people cannot have a positive count band")
        if self.completed and self.technical_usability == "unreviewed":
            raise ValueError("completed ground truth must review technical usability")
        return self


class DirectorVisualGroundTruth(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dev_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    blind_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    records: list[GroundTruthRecord]


def build_ground_truth_template(
    split: DirectorVisualSplit,
    source_hashes: dict[str, str],
    frame_paths: dict[str, list[str]] | None = None,
) -> DirectorVisualGroundTruth:
    frames = frame_paths or {}
    records: list[GroundTruthRecord] = []
    for split_name, manifest in (("dev", split.dev), ("blind", split.blind)):
        for entry in manifest.entries:
            relative_path = entry.source.relative_path
            try:
                source_sha256 = source_hashes[relative_path]
            except KeyError as exc:
                raise ValueError(f"missing source SHA-256 for {relative_path}") from exc
            records.append(
                GroundTruthRecord(
                    material_id=derive_material_id(source_sha256),
                    source_sha256=source_sha256,
                    file=relative_path,
                    split=split_name,
                    frame_paths=frames.get(relative_path, []),
                )
            )
    return DirectorVisualGroundTruth(
        source_manifest_sha256=split.source_manifest_sha256,
        dev_membership_sha256=split.dev_membership_sha256,
        blind_membership_sha256=split.blind_membership_sha256,
        records=records,
    )


def validate_ground_truth(
    ground_truth: DirectorVisualGroundTruth,
    split: DirectorVisualSplit,
    *,
    require_completed: bool,
) -> None:
    expected = {
        (split_name, entry.source.relative_path)
        for split_name, manifest in (("dev", split.dev), ("blind", split.blind))
        for entry in manifest.entries
    }
    observed = [(row.split, row.file) for row in ground_truth.records]
    if len(observed) != len(set(observed)):
        raise ValueError("duplicate material in ground truth")
    if set(observed) != expected:
        raise ValueError("ground truth membership differs from frozen split")
    if ground_truth.source_manifest_sha256 != split.source_manifest_sha256:
        raise ValueError("ground truth source manifest hash mismatch")
    if ground_truth.dev_membership_sha256 != split.dev_membership_sha256:
        raise ValueError("ground truth development membership hash mismatch")
    if ground_truth.blind_membership_sha256 != split.blind_membership_sha256:
        raise ValueError("ground truth blind membership hash mismatch")
    if require_completed:
        incomplete = [row.file for row in ground_truth.records if not row.completed]
        if incomplete:
            raise ValueError(f"ground truth has incomplete records: {len(incomplete)}")


class FieldConfirmation(VisualStrictModel):
    material_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    field: str = Field(min_length=1)
    original_value: Any = None
    original_status: Literal["measured", "candidate", "confirmed", "abstained", "unavailable"]
    confirmed_value: Any = None
    confirmed_status: Literal["confirmed", "abstained"]
    reviewer_note: str = ""
    changed_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def abstention_has_no_value(self) -> "FieldConfirmation":
        if self.confirmed_status == "abstained" and self.confirmed_value is not None:
            raise ValueError("abstained confirmation must not carry a value")
        return self


class VisualConfirmation(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    source_observations_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["completed", "partial"]
    reviewer: str = Field(min_length=1)
    items: list[FieldConfirmation]

    @model_validator(mode="after")
    def fields_are_unique_per_material(self) -> "VisualConfirmation":
        keys = [(item.material_id, item.field) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate field confirmation")
        return self


class DirectorVisualBrief(VisualStrictModel):
    brief_id: str = Field(min_length=1)
    purpose: Literal["development_anchor", "blind_project"]
    brief: RawCreativeBrief


class DirectorVisualBriefSet(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    briefs: list[DirectorVisualBrief]


class DuplicateFixtureResult(VisualStrictModel):
    exact_match: bool
    near_match: bool
    distinct_match: bool
    exact_distance: int
    near_distance: int
    distinct_distance: int
    threshold: int
    real_pair_status: Literal["not_evaluated_real_pair"] = "not_evaluated_real_pair"


def _dhash(path: Path) -> int:
    with Image.open(path) as image:
        gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(gray.get_flattened_data())
    value = 0
    for row in range(8):
        for column in range(8):
            left = pixels[row * 9 + column]
            right = pixels[row * 9 + column + 1]
            value = (value << 1) | int(left > right)
    return value


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def evaluate_duplicate_fixture(
    original: Path,
    exact: Path,
    near: Path,
    distinct: Path,
    *,
    threshold: int = 8,
) -> DuplicateFixtureResult:
    original_hash = _dhash(original)
    exact_distance = _hamming(original_hash, _dhash(exact))
    near_distance = _hamming(original_hash, _dhash(near))
    distinct_distance = _hamming(original_hash, _dhash(distinct))
    return DuplicateFixtureResult(
        exact_match=original.read_bytes() == exact.read_bytes(),
        near_match=near_distance <= threshold,
        distinct_match=distinct_distance <= threshold,
        exact_distance=exact_distance,
        near_distance=near_distance,
        distinct_distance=distinct_distance,
        threshold=threshold,
    )


def load_cv_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in payload["items"]:
        rows.append(
            {
                "file": item["file"],
                "brightness_score": item.get("quality", {}).get("brightness_score"),
                "laplacian_variance_raw": item.get("quality", {}).get(
                    "laplacian_variance_raw"
                ),
                "motion_intensity_raw": item.get("motion", {}).get(
                    "motion_intensity_raw"
                ),
            }
        )
    return rows


def _selected_probe_paths(probe_dir: Path, count: int = 4) -> list[Path]:
    files = sorted(probe_dir.glob("*.jpg"))
    if not files:
        raise FileNotFoundError(f"no saved probe frames: {probe_dir}")
    if len(files) <= count:
        return files
    indices = sorted({round(index * (len(files) - 1) / (count - 1)) for index in range(count)})
    return [files[index] for index in indices]


def build_blank_observations(
    split: DirectorVisualSplit,
    source_hashes: dict[str, str],
) -> ClipObservationBatch:
    items: list[ClipObservation] = []
    for manifest in (split.dev, split.blind):
        for entry in manifest.entries:
            source_hash = source_hashes[entry.source.relative_path]
            items.append(
                ClipObservation(
                    material=MaterialRef(
                        material_id=derive_material_id(source_hash),
                        relative_path=entry.source.relative_path,
                        source_sha256=source_hash,
                        size_bytes=entry.source.size_bytes,
                        mtime_ns=entry.source.mtime_ns,
                        duration_seconds=entry.technical.duration,
                        fps=entry.technical.fps,
                        orientation=entry.technical.orientation,
                        rotation=entry.technical.rotation,
                    ),
                    provider="annotation_template",
                    observation_status="abstained",
                    unknown_fields=[
                        "technical_usability",
                        "content_families",
                        "setting",
                        "lighting",
                        "people_presence",
                        "people_count_band",
                        "subject_candidates",
                        "activity_candidates",
                    ],
                    review_required_fields=[
                        "technical_usability",
                        "content_families",
                        "setting",
                        "lighting",
                        "people_presence",
                        "people_count_band",
                    ],
                )
            )
    return ClipObservationBatch(status="partial", mode="scanner_only", items=items)


def default_brief_set() -> DirectorVisualBriefSet:
    return DirectorVisualBriefSet(
        briefs=[
            DirectorVisualBrief(
                brief_id="bright-city-exploration",
                purpose="development_anchor",
                brief=RawCreativeBrief(
                    raw_description="制作一条明亮、有推进感的城市探索旅行短片，重视空间变化和行动感。"
                ),
            ),
            DirectorVisualBrief(
                brief_id="warm-people-memory",
                purpose="development_anchor",
                brief=RawCreativeBrief(
                    raw_description="制作一条温暖、重人物关系和真实互动的旅行回忆短片。"
                ),
            ),
            DirectorVisualBrief(
                brief_id="quiet-cultural-texture",
                purpose="development_anchor",
                brief=RawCreativeBrief(
                    raw_description="制作一条安静、重空间层次与文化质感的旅行短片，节奏克制。"
                ),
            ),
            DirectorVisualBrief(
                brief_id="blind-primary",
                purpose="blind_project",
                brief=RawCreativeBrief(
                    raw_description="制作一条有进入、探索和收束结构的开封旅行短片，兼顾城市氛围与同行体验。"
                ),
            ),
        ]
    )


def freeze_evaluation_pack(
    source_manifest_path: Path,
    cv_profile_path: Path,
    probe_root: Path,
    output_dir: Path,
) -> dict[str, Path]:
    """Freeze metadata-only splits and templates while reusing saved probe frames."""

    inventory = TestManifest.model_validate_json(
        source_manifest_path.read_text(encoding="utf-8")
    )
    split = build_evaluation_split(
        inventory,
        load_cv_rows(cv_profile_path),
        source_manifest_sha256=sha256_file(source_manifest_path),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_entries = split.dev.entries + split.blind.entries
    source_hashes: dict[str, str] = {}
    frame_paths: dict[str, list[str]] = {}
    index_by_path = {
        entry.source.relative_path: index
        for index, entry in enumerate(inventory.entries)
    }
    for entry in selected_entries:
        relative_path = entry.source.relative_path
        source_path = Path(inventory.input_root) / relative_path
        source_hashes[relative_path] = sha256_file(source_path)
        index = index_by_path[relative_path]
        probes = _selected_probe_paths(probe_root / f"{index:04d}")
        frame_paths[relative_path] = [
            path.relative_to(output_dir).as_posix() for path in probes
        ]

    ground_truth = build_ground_truth_template(split, source_hashes, frame_paths)
    observations = build_blank_observations(split, source_hashes)
    paths = {
        "split": output_dir / "director_visual_split.json",
        "dev": output_dir / "director_visual_dev_manifest.json",
        "blind": output_dir / "director_visual_blind_manifest.json",
        "briefs": output_dir / "director_visual_briefs.json",
        "ground_truth": output_dir / "director_visual_ground_truth.template.json",
        "observations": output_dir / "director_visual_observations.template.json",
    }
    payloads = {
        "split": split.model_dump(mode="json"),
        "dev": split.dev.model_dump(mode="json"),
        "blind": split.blind.model_dump(mode="json"),
        "briefs": default_brief_set().model_dump(mode="json"),
        "ground_truth": ground_truth.model_dump(mode="json"),
        "observations": observations.model_dump(mode="json"),
    }
    for name, path in paths.items():
        path.write_bytes(_canonical_bytes(payloads[name]))
    return paths
