"""Draft, confirmed, and history snapshots of music edit regions.

These versions live **inside one project**. They are not ``music_version``
child projects. ``director.music_version.create_music_version`` forks a project
onto a new track (``<project>-music-<sha16>``). Every regions version here stays
bound to the same frozen ``source_sha256``; a different track must open a child
project instead.

Layout (sibling of the analyzer candidate ``music_edit_regions.json``)::

    <project>/music_edit_regions_versions/
      index.json                         # mutable listing
      draft.json                         # at most one editable snapshot
      confirmed/regions-vNN.json         # write-once confirmed snapshot
      receipts/regions-receipt-NN.json   # write-once action receipt

Hash keys in ``project_state.json`` follow existing artifact habits:

- ``music_edit_regions_versions_index`` and ``music_edit_regions_version_draft``
  use ``record_supporting_artifact`` (replaceable while the recorded hash still
  matches the file).
- ``music_edit_regions_version:<id>`` and ``music_edit_regions_receipt:<id>``
  are write-once, same rule as stage artifacts: a different payload is refused.
- The analyzer key ``music_edit_regions`` is not a version key.
  ``create_music_version`` skips this directory and strips version hash keys
  from the child so a new track does not inherit a lock for the old track.

Listing status is ``draft``, ``confirmed`` (latest lock), or ``history`` (older
locks). File status is only ``draft`` or ``confirmed``. History stays
immutable. There is no unlock.

``stage_regions_reanalysis`` is the re-run data rule: replace the open draft,
or open a new draft when the latest snapshot is confirmed. It never rewrites
``confirmed/``. Once this directory exists, ``build_project_music_edit_regions``
calls that rule after refreshing the analyzer candidate file.

Confirm freezes the shot track into that write-once file: regions, ``shot_style``,
``shot_rules_version``, and the guidance layer. Opening a confirmed or history
version reads the file and does not replan. A draft still replans with the
current rules. If the frozen rule version disagrees with the running code, the
desk only says 「有新规则，可另存新草稿」 and leaves the file alone. A confirmed
file from before snapshots existed stays byte-identical; the desk says so and
``migrate_unlocked_confirmed_regions`` opens a new draft under the current rules.

``require_confirmed_regions_version`` is the export gate. Missing ids,
``latest``, and drafts are refused. ``export_fcpxml_for_confirmed_regions``
writes a 30 fps FCPXML package and a markdown edit sheet from that snapshot
only. It does not replan. Markers, gap names, and gap placeholders are not
claimed to survive a Jianying import.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from director.music_edit_regions_schema import MusicEditRegions, region_invariant_violations
from director.project import (
    ProjectConflict,
    ProjectPaths,
    _canonical_bytes,
    _json_value,
    _sha256_bytes,
    _sha256_file,
    _write_state,
    load_project_state,
    record_supporting_artifact,
)
from director.schema import StrictModel


VERSIONS_DIR_NAME = "music_edit_regions_versions"
INDEX_KEY = "music_edit_regions_versions_index"
DRAFT_KEY = "music_edit_regions_version_draft"
_REFUSED_EXPORT_IDS = frozenset({"", "latest", "draft"})


class RegionsVersionError(ProjectConflict):
    """Regions version store refused a write or a missing draft."""


class RegionsConfirmGateError(RegionsVersionError):
    """Export refused because no explicit confirmed regions version was selected."""


def is_regions_version_state_key(key: str) -> bool:
    """True for version-store hash keys, never for the analyzer ``music_edit_regions`` key."""

    return key.startswith("music_edit_regions_version") or key.startswith(
        "music_edit_regions_receipt"
    )


def version_state_key(version_id: str) -> str:
    return f"music_edit_regions_version:{version_id}"


def receipt_state_key(receipt_id: str) -> str:
    return f"music_edit_regions_receipt:{receipt_id}"


def regions_content_sha256(regions: MusicEditRegions) -> str:
    return _sha256_bytes(_canonical_bytes(regions.model_dump(mode="json")))


class RegionsVersionDocument(StrictModel):
    """One draft or confirmed snapshot. History is a listing status, not a third file status."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    version_id: str = Field(pattern=r"^regions-v[0-9]{2,}$")
    status: Literal["draft", "confirmed"]
    source_music_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_music_sha8: str = Field(pattern=r"^[0-9a-f]{8}$")
    created_at: str = Field(min_length=1)
    edited_at: str | None = None
    confirmed_at: str | None = None
    confirmed_by: Literal["user"] | None = None
    parent_version_id: str | None = None
    regions: MusicEditRegions
    regions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def snapshot_matches_regions(self) -> "RegionsVersionDocument":
        if self.source_music_sha8 != self.source_music_sha256[:8]:
            raise ValueError("source_music_sha8 must be the leading 8 characters of source_music_sha256")
        if self.regions.source_sha256 != self.source_music_sha256:
            raise ValueError("regions are bound to a different source")
        if self.regions_sha256 != regions_content_sha256(self.regions):
            raise ValueError("regions_sha256 does not match regions")
        if self.status == "draft" and (self.confirmed_at is not None or self.confirmed_by is not None):
            raise ValueError("draft cannot carry confirmation")
        if self.status == "confirmed" and (not self.confirmed_at or self.confirmed_by != "user"):
            raise ValueError("confirmed version requires confirmed_at and confirmed_by=user")
        return self


