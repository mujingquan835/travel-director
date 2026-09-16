"""Freeze selected effects and resolve only verified delivery-local bytes."""
from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field

from director.audio_catalog import _probe_duration
from director.project import ProjectConflict, _sha256_bytes, _sha256_file
from director.schema import StrictModel


class SfxAsset(StrictModel):
    role: Literal['hook_riser', 'hook_hit', 'outro']
    source_absolute_path: str
    source_relative_path: str
    frozen_relative_path: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)


def selected_sfx(timeline):
    selected = {}
    if timeline.hook_plan is not None:
        selected.update(hook_riser=timeline.hook_plan.riser_path,
                        hook_hit=timeline.hook_plan.hit_path)
    if timeline.outro_plan is not None and timeline.outro_plan.sfx_path:
        selected['outro'] = timeline.outro_plan.sfx_path
    return selected


def freeze_sfx_assets(timeline, library_root: Path | None, project_root: Path):
    assets = []
    for role, relative in selected_sfx(timeline).items():
        if library_root is None:
            raise ProjectConflict('SFX library root is required to freeze selected effects')
        library = library_root.resolve()
        source = (library / relative).resolve()
        if not source.is_relative_to(library) or Path(relative).is_absolute():
            raise ProjectConflict(f'SFX source is outside library: {relative}')
        before = _sha256_file(source)
        data = source.read_bytes()
        digest = _sha256_bytes(data)
        if digest != before or _sha256_file(source) != digest:
            raise ProjectConflict(f'SFX source changed during freezing: {relative}')
        suffix = source.suffix.lower()
        if suffix not in {'.wav', '.mp3', '.m4a'} or not data:
            raise ProjectConflict(f'Invalid SFX audio: {relative}')
        relative_frozen = f'delivery/assets/sfx-{digest}{suffix}'
        destination = project_root / relative_frozen
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.parent.resolve() != project_root.resolve() / 'delivery/assets':
            raise ProjectConflict('SFX asset directory must not be redirected')
        fd, temporary = tempfile.mkstemp(prefix='.sfx-', suffix=suffix, dir=destination.parent)
        temporary = Path(temporary)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            duration = _probe_duration(temporary)
            if not math.isfinite(duration) or duration <= 0:
                raise ProjectConflict(f'Invalid SFX duration: {relative}')
            # Publish without overwriting an existing asset, including a damaged one.
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if destination.is_symlink() or _sha256_file(destination) != digest:
                    raise ProjectConflict(f'Frozen SFX missing or drifted: {relative_frozen}')
        finally:
            temporary.unlink(missing_ok=True)
        assets.append(SfxAsset(role=role, source_absolute_path=str(source),
                               source_relative_path=relative, frozen_relative_path=relative_frozen,
                               sha256=digest, size_bytes=len(data), duration_seconds=duration))
    frozen = timeline.model_copy(update={'schema_version': '1.2.0', 'sfx_assets': assets})
    validate_sfx_assets(frozen, project_root)
    return frozen


def validate_sfx_assets(timeline, project_root: Path) -> dict[str, Path]:
    """Preflight for delivery/resume and future render consumers; never use source paths."""
    selected = selected_sfx(timeline)
    if timeline.sfx_assets is None:
        raise ProjectConflict('Legacy SFX bytes are not frozen; create a new timeline revision')
    if len(timeline.sfx_assets) != len(selected) or {a.role for a in timeline.sfx_assets} != set(selected):
        raise ProjectConflict('SFX asset roles do not match selected plans')
    result = {}
    for asset in timeline.sfx_assets:
        path = project_root / asset.frozen_relative_path
        expected_prefix = f'delivery/assets/sfx-{asset.sha256}'
        if (asset.source_relative_path != selected[asset.role]
                or asset.frozen_relative_path not in {expected_prefix + ext for ext in ('.wav', '.mp3', '.m4a')}
                or path.is_symlink() or not path.is_file()
                or path.resolve() != project_root.resolve() / asset.frozen_relative_path
                or path.stat().st_size != asset.size_bytes or _sha256_file(path) != asset.sha256):
            raise ProjectConflict(f'Frozen SFX missing or drifted: {asset.role}')
        result[asset.role] = path.resolve()
    return result
