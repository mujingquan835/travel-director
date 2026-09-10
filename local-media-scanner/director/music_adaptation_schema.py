"""Music phrase evidence is separate from automatic energy/beat hypotheses."""
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from director.shot_review_schema import ReviewModel


class ListeningRecord(ReviewModel):
    listening_id: str = Field(min_length=1)
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    reviewer: str = Field(min_length=1)
    method: Literal['user_report', 'direct_listening']
    note: str = Field(min_length=1)
    reviewed_at: datetime

    @model_validator(mode='after')
    def range_and_date(self):
        if self.source_out <= self.source_in or self.reviewed_at.tzinfo is None:
            raise ValueError('listening record requires a positive range and timezone-aware date')
        return self


class Phrase(ReviewModel):
    phrase_id: str = Field(min_length=1)
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    label: str = Field(min_length=1)
    status: Literal['candidate', 'confirmed']
    basis: Literal['automatic_energy', 'editorial_proposal', 'listening']
    listening_id: str | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def provenance(self):
        if self.source_out <= self.source_in:
            raise ValueError('phrase source range must be positive')
        if self.status == 'confirmed' and (self.basis != 'listening' or self.listening_id is None):
            raise ValueError('confirmed phrase requires listening evidence; automatic labels remain candidates')
        if self.basis == 'listening' and self.listening_id is None:
            raise ValueError('listening-based phrase requires a record')
        if self.basis != 'listening' and self.listening_id is not None:
            raise ValueError('do not attach listening provenance to an automatic/proposed label')
        return self


class MusicMapping(ReviewModel):
    segment_id: str = Field(min_length=1)
    kind: Literal['music','silence']
    source_in: float | None = Field(ge=0)
    source_out: float | None = Field(gt=0)
    project_in: float = Field(ge=0)
    project_out: float = Field(gt=0)
    phrase_id: str | None = None
    gain: float = Field(ge=0,le=4)
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def original_speed(self):
        duration=self.project_out-self.project_in
        if duration <= 0:
            raise ValueError('mapping interval must be positive')
        if self.kind=='silence':
            if self.source_in is not None or self.source_out is not None or self.phrase_id is not None or self.gain != 0:
                raise ValueError('music silence carries no source interval or phrase and has zero gain')
        elif (self.source_in is None or self.source_out is None or self.source_out<=self.source_in
              or abs(self.source_out-self.source_in-duration)>1e-6):
            raise ValueError('music mapping currently requires original-speed equal source/project duration')
        return self


class MusicEvent(ReviewModel):
    event_id: str = Field(min_length=1)
    kind: Literal['turn','pause','resume','accent','ending']
    project_time: float = Field(ge=0)
    segment_id: str
    source_time: float | None = Field(ge=0)
    status: Literal['proposed','listened']
    listening_id: str | None = None
    reason: str = Field(min_length=1)


class EndingTreatment(ReviewModel):
    treatment: Literal['cut','source_end','silence','fade']
    reason: str = Field(min_length=1)
    listening_id: str | None = None


class PicturePacing(ReviewModel):
    mode: Literal['hold','internal_action','local_fast_cut']
    shot_ids: list[str] = Field(min_length=1,max_length=4)
    event_id: str | None = None
    action_field: Literal['action_start','action_accent','action_end'] | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def local_scope(self):
        if len(self.shot_ids)!=len(set(self.shot_ids)):
            raise ValueError('pacing shot IDs must be unique')
        if self.mode=='internal_action' and (len(self.shot_ids)!=1 or self.event_id is None or self.action_field is None):
            raise ValueError('internal action requires one shot, music event and reviewed action field')
        if self.mode=='local_fast_cut' and len(self.shot_ids)<2:
            raise ValueError('fast cuts must be a reasoned local multi-shot group')
        if self.mode!='internal_action' and self.action_field is not None:
            raise ValueError('action field belongs only to internal-action pacing')
        return self


class MusicAdaptationPlan(ReviewModel):
    schema_version: Literal['1.0.0']='1.0.0'
    music_project: Path
    base_decision: Path
    revision_reason: str = Field(min_length=1,max_length=1000)
    listening: list[ListeningRecord] = Field(default_factory=list,max_length=100)
    phrases: list[Phrase] = Field(default_factory=list,max_length=100)
    mapping: list[MusicMapping] = Field(min_length=1,max_length=100)
    events: list[MusicEvent] = Field(default_factory=list,max_length=100)
    ending: EndingTreatment
    pacing: list[PicturePacing] = Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def identities(self):
        if not self.music_project.is_absolute() or not self.base_decision.is_absolute():
            raise ValueError('music project and base decision require absolute paths')
        for items,key in [(self.listening,'listening_id'),(self.phrases,'phrase_id'),
                          (self.mapping,'segment_id'),(self.events,'event_id')]:
            ids=[getattr(x,key) for x in items]
            if len(ids)!=len(set(ids)):
                raise ValueError(f'duplicate {key}')
        return self
