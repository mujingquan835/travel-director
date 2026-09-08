"""Independent, content-addressed timeline revisions over frozen evidence."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from director.audio_import import load_music_evidence
from director.creative_direction import _context, load_creative
from director.project import (
    ProjectConflict, _paths, _sha256_file, _sha256_bytes, _canonical_bytes,
    _write_state, load_project_state, open_project, record_supporting_artifact,
)
from director.timeline_delivery_store import validate_timeline_delivery
from director.timeline import TimelineConfig
from director.hook_builder import HookConfig
from director.outro_builder import OutroConfig

ALGORITHM_VERSION = 'timeline-revision-1'
EXCLUDED = {'delivery', 'timeline_slots.json', 'clip_placements.json', 'sfx_plan.json',
            'render', 'previews', 'guidance', 'validation', 'timeline_revision.json'}


def _manifest(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ProjectConflict('timeline revision sources must not contain symbolic links')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = _sha256_file(path)
    return result


def validate_revision(paths):
    state = load_project_state(paths)
    expected = state.completed_artifact_hashes.get('timeline_revision')
    record = paths.root / 'timeline_revision.json'
    if expected is None:
        if record.exists():
            raise ProjectConflict('unrecorded timeline revision')
        return None
    if not record.is_file() or _sha256_file(record) != expected:
        raise ProjectConflict('timeline revision lineage missing or drifted')
    data = json.loads(record.read_text())
    for name, digest in data['inherited_files'].items():
        file = paths.root / name
        if not file.is_file() or _sha256_file(file) != digest:
            raise ProjectConflict(f'timeline revision evidence drifted: {name}')
    if 'timeline_delivery' not in state.completed_artifact_hashes:
        for name, digest in data['algorithm_files'].items():
            if _sha256_file(Path(__file__).resolve().parent / name) != digest:
                raise ProjectConflict('pending timeline revision algorithm changed; request a new revision from the parent')
    return data


def create_timeline_revision(parent, require_sfx=()):
    validate_revision(parent)
    validate_timeline_delivery(parent)
    _context(parent)
    load_creative(parent, validate_sources=False)
    if load_music_evidence(parent) is None:
        raise ProjectConflict('timeline revision requires frozen music analysis')
    manifest = _manifest(parent.root)
    package = Path(__file__).resolve().parent
    code_files = ('timeline.py', 'delivery.py', 'hook_builder.py', 'outro_builder.py',
                  'audio_catalog.py', 'export/markdown.py', 'timeline_delivery_store.py',
                  'timeline_revision.py', 'runner.py', 'schema.py', 'sfx_assets.py')
    linkage = {
        'schema_version': '1.0.0', 'algorithm_version': ALGORITHM_VERSION,
        'algorithm_files': {name: _sha256_file(package / name) for name in code_files},
        'parent_project': str(parent.root.resolve()),
        'parent_state_sha256': manifest['project_state.json'],
        'parent_receipt_sha256': manifest['delivery/receipt.json'],
        'configuration': {'require_sfx': sorted(set(require_sfx)),
                          'timeline': TimelineConfig().model_dump(mode='json'),
                          'hook': HookConfig().model_dump(mode='json'),
                          'outro': OutroConfig().model_dump(mode='json')},
        'inherited_files': {name: digest for name, digest in manifest.items()
                            if name.split('/')[0] not in EXCLUDED and name != 'project_state.json'},
    }
    identity = _sha256_bytes(_canonical_bytes(linkage))
    target = parent.root.with_name(f'{parent.root.name}-timeline-{identity[:16]}')
    if target.exists():
        child = open_project(target)
        if validate_revision(child) != linkage:
            raise ProjectConflict('timeline revision destination has different lineage')
        return child
    temporary = Path(tempfile.mkdtemp(prefix=f'.{target.name}-', dir=target.parent))
    try:
        shutil.copytree(parent.root, temporary, dirs_exist_ok=True,
                        ignore=lambda directory, names: EXCLUDED.intersection(names)
                        if Path(directory) == parent.root else set())
        child = _paths(temporary)
        state = load_project_state(child)
        state.project_id = target.name
        for key in ('timeline', 'clip_placements', 'sfx_plan', 'render',
                    'timeline_delivery', 'timeline_delivery_receipt', 'timeline_revision'):
            state.completed_artifact_hashes.pop(key, None)
            state.artifact_paths.pop(key, None)
        _write_state(child, state)
        record_supporting_artifact(child, temporary / 'timeline_revision.json', linkage,
                                   state_key='timeline_revision')
        validate_revision(child)
        if _manifest(parent.root) != manifest:
            raise ProjectConflict('parent changed while creating timeline revision')
        if target.exists():
            raise ProjectConflict('timeline revision appeared during copy; retry')
        os.rename(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return open_project(target)