class RegionsVersionListing(StrictModel):
    version_id: str
    status: Literal["draft", "confirmed", "history"]
    source_music_sha8: str = Field(pattern=r"^[0-9a-f]{8}$")
    confirmed_at: str | None = None


class RegionsVersionIndex(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    source_music_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    draft_version_id: str | None = None
    confirmed_version_ids: list[str] = Field(default_factory=list)
    next_serial: int = Field(default=1, ge=1)


class RegionsBaseline(StrictModel):
    """What remains after the draft overlay is gone.

    ``confirmed`` is the latest locked snapshot. ``analyzer`` is the sibling
    ``music_edit_regions.json`` candidate file. ``none`` means neither exists.
    """

    kind: Literal["confirmed", "analyzer", "none"]
    version_id: str | None = None
    source_music_sha8: str | None = None
    regions_sha256: str | None = None


class RegionsActionReceipt(StrictModel):
    """Receipt for draft save, confirm, and the later re-run / export hooks.

    ``rerun`` and ``export`` are accepted so those writers have a place to
    attach. Slice 1 records them; it does not run a re-analysis job machine or
    build an FCPXML package.
    """

    schema_version: Literal["0.1.0"] = "0.1.0"
    receipt_id: str = Field(pattern=r"^regions-receipt-.+")
    action: Literal["draft_save", "confirm", "rerun", "export"]
    version_id: str = Field(min_length=1)
    source_music_sha8: str = Field(pattern=r"^[0-9a-f]{8}$")
    created_at: str = Field(min_length=1)
    regions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    override: bool = False
    reason: str | None = None

    @model_validator(mode="after")
    def override_requires_reason(self) -> "RegionsActionReceipt":
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        if self.override:
            if self.action != "confirm":
                raise ValueError("only confirm receipts record an override")
            if not self.reason:
                raise ValueError("override receipt requires a non-empty reason")
        elif self.reason:
            raise ValueError("reason is only recorded for an override")
        return self


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _versions_dir(paths: ProjectPaths) -> Path:
    return paths.root / VERSIONS_DIR_NAME


def _index_path(paths: ProjectPaths) -> Path:
    return _versions_dir(paths) / "index.json"


def _draft_path(paths: ProjectPaths) -> Path:
    return _versions_dir(paths) / "draft.json"


def _confirmed_path(paths: ProjectPaths, version_id: str) -> Path:
    return _versions_dir(paths) / "confirmed" / f"{version_id}.json"


def _receipt_path(paths: ProjectPaths, receipt_id: str) -> Path:
    return _versions_dir(paths) / "receipts" / f"{receipt_id}.json"


def _read_model(paths: ProjectPaths, path: Path, state_key: str, model: type[Any]) -> Any | None:
    state = load_project_state(paths)
    recorded = state.completed_artifact_hashes.get(state_key)
    if recorded is None and not path.is_file():
        return None
    if recorded is None or not path.is_file() or _sha256_file(path) != recorded:
        raise ProjectConflict(f"supporting artifact hash drifted: {state_key}")
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _load_index(paths: ProjectPaths) -> RegionsVersionIndex | None:
    return _read_model(paths, _index_path(paths), INDEX_KEY, RegionsVersionIndex)


def _write_mutable(paths: ProjectPaths, destination: Path, value: Any, state_key: str) -> str:
    return record_supporting_artifact(paths, destination, value, state_key=state_key)


def _write_once(paths: ProjectPaths, destination: Path, value: Any, state_key: str) -> str:
    """Write a supporting artifact that cannot be replaced by a different payload."""

    payload_hash = _sha256_bytes(_canonical_bytes(_json_value(value)))
    state = load_project_state(paths)
    recorded = state.completed_artifact_hashes.get(state_key)
    if recorded is not None:
        if not destination.is_file() or _sha256_file(destination) != recorded:
            raise ProjectConflict(f"supporting artifact hash drifted: {state_key}")
        if recorded != payload_hash:
            raise RegionsVersionError(f"confirmed regions version is immutable: {state_key}")
        return recorded
    if destination.exists():
        raise ProjectConflict(f"untracked supporting artifact already exists: {state_key}")
    return record_supporting_artifact(paths, destination, value, state_key=state_key)


def _write_index(paths: ProjectPaths, index: RegionsVersionIndex) -> None:
    if index.draft_version_id is None and not index.confirmed_version_ids:
        index.source_music_sha256 = None
    _write_mutable(paths, _index_path(paths), index, INDEX_KEY)


def _allocate_version_id(index: RegionsVersionIndex) -> str:
    """Hand out the next ``regions-vNN`` id. Discard does not return it to the pool."""

    version_id = f"regions-v{index.next_serial:02d}"
    index.next_serial += 1
    return version_id


def _next_receipt_id(paths: ProjectPaths) -> str:
    state = load_project_state(paths)
    count = sum(1 for key in state.completed_artifact_hashes if key.startswith("music_edit_regions_receipt:"))
    return f"regions-receipt-{count + 1:02d}"


def _require_same_track(index: RegionsVersionIndex | None, regions: MusicEditRegions) -> None:
    if index is not None and index.source_music_sha256 and regions.source_sha256 != index.source_music_sha256:
        raise RegionsVersionError(
            "regions versions stay on one frozen track; open a music_version child project for a new track"
        )


def _make_document(
    *,
    version_id: str,
    status: Literal["draft", "confirmed"],
    regions: MusicEditRegions,
    created_at: str,
    edited_at: str | None,
    parent_version_id: str | None,
    confirmed_at: str | None = None,
    confirmed_by: Literal["user"] | None = None,
) -> RegionsVersionDocument:
    return RegionsVersionDocument(
        version_id=version_id,
        status=status,
        source_music_sha256=regions.source_sha256,
        source_music_sha8=regions.source_sha256[:8],
        created_at=created_at,
        edited_at=edited_at,
        confirmed_at=confirmed_at,
        confirmed_by=confirmed_by,
        parent_version_id=parent_version_id,
        regions=regions,
        regions_sha256=regions_content_sha256(regions),
    )


def _retarget(document: RegionsVersionDocument, regions: MusicEditRegions, edited_at: str) -> RegionsVersionDocument:
    return _make_document(
        version_id=document.version_id,
        status="draft",
        regions=regions,
        created_at=document.created_at,
        edited_at=edited_at,
        parent_version_id=document.parent_version_id,
    )


def _listing_for(document: RegionsVersionDocument, status: Literal["draft", "confirmed", "history"]) -> RegionsVersionListing:
    return RegionsVersionListing(
        version_id=document.version_id,
        status=status,
        source_music_sha8=document.source_music_sha8,
        confirmed_at=None if status == "draft" else document.confirmed_at,
    )


def _load_confirmed(paths: ProjectPaths, version_id: str) -> RegionsVersionDocument:
    document = _read_model(
        paths,
        _confirmed_path(paths, version_id),
        version_state_key(version_id),
        RegionsVersionDocument,
    )
    if document is None or document.version_id != version_id or document.status != "confirmed":
        raise ProjectConflict(f"supporting artifact hash drifted: {version_state_key(version_id)}")
    return document


def _load_draft_document(paths: ProjectPaths) -> RegionsVersionDocument | None:
    document = _read_model(paths, _draft_path(paths), DRAFT_KEY, RegionsVersionDocument)
    if document is not None and document.status != "draft":
        raise ProjectConflict("supporting artifact hash drifted: music_edit_regions_version_draft")
    return document


def load_regions_draft(paths: ProjectPaths) -> RegionsVersionDocument | None:
    """Return the open draft, or None when the index has no draft."""

    index = _load_index(paths)
    if index is None or index.draft_version_id is None:
        return None
    draft = _load_draft_document(paths)
    if draft is None or draft.version_id != index.draft_version_id:
        raise ProjectConflict("regions draft index drifted")
    return draft


def load_regions_version(paths: ProjectPaths, version_id: str) -> RegionsVersionDocument:
    index = _load_index(paths)
    if index is not None and version_id in index.confirmed_version_ids:
        return _load_confirmed(paths, version_id)
    draft = load_regions_draft(paths)
    if draft is not None and draft.version_id == version_id:
        return draft
    raise RegionsVersionError(f"unknown regions version: {version_id}")


def list_regions_versions(paths: ProjectPaths) -> list[RegionsVersionListing]:
    """Chronological listings: older locks, latest confirmed, then the open draft."""

    index = _load_index(paths)
    if index is None:
        return []
    listings: list[RegionsVersionListing] = []
    last = len(index.confirmed_version_ids) - 1
    for offset, version_id in enumerate(index.confirmed_version_ids):
        document = _load_confirmed(paths, version_id)
        status: Literal["confirmed", "history"] = "confirmed" if offset == last else "history"
        listings.append(_listing_for(document, status))
    draft = load_regions_draft(paths)
    if draft is not None:
        listings.append(_listing_for(draft, "draft"))
    return listings


def list_regions_receipts(paths: ProjectPaths) -> list[RegionsActionReceipt]:
    state = load_project_state(paths)
    receipts: list[RegionsActionReceipt] = []
    for key in sorted(state.completed_artifact_hashes):
        if not key.startswith("music_edit_regions_receipt:"):
            continue
        receipt_id = key.removeprefix("music_edit_regions_receipt:")
        receipt = _read_model(paths, _receipt_path(paths, receipt_id), key, RegionsActionReceipt)
        if receipt is None:
            raise ProjectConflict(f"supporting artifact hash drifted: {key}")
        receipts.append(receipt)
    return receipts


def _append_receipt(
    paths: ProjectPaths,
    *,
    action: Literal["draft_save", "confirm", "rerun", "export"],
    document: RegionsVersionDocument,
    override: bool,
    reason: str | None,
) -> RegionsActionReceipt:
    receipt = RegionsActionReceipt(
        receipt_id=_next_receipt_id(paths),
        action=action,
        version_id=document.version_id,
        source_music_sha8=document.source_music_sha8,
        created_at=_now(),
        regions_sha256=document.regions_sha256,
        override=override,
        reason=reason,
    )
    _write_once(paths, _receipt_path(paths, receipt.receipt_id), receipt, receipt_state_key(receipt.receipt_id))
    return receipt


def _store_draft(paths: ProjectPaths, index: RegionsVersionIndex, document: RegionsVersionDocument) -> RegionsVersionDocument:
    index.draft_version_id = document.version_id
    index.source_music_sha256 = document.source_music_sha256
    _write_mutable(paths, _draft_path(paths), document, DRAFT_KEY)
    _write_index(paths, index)
    return document


def save_regions_draft(paths: ProjectPaths, regions: MusicEditRegions) -> RegionsVersionDocument:
    """Create the single draft, or replace it in place. Writes a ``draft_save`` receipt.

    When a confirmed snapshot already exists, the new draft's parent is the
    latest confirmed version. Confirmed files are not modified. A draft is not
    a snapshot: the shot-track lock is cleared on write.
    """

    from director.shot_slots import unlock_shot_track

    regions = unlock_shot_track(regions)
    index = _load_index(paths) or RegionsVersionIndex()
    _require_same_track(index, regions)
    now = _now()
    if index.draft_version_id:
        current = load_regions_draft(paths)
        if current is None:
            raise ProjectConflict("regions draft index drifted")
        document = _retarget(current, regions, now)
    else:
        parent = index.confirmed_version_ids[-1] if index.confirmed_version_ids else None
        document = _make_document(
            version_id=_allocate_version_id(index),
            status="draft",
            regions=regions,
            created_at=now,
            edited_at=now,
            parent_version_id=parent,
        )
    _store_draft(paths, index, document)
    _append_receipt(paths, action="draft_save", document=document, override=False, reason=None)
    return document


def replace_regions_version(
    paths: ProjectPaths, version_id: str, regions: MusicEditRegions
) -> RegionsVersionDocument:
    """Replace a draft by id. Confirmed and history ids are immutable."""

    index = _load_index(paths)
    if index is not None and version_id in index.confirmed_version_ids:
        raise RegionsVersionError(f"confirmed regions version is immutable: {version_id}")
    if index is None or index.draft_version_id != version_id:
        raise RegionsVersionError(f"unknown regions version: {version_id}")
    return save_regions_draft(paths, regions)


def _confirm_blockers(regions: MusicEditRegions) -> list[str]:
    problems = list(region_invariant_violations(regions))
    unknown = [region.region_id for region in regions.regions if region.edit_role == "unknown"]
    if unknown:
        problems.append("unknown regions: " + ", ".join(unknown))
    return problems


def technique_priors(paths: ProjectPaths, *, exclude: str | None = None) -> list:
    """Confirmed technique plans on this project, oldest first. Skips snapshots with no theme."""

    from director.shot_track.differentiate import prior_from_regions

    index = _load_index(paths)
    if index is None:
        return []
    priors = []
    for version_id in index.confirmed_version_ids:
        if version_id == exclude:
            continue
        try:
            document = _load_confirmed(paths, version_id)
        except (RegionsVersionError, OSError, ValueError):
            continue
        prior = prior_from_regions(document.regions)
        if prior is not None:
            priors.append(prior)
    return priors


def confirm_regions_draft(
    paths: ProjectPaths, *, force: bool = False, reason: str | None = None
) -> RegionsVersionListing:
    """Lock the open draft. Force-confirm requires a non-empty reason and records override."""

    draft = load_regions_draft(paths)
    if draft is None:
        raise RegionsVersionError("nothing to confirm; open a draft first")
    cleaned = reason.strip() if isinstance(reason, str) else None
    if cleaned == "":
        cleaned = None
    if force:
        if not cleaned:
            raise RegionsVersionError("force-confirm requires a non-empty reason")
    else:
        if cleaned:
            raise RegionsVersionError("reason is only accepted with force-confirm")
        blockers = _confirm_blockers(draft.regions)
        if blockers:
            raise RegionsVersionError("confirm refused: " + "; ".join(blockers))
    from director.shot_slots import freeze_shot_track

    frozen = freeze_shot_track(
        draft.regions,
        version_id=draft.version_id,
        prior=technique_priors(paths, exclude=draft.version_id),
    )
    confirmed = _make_document(
        version_id=draft.version_id,
        status="confirmed",
        regions=frozen,
        created_at=draft.created_at,
        edited_at=draft.edited_at,
        parent_version_id=draft.parent_version_id,
        confirmed_at=_now(),
        confirmed_by="user",
    )
    _write_once(paths, _confirmed_path(paths, confirmed.version_id), confirmed, version_state_key(confirmed.version_id))
    _append_receipt(
        paths,
        action="confirm",
        document=confirmed,
        override=force,
        reason=cleaned if force else None,
    )
    _delete_draft(paths)
    index = _load_index(paths)
    if index is None:
        raise ProjectConflict("regions version index missing")
    index.confirmed_version_ids = [*index.confirmed_version_ids, confirmed.version_id]
    index.draft_version_id = None
    _write_index(paths, index)
    return _listing_for(confirmed, "confirmed")


def _delete_draft(paths: ProjectPaths) -> None:
    draft_path = _draft_path(paths)
    if draft_path.is_file():
        draft_path.unlink()
    state = load_project_state(paths)
    if DRAFT_KEY not in state.completed_artifact_hashes:
        return
    state.completed_artifact_hashes.pop(DRAFT_KEY, None)
    _write_state(paths, state)


def current_regions_baseline(paths: ProjectPaths) -> RegionsBaseline:
    """Baseline ignoring any open draft: latest confirmed, else analyzer candidate, else none."""

    index = _load_index(paths)
    if index is not None and index.confirmed_version_ids:
        version_id = index.confirmed_version_ids[-1]
        document = _load_confirmed(paths, version_id)
        return RegionsBaseline(
            kind="confirmed",
            version_id=version_id,
            source_music_sha8=document.source_music_sha8,
            regions_sha256=document.regions_sha256,
        )
    state = load_project_state(paths)
    recorded = state.completed_artifact_hashes.get("music_edit_regions")
    artifact = paths.music_edit_regions
    if recorded is not None:
        if not artifact.is_file() or _sha256_file(artifact) != recorded:
            raise ProjectConflict("supporting artifact hash drifted: music_edit_regions")
        regions = MusicEditRegions.model_validate_json(artifact.read_text(encoding="utf-8"))
        return RegionsBaseline(
            kind="analyzer",
            version_id=None,
            source_music_sha8=regions.source_sha256[:8],
            regions_sha256=recorded,
        )
    return RegionsBaseline(kind="none")


def discard_regions_draft(paths: ProjectPaths) -> RegionsBaseline:
    """Delete the open draft and return the baseline it was covering.

    Confirmed snapshots and ``music_edit_regions.json`` are left byte-identical.
    """

    if load_regions_draft(paths) is None:
        raise RegionsVersionError("no draft to discard")
    _delete_draft(paths)
    index = _load_index(paths)
    if index is None:
        raise ProjectConflict("regions version index missing")
    index.draft_version_id = None
    _write_index(paths, index)
    return current_regions_baseline(paths)


def migrate_unlocked_confirmed_regions(
    paths: ProjectPaths, version_id: str
) -> RegionsVersionDocument:
    """Open a current-rules draft from a confirmed version that has no snapshot.

    The confirmed file is left byte-identical. A version that already has a
    shot-track snapshot is refused; fork that one with 另存新草稿 instead.
    """

    document = load_regions_version(paths, version_id)
    if document.status != "confirmed":
        raise RegionsVersionError("只能基于已确认的版本另开草稿。")
    if load_regions_draft(paths) is not None:
        raise RegionsVersionError("已经有打开的草稿。先确认或丢弃它，再基于确认版另开。")
    if document.regions.shot_track_locked:
        raise RegionsVersionError("这份确认版已有镜头轨快照。要换规则，请另存新草稿。")
    from director.shot_slots import plan_shot_slots

    return save_regions_draft(paths, plan_shot_slots(document.regions))


def require_confirmed_regions_version(
    paths: ProjectPaths, version_id: str | None
) -> RegionsVersionDocument:
    """Refuse export unless ``version_id`` names a confirmed or history snapshot.

    ``None``, blanks, ``latest``, and ``draft`` never fall through to the newest
    draft or the newest confirmed snapshot.
    """

    if version_id is None or version_id.strip() in _REFUSED_EXPORT_IDS:
        raise RegionsConfirmGateError(
            "export requires an explicit confirmed regions version id; refusing latest and draft"
        )
    selected = version_id.strip()
    found = {item.version_id: item for item in list_regions_versions(paths)}.get(selected)
    if found is None or found.status == "draft":
        raise RegionsConfirmGateError(
            "export refuses a draft or unknown regions version; select an explicit confirmed version id"
        )
    return load_regions_version(paths, selected)


def _frozen_audio_for_export(paths: ProjectPaths):
    from director.audio_import import ImportedMusicAsset
    from director.regions_fcpxml import FrozenAudio

    state = load_project_state(paths)
    recorded = state.completed_artifact_hashes.get("music_asset")
    asset_path = paths.generated_music
    if recorded is None or not asset_path.is_file():
        raise RegionsVersionError("还没有冻结的配乐，不能导出。")
    if _sha256_file(asset_path) != recorded:
        raise ProjectConflict("supporting artifact hash drifted: music_asset")
    asset = ImportedMusicAsset.model_validate_json(asset_path.read_text(encoding="utf-8"))
    relative = Path(asset.frozen_relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise RegionsVersionError("冻结的配乐路径不在项目里，不能导出。")
    frozen = (paths.root / relative).resolve()
    root = paths.root.resolve()
    if not frozen.is_file() or not frozen.is_relative_to(root):
        raise RegionsVersionError("冻结的配乐文件不在项目里，不能导出。")
    if _sha256_file(frozen) != asset.source_sha256:
        raise ProjectConflict("frozen music asset hash drifted")
    return FrozenAudio(
        path=frozen,
        duration_seconds=asset.duration_seconds,
        sample_rate=asset.sample_rate,
        channels=asset.channels,
    )


def export_fcpxml_for_confirmed_regions(paths: ProjectPaths, version_id: str | None, output_dir: Path):
    """Write FCPXML and an edit sheet for one confirmed snapshot.

    Drafts, ``latest``, and a missing id are refused before any directory is
    created. The shot track is the one stored on that snapshot.
    """

    from director.regions_fcpxml import write_regions_fcpxml

    document = require_confirmed_regions_version(paths, version_id)
    audio = _frozen_audio_for_export(paths)
    try:
        result = write_regions_fcpxml(document, audio, output_dir)
    except ValueError as exc:
        raise RegionsVersionError(str(exc)) from exc
    record_regions_export_receipt(paths, document.version_id)
    return result


def record_regions_export_receipt(paths: ProjectPaths, version_id: str) -> RegionsActionReceipt:
    """Attach an export receipt to an explicit confirmed or history version.

    The receipt records the action. ``export_fcpxml_for_confirmed_regions``
    writes the package and then calls this.
    """

    document = require_confirmed_regions_version(paths, version_id)
    return _append_receipt(paths, action="export", document=document, override=False, reason=None)


def stage_regions_reanalysis(paths: ProjectPaths, regions: MusicEditRegions) -> RegionsVersionDocument:
    """Put a re-analysis into the draft slot and record a ``rerun`` receipt.

    An open draft is replaced in place. If the current snapshot is confirmed, a
    new draft is opened and confirmed files are not written. No job runner.
    """

    index = _load_index(paths) or RegionsVersionIndex()
    _require_same_track(index, regions)
    now = _now()
    if index.draft_version_id:
        current = load_regions_draft(paths)
        if current is None:
            raise ProjectConflict("regions draft index drifted")
        document = _retarget(current, regions, now)
    else:
        parent = index.confirmed_version_ids[-1] if index.confirmed_version_ids else None
        document = _make_document(
            version_id=_allocate_version_id(index),
            status="draft",
            regions=regions,
            created_at=now,
            edited_at=now,
            parent_version_id=parent,
        )
    _store_draft(paths, index, document)
    _append_receipt(paths, action="rerun", document=document, override=False, reason=None)
    return document


def stage_reanalysis_if_versioned(
    paths: ProjectPaths, regions: MusicEditRegions
) -> RegionsVersionDocument | None:
    """Apply the re-analysis rule only after the operator has opened the version store."""

    if not _index_path(paths).is_file():
        return None
    return stage_regions_reanalysis(paths, regions)
