"""Local 2–4-shot combinations and paired temporal-evidence references."""
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from director.shot_review_schema import ReviewModel


class ShotGroupBinding(ReviewModel):
    path: Path
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class GroupCanvas(ReviewModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0, le=120)


class GroupShot(ReviewModel):
    shot_id: str = Field(min_length=1, max_length=80)
    review_request: Path
    candidate_id: str
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    function: Literal['opening', 'context', 'action', 'detail', 'reaction', 'contrast', 'release', 'ending']
    reason: str = Field(min_length=1, max_length=500)
    gain: float = Field(default=1, ge=0, le=4)

    @model_validator(mode='after')
    def valid_range(self):
        if self.source_out <= self.source_in:
            raise ValueError('shot source range must be positive')
        if not self.review_request.is_absolute():
            raise ValueError('review_request must be an absolute path')
        return self


class ConnectionAnchor(ReviewModel):
    field: Literal['frames', 'shot_scale', 'subject_position', 'camera_motion',
                   'subject_motion', 'action_start', 'action_accent', 'action_end']
    evidence_frames: list[int] = Field(max_length=65)


class ShotConnection(ReviewModel):
    left_shot_id: str
    right_shot_id: str
    status: Literal['supported', 'needs_review', 'intentional_cut']
    relationship: Literal['motion_match', 'action_match', 'visual_match', 'content', 'contrast', 'hard_cut']
    reason: str = Field(min_length=1, max_length=500)
    left: ConnectionAnchor
    right: ConnectionAnchor

    @model_validator(mode='after')
    def intentional_is_not_match_claim(self):
        if self.status == 'intentional_cut' and self.relationship not in ('hard_cut', 'contrast'):
            raise ValueError('intentional cut cannot claim an unverified match')
        if self.relationship == 'hard_cut' and self.status == 'supported':
            raise ValueError('a plain hard cut must be marked intentional_cut')
        return self


class ShotGroupPlan(ReviewModel):
    schema_version: Literal['1.0.0'] = '1.0.0'
    project_name: str = Field(min_length=1, max_length=120)
    canvas: GroupCanvas
    shots: list[GroupShot] = Field(min_length=2, max_length=4)
    connections: list[ShotConnection] = Field(min_length=1, max_length=3)

    @model_validator(mode='after')
    def adjacency(self):
        ids = [s.shot_id for s in self.shots]
        if len(ids) != len(set(ids)):
            raise ValueError('shot IDs must be unique')
        pairs = [(s.left_shot_id, s.right_shot_id) for s in self.connections]
        if pairs != list(zip(ids, ids[1:])):
            raise ValueError('connections must cover each adjacent pair exactly once in shot order')
        return self
