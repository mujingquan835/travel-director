"""Local lightweight object-detection evidence and aggregation."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence, TYPE_CHECKING

from pydantic import Field

from scanner.schema import StrictModel

if TYPE_CHECKING:
    from PIL import Image


@dataclass(frozen=True)
class Detection:
    label: str
    score: float
    box_xyxy: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("detection score must be between 0 and 1")
        if len(self.box_xyxy) != 4:
            raise ValueError("box_xyxy must contain four coordinates")


class DetectionSummary(StrictModel):
    people_present: bool
    people_counts: list[int]
    people_count_max: int = Field(ge=0)
    main_objects: list[str]
    object_frame_support: dict[str, int]
    object_max_scores: dict[str, float]


class Detector(Protocol):
    def detect(self, images: Sequence["Image.Image"]) -> list[list[Detection]]:
        """Return detections in original image coordinates for every input frame."""


def filter_detections(rows: Sequence[Detection], score_threshold: float) -> list[Detection]:
    if not 0.0 <= score_threshold <= 1.0:
        raise ValueError("score_threshold must be between 0 and 1")
    return [row for row in rows if row.score >= score_threshold]


def summarize_detections(per_frame: Sequence[Sequence[Detection]]) -> DetectionSummary:
    people_counts = [sum(row.label == "person" for row in frame) for frame in per_frame]
    frame_support: Counter[str] = Counter()
    max_scores: dict[str, float] = defaultdict(float)
    for frame in per_frame:
        for label in {row.label for row in frame}:
            frame_support[label] += 1
        for row in frame:
            max_scores[row.label] = max(max_scores[row.label], row.score)

    labels = sorted(
        frame_support,
        key=lambda label: (-frame_support[label], -max_scores[label], label),
    )
    people_count_max = max(people_counts, default=0)
    return DetectionSummary(
        people_present=people_count_max > 0,
        people_counts=people_counts,
        people_count_max=people_count_max,
        main_objects=labels,
        object_frame_support=dict(frame_support),
        object_max_scores=dict(max_scores),
    )


class TorchvisionSSDLiteDetector:
    """Batch-size-one adapter for Torchvision SSDLite MobileNet V3 Large."""

    model_id = "torchvision/ssdlite320_mobilenet_v3_large"

    def __init__(self, model: object, categories: Sequence[str], score_threshold: float, device: str):
        self._model = model
        self._categories = list(categories)
        self.score_threshold = score_threshold
        self.device = device
        self.weights_id = "unknown"

    @classmethod
    def load(
        cls,
        cache_dir: Path,
        score_threshold: float,
        device: str = "cpu",
    ) -> "TorchvisionSSDLiteDetector":
        if device not in {"cpu", "mps", "cuda"}:
            raise ValueError(f"unsupported detector device: {device}")
        if not 0.0 <= score_threshold <= 1.0:
            raise ValueError("score_threshold must be between 0 and 1")

        import torch
        from torchvision.models.detection import SSDLite320_MobileNet_V3_Large_Weights
        from torchvision.models.detection import ssdlite320_mobilenet_v3_large

        cache_dir.mkdir(parents=True, exist_ok=True)
        torch.hub.set_dir(str(cache_dir.resolve()))
        weights = SSDLite320_MobileNet_V3_Large_Weights.DEFAULT
        model = ssdlite320_mobilenet_v3_large(weights=weights)
        model.eval().to(device)
        detector = cls(model, weights.meta["categories"], score_threshold, device)
        detector.weights_id = str(weights)
        return detector

    def detect(self, images: Sequence["Image.Image"]) -> list[list[Detection]]:
        import torch
        from torchvision.transforms.functional import pil_to_tensor

        output: list[list[Detection]] = []
        with torch.inference_mode():
            for image in images:
                tensor = pil_to_tensor(image.convert("RGB")).float().div(255.0).to(self.device)
                prediction = self._model([tensor])[0]
                rows: list[Detection] = []
                for label_id, score, box in zip(
                    prediction["labels"].detach().cpu().tolist(),
                    prediction["scores"].detach().cpu().tolist(),
                    prediction["boxes"].detach().cpu().tolist(),
                    strict=True,
                ):
                    if score < self.score_threshold:
                        continue
                    label = self._categories[int(label_id)]
                    rows.append(Detection(label, score, tuple(box)))
                output.append(rows)
        return output
