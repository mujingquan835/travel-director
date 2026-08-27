"""Versioned SigLIP2 prompt evidence for local zero-shot classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import torch
import torch.nn.functional as functional


PROMPT_SET_VERSION = "0.1.0"
DEFAULT_SIGLIP2_MODEL_ID = "google/siglip2-base-patch16-224"
DEFAULT_SIGLIP2_REVISION = "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2"

SCENE_PROMPTS: dict[str, tuple[str, ...]] = {
    "nature": ("a natural landscape", "an outdoor nature scene", "scenery with trees water or mountains"),
    "city": ("a city street scene", "an urban public space", "a downtown travel view"),
    "building": ("a building exterior", "architecture as the main subject", "a travel view of a structure"),
    "indoor": ("an indoor interior space", "a scene inside a building", "an enclosed interior environment"),
    "theme_park": ("a theme park attraction", "an amusement park travel scene", "a tourist attraction with rides or shows"),
    "food_dining": ("a food or dining scene", "a meal being prepared or served", "a restaurant table with food"),
    "transportation": ("a transportation scene", "travel by road rail boat or vehicle", "vehicles as the main travel context"),
    "night_scene": ("an outdoor night scene", "travel scenery after dark", "a nighttime view with artificial lights"),
    "other": ("another kind of travel scene", "a scene outside the listed categories", "an unclear miscellaneous scene"),
}

SHOT_SCALE_PROMPTS: dict[str, tuple[str, ...]] = {
    "wide": ("a wide establishing shot", "a long shot showing the full environment", "a wide view with subjects small in frame"),
    "medium": ("a medium shot", "a subject framed at medium distance", "people or objects occupying a moderate part of frame"),
    "close": ("a close shot", "a nearby subject filling much of the frame", "a close view while retaining some context"),
    "close_up": ("an extreme close-up detail shot", "a small detail filling the frame", "a very tight close-up"),
    "aerial": ("an aerial drone shot", "a view from high above", "a bird's-eye view of the landscape"),
}

PEOPLE_TYPE_PROMPTS: dict[str, tuple[str, ...]] = {
    "child": ("a child is visible", "a young kid in the scene", "children are the people shown"),
    "adult": ("an adult is visible", "a grown person in the scene", "adults are the people shown"),
}

ACTION_PROMPTS: dict[str, tuple[str, ...]] = {
    "walking": ("a person walking", "people are walking", "travelers moving on foot"),
    "running": ("a person running", "people are running", "fast movement on foot"),
    "eating": ("a person eating food", "people having a meal", "someone dining"),
    "riding": ("a person riding something", "someone on a ride or animal", "travelers riding a vehicle or attraction"),
    "entering": ("a person entering a place", "someone going through an entrance", "people moving inside a building"),
    "watching": ("people watching an event", "a person observing something", "an audience looking at a show"),
    "interacting": ("people interacting with each other", "a social human interaction", "people engaging together"),
    "other": ("another action is happening", "an action outside the listed classes", "no clear listed action"),
}

OBJECT_PROMPTS: dict[str, tuple[str, ...]] = {
    "person": ("a person", "a human figure", "people in the scene"),
    "building": ("a building", "an architectural structure", "a constructed facade"),
    "food": ("food", "a prepared dish", "something to eat"),
    "car": ("a car", "a road vehicle", "an automobile"),
    "sign": ("a sign", "a signboard with text", "a posted travel sign"),
    "lantern": ("a lantern", "decorative hanging lanterns", "a traditional light fixture"),
    "fountain": ("a fountain", "a water fountain", "decorative spraying water"),
    "horse": ("a horse", "people with horses", "an equestrian animal"),
    "stage": ("a performance stage", "a theatrical stage", "a live show platform"),
}


@dataclass(frozen=True)
class LabelScore:
    label: str
    score: float


@dataclass(frozen=True)
class FramePrediction:
    field: str
    scores: list[LabelScore]
    top_margin: float
    source: str


@dataclass(frozen=True)
class DeviceResolution:
    requested: str
    actual: str
    fallback_reason: str | None = None


def top_margin(scores: Sequence[LabelScore]) -> float:
    if len(scores) < 2:
        return 0.0
    ordered = sorted(scores, key=lambda row: row.score, reverse=True)
    return ordered[0].score - ordered[1].score


def embedding_tensor(output: object) -> torch.Tensor:
    """Normalize Transformers embedding API variants to their pooled tensor."""

    if isinstance(output, torch.Tensor):
        return output
    pooled = getattr(output, "pooler_output", None)
    if isinstance(pooled, torch.Tensor):
        return pooled
    raise TypeError(f"unsupported embedding output: {type(output).__name__}")


def resolve_device(requested: str) -> DeviceResolution:
    if requested == "cpu":
        return DeviceResolution(requested, "cpu")
    if requested == "mps":
        if not torch.backends.mps.is_available():
            raise RuntimeError("MPS was requested but is unavailable")
        return DeviceResolution(requested, "mps")
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable")
        return DeviceResolution(requested, "cuda")
    if requested != "auto":
        raise ValueError(f"unsupported device request: {requested}")
    if torch.backends.mps.is_available():
        return DeviceResolution(requested, "mps")
    if torch.cuda.is_available():
        return DeviceResolution(requested, "cuda", "mps_unavailable")
    return DeviceResolution(requested, "cpu", "mps_unavailable")


class SiglipEvidenceEncoder:
    def __init__(self, model: object, processor: object, model_id: str, device: DeviceResolution):
        self._model = model
        self._processor = processor
        self.model_id = model_id
        self.device = device
        self.resolved_revision = getattr(model.config, "_commit_hash", None)
        self._text_cache: dict[tuple[tuple[str, tuple[str, ...]], ...], tuple[list[str], torch.Tensor]] = {}

    @classmethod
    def load(
        cls,
        model_id: str,
        cache_dir: Path,
        requested_device: str,
        revision: str = DEFAULT_SIGLIP2_REVISION,
        local_files_only: bool = False,
    ) -> "SiglipEvidenceEncoder":
        from transformers import AutoModel, AutoProcessor

        resolved = resolve_device(requested_device)
        cache_dir.mkdir(parents=True, exist_ok=True)
        processor = AutoProcessor.from_pretrained(
            model_id,
            cache_dir=cache_dir,
            revision=revision,
            local_files_only=local_files_only,
        )
        model = AutoModel.from_pretrained(
            model_id,
            cache_dir=cache_dir,
            revision=revision,
            local_files_only=local_files_only,
        )
        model.eval().to(resolved.actual)
        return cls(model, processor, model_id, resolved)

    def _text_features(self, prompt_groups: Mapping[str, Sequence[str]]) -> tuple[list[str], torch.Tensor]:
        cache_key = tuple((label, tuple(prompt_groups[label])) for label in prompt_groups)
        if cache_key in self._text_cache:
            return self._text_cache[cache_key]
        labels = list(prompt_groups)
        phrases = [phrase for label in labels for phrase in prompt_groups[label]]
        counts = [len(prompt_groups[label]) for label in labels]
        inputs = self._processor(
            text=phrases,
            padding="max_length",
            truncation=True,
            max_length=64,
            return_tensors="pt",
        )
        inputs = {key: value.to(self.device.actual) for key, value in inputs.items()}
        with torch.inference_mode():
            features = embedding_tensor(self._model.get_text_features(**inputs))
        features = functional.normalize(features.float(), dim=-1)
        ensembles: list[torch.Tensor] = []
        offset = 0
        for count in counts:
            ensemble = features[offset : offset + count].mean(dim=0)
            ensembles.append(functional.normalize(ensemble, dim=0))
            offset += count
        result = labels, torch.stack(ensembles)
        self._text_cache[cache_key] = result
        return result

    def _encode_images(self, images: Sequence[object], batch_size: int = 4) -> torch.Tensor:
        batches: list[torch.Tensor] = []
        for offset in range(0, len(images), batch_size):
            batch = list(images[offset : offset + batch_size])
            inputs = self._processor(images=batch, return_tensors="pt")
            pixel_values = inputs["pixel_values"].to(self.device.actual)
            pixel_attention_mask = inputs.get("pixel_attention_mask")
            if pixel_attention_mask is not None:
                pixel_attention_mask = pixel_attention_mask.to(self.device.actual)
            with torch.inference_mode():
                kwargs = {"pixel_values": pixel_values}
                if pixel_attention_mask is not None:
                    kwargs["pixel_attention_mask"] = pixel_attention_mask
                features = embedding_tensor(self._model.get_image_features(**kwargs))
            batches.append(functional.normalize(features.float(), dim=-1))
        if not batches:
            return torch.empty((0, 0), device=self.device.actual)
        return torch.cat(batches, dim=0)

    def _classify_features(
        self,
        image_features: torch.Tensor,
        prompt_groups: Mapping[str, Sequence[str]],
        field: str,
    ) -> list[FramePrediction]:
        labels, text_features = self._text_features(prompt_groups)
        similarities = image_features @ text_features.T
        predictions: list[FramePrediction] = []
        for row in similarities.detach().cpu().tolist():
            scores = sorted(
                [LabelScore(label, float(score)) for label, score in zip(labels, row, strict=True)],
                key=lambda item: item.score,
                reverse=True,
            )
            predictions.append(
                FramePrediction(
                    field=field,
                    scores=scores,
                    top_margin=top_margin(scores),
                    source=f"{self.model_id}@{self.resolved_revision or 'unknown'}:prompts-{PROMPT_SET_VERSION}",
                )
            )
        return predictions

    def classify(
        self,
        images: Sequence[object],
        prompt_groups: Mapping[str, Sequence[str]],
        field: str,
    ) -> list[FramePrediction]:
        return self._classify_features(self._encode_images(images), prompt_groups, field)

    def classify_many(
        self,
        images: Sequence[object],
        field_groups: Mapping[str, Mapping[str, Sequence[str]]],
    ) -> dict[str, list[FramePrediction]]:
        image_features = self._encode_images(images)
        return {
            field: self._classify_features(image_features, prompts, field)
            for field, prompts in field_groups.items()
        }
