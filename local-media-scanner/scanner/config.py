"""Versioned runtime configuration for local scanning."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SamplingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["temporal3", "adaptive5"] = "adaptive5"
    probe_max_edge: int = Field(default=320, ge=64, le=1024)
    thumbnail_max_edge: int = Field(default=720, ge=224, le=2048)
    max_probe_frames: int = Field(default=24, ge=3, le=64)
    max_representative_frames: int = Field(default=5, ge=1, le=8)
    hardware_acceleration: Literal["none", "videotoolbox"] = "none"


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detector_id: str = "torchvision/ssdlite320_mobilenet_v3_large"
    vision_model_id: str = "google/siglip2-base-patch16-224"
    model_cache_dir: Path = Path(".cache/models")
    detector_score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class ScanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1.0"] = "0.1.0"
    device: Literal["auto", "cpu", "mps", "cuda"] = "auto"
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    models: ModelConfig = Field(default_factory=ModelConfig)
    cache_dir: Path = Path(".cache/scanner")
