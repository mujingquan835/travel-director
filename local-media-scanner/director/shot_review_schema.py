"""Independent, compact temporal review contract; never extends coarse assertions."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from director.visual_schema import MaterialRef


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ShotCandidate(ReviewModel):
    material_id: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    purpose: Literal['selected', 'connection_uncertain']
    reason: str = Field(min_length=1, max_length=400)

    @model_validator(mode='after')
    def bounded_interval(self):
        if not 0 < self.source_out - self.source_in <= 8:
            raise ValueError('candidate interval must be positive and at most 8 seconds')
        return self


class ShotSelection(ReviewModel):
    items: list[ShotCandidate] = Field(min_length=1, max_length=10)

    @model_validator(mode='after')
    def bounded_selection(self):
        keys = [(x.material_id, x.source_in, x.source_out) for x in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate candidate interval')
        if sum(x.source_out - x.source_in for x in self.items) > 40:
            raise ValueError('selected intervals exceed 40 seconds')
        return self


class HashedReviewFile(ReviewModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class ReviewFrame(HashedReviewFile):
    source_time: float = Field(ge=0)


class ShotPacket(ReviewModel):
    candidate_id: str
    candidate: ShotCandidate
    material: MaterialRef
    frames: list[ReviewFrame] = Field(min_length=1, max_length=65)
    sheets: list[HashedReviewFile] = Field(min_length=1, max_length=6)


class ShotReviewRequest(ReviewModel):
    schema_version: Literal['1.0.0'] = '1.0.0'
    recipe: Literal['dense-pts-v1-8fps-640px'] = 'dense-pts-v1-8fps-640px'
    request_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    project_path: str
    input_root: str
    upstream_hashes: dict[str, str]
    selection: ShotSelection
    packets: list[ShotPacket] = Field(min_length=1, max_length=10)
    external_call_count: Literal[0] = 0


class FrameJudgment(ReviewModel):
    value: str | None
    confidence: float | None = Field(ge=0, le=1)
    evidence_frames: list[int] = Field(max_length=65)
    reason: str = Field(min_length=1, max_length=400)

    @model_validator(mode='after')
    def supported_or_abstained(self):
        if self.value is None:
            if self.confidence is not None or self.evidence_frames:
                raise ValueError('abstention must not carry confidence or evidence')
        elif not self.value.strip() or self.confidence is None or not self.evidence_frames:
            raise ValueError('candidate judgment requires value, confidence and frame evidence')
        return self


class ActionMoment(ReviewModel):
    time_seconds: float = Field(ge=0)
    uncertainty_seconds: float = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    evidence_frames: list[int] = Field(min_length=2, max_length=65)
    reason: str = Field(min_length=1, max_length=400)


class CompactShotObservation(ReviewModel):
    candidate_id: str
    source_in: float | None = Field(ge=0)
    source_out: float | None = Field(gt=0)
    range_confidence: float | None = Field(ge=0, le=1)
    range_evidence_frames: list[int] = Field(max_length=65)
    range_reason: str = Field(min_length=1, max_length=400)
    shot_scale: FrameJudgment
    subject_position: FrameJudgment
    camera_motion: FrameJudgment
    subject_motion: FrameJudgment
    action_description: str | None = Field(min_length=1, max_length=400)
    action_start: ActionMoment | None
    action_accent: ActionMoment | None
    action_end: ActionMoment | None
    action_unknown_reason: str | None = Field(min_length=1, max_length=400)

    @model_validator(mode='after')
    def unknowns_and_order(self):
        if self.source_in is None or self.source_out is None:
            if not (self.source_in is self.source_out is self.range_confidence is None
                    and not self.range_evidence_frames):
                raise ValueError('unknown source range requires both times and confidence null')
        elif self.source_out <= self.source_in or self.range_confidence is None or len(self.range_evidence_frames) < 2:
            raise ValueError('source range requires ordered bounds, confidence and two frames')
        moments = [self.action_start, self.action_accent, self.action_end]
        if any(moments) and self.action_description is None:
            raise ValueError('action moments require a primary action description')
        if any(x is None for x in moments) and not self.action_unknown_reason:
            raise ValueError('missing action moments require an uncertainty reason')
        times = [x.time_seconds for x in moments if x is not None]
        if times != sorted(times):
            raise ValueError('action start/accent/end must be ordered')
        return self


class CompactShotReview(ReviewModel):
    items: list[CompactShotObservation] = Field(min_length=1, max_length=10)
