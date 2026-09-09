"""Resolve explicit picture-anchored sound cues against the local SFX catalog."""
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from director.audio_catalog import scan_sfx_catalog
from director.schema import StrictModel


class SfxCue(StrictModel):
    cue_id: str = Field(min_length=1, max_length=80)
    role: Literal['hook_hit', 'hook_subdrop', 'riser', 'whoosh', 'outro_hit',
                  'outro_piano', 'env_drone', 'env_ambient']
    keywords: list[str] = Field(default_factory=list)
    anchor_video_index: int = Field(ge=0)
    event: str = Field(min_length=1, max_length=200)
    offset_seconds: float = Field(default=0, ge=0)
    duration: float = Field(gt=0)
    gain: float = Field(default=0.5, gt=0, le=4)

    @model_validator(mode='after')
    def concrete_ambient(self):
        if any(not word.strip() for word in self.keywords):
            raise ValueError('SFX keywords must not be blank')
        if self.role == 'env_ambient' and not self.keywords:
            raise ValueError('ambient SFX requires a concrete sound keyword')
        return self


def resolve_sfx_cues(decision, sfx_root: Path):
    """No footage scan, music scan or model call; unmatched cues fail before export."""
    from director.fcpxml_delivery import FcpxmlClipDecision, FcpxmlEditDecision

    root = sfx_root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'SFX library does not exist: {root}')
    entries = scan_sfx_catalog(root)
    videos = [clip for clip in decision.clips if clip.kind == 'video']
    clips = list(decision.clips)
    matches = []
    if len({cue.cue_id for cue in decision.sfx_cues}) != len(decision.sfx_cues):
        raise ValueError('duplicate SFX cue_id')
    for index, cue in enumerate(decision.sfx_cues):
        if cue.anchor_video_index >= len(videos):
            raise ValueError(f'SFX {cue.cue_id}: video anchor does not exist')
        anchor = videos[cue.anchor_video_index]
        if cue.offset_seconds >= anchor.duration:
            raise ValueError(f'SFX {cue.cue_id}: event lies outside anchored picture')
        candidates = [entry for entry in entries
                      if entry.role == cue.role
                      and entry.duration_seconds + 1e-6 >= cue.duration
                      and all(word.casefold() in entry.name.casefold() for word in cue.keywords)]
        candidates.sort(key=lambda entry: (entry.duration_seconds, entry.relative_path))
        if not candidates:
            raise ValueError(f'SFX {cue.cue_id}: no matching playable {cue.role} with keywords {cue.keywords} and duration >= {cue.duration}s')
        entry = candidates[0]
        source = (root / entry.relative_path).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError(f'SFX {cue.cue_id}: source escapes library or is missing')
        track = f'sfx-cue-{index + 1}'
        if any(clip.track == track for clip in clips):
            raise ValueError(f'SFX generated track conflicts with existing track: {track}')
        clip = FcpxmlClipDecision(kind='sfx', source_path=source, track=track,
                                 timeline_in=anchor.timeline_in + cue.offset_seconds,
                                 source_in=0, duration=cue.duration, gain=cue.gain)
        clips.append(clip)
        matches.append({'cue': cue.model_dump(), 'selected': entry.model_dump(),
                        'clip': clip.model_dump(mode='json'),
                        'match_basis': 'exact role and all supplied filename keywords; shortest sufficient duration, path tie-break',
                        'listening_review': 'not_tested'})
    resolved = FcpxmlEditDecision.model_validate({**decision.model_dump(), 'clips': clips, 'sfx_cues': []})
    return resolved, matches
