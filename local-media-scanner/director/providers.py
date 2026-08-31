"""Replaceable provider contracts for the V0.2 visual director workflow."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from director.visual_schema import (
    BriefConfirmation,
    ClipObservation,
    ClipObservationBatch,
    DirectorTreatment,
    IntentDecisionBatch,
    MaterialRef,
    NormalizedIntentDraft,
    ProjectCoverage,
    ProviderCapabilities,
    RawCreativeBrief,
)


@runtime_checkable
class VisualUnderstandingProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def observe(self, material: MaterialRef, evidence: dict[str, Any]) -> ClipObservation: ...


@runtime_checkable
class BriefInterpreterProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def normalize(self, brief: RawCreativeBrief) -> NormalizedIntentDraft: ...


@runtime_checkable
class DirectorReasoningProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def build_treatment(
        self,
        observations: ClipObservationBatch,
        brief: BriefConfirmation,
        decisions: IntentDecisionBatch,
        coverage: ProjectCoverage,
    ) -> DirectorTreatment: ...
