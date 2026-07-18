"""Provider-neutral contracts for optional advanced vision adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PromptBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True, slots=True)
class PromptPoint:
    x: float
    y: float
    positive: bool = True


@dataclass(frozen=True, slots=True)
class PromptDetection:
    label: str
    confidence: float
    box: PromptBox
    phrase: str | None = None


@dataclass(frozen=True, slots=True)
class PromptMask:
    confidence: float
    polygon: tuple[tuple[float, float], ...]
    label: str | None = None


@dataclass(frozen=True, slots=True)
class DepthPrediction:
    width: int
    height: int
    relative_depth_path: Path
    preview_path: Path | None
    minimum_value: float
    maximum_value: float


@dataclass(frozen=True, slots=True)
class VideoMaskFrame:
    frame_index: int
    object_id: str
    polygon: tuple[tuple[float, float], ...]
    confidence: float | None = None


@runtime_checkable
class TextPromptDetectionProvider(Protocol):
    provider_id: str
    provider_version: str

    def detect(
        self,
        model_path: Path,
        image_path: Path,
        *,
        prompts: list[str],
        confidence: float,
        device: str,
    ) -> list[PromptDetection]: ...


@runtime_checkable
class ImagePromptSegmentationProvider(Protocol):
    provider_id: str
    provider_version: str

    def segment(
        self,
        model_path: Path,
        image_path: Path,
        *,
        boxes: list[PromptBox],
        points: list[PromptPoint],
        device: str,
    ) -> list[PromptMask]: ...


@runtime_checkable
class VideoPropagationProvider(Protocol):
    provider_id: str
    provider_version: str

    def propagate(
        self,
        model_path: Path,
        video_path: Path,
        *,
        seed_frame: int,
        seed_masks: dict[str, PromptMask],
        device: str,
    ) -> list[VideoMaskFrame]: ...


@runtime_checkable
class MonocularDepthProvider(Protocol):
    provider_id: str
    provider_version: str

    def predict_depth(
        self,
        model_path: Path,
        image_path: Path,
        output_path: Path,
        *,
        device: str,
    ) -> DepthPrediction: ...
