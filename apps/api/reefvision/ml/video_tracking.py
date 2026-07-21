"""Framework-isolated detector-to-tracker adapters for managed videos."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import configure_provider_runtime, require_provider_ready
from reefvision.ml.providers import resolve_torch_device


@dataclass(frozen=True, slots=True)
class TrackedDetection:
    tracker_id: int
    class_index: int
    label: str
    confidence: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True, slots=True)
class TrackedFrame:
    frame_index: int
    detections: tuple[TrackedDetection, ...]


class VideoTrackingAdapter(Protocol):
    provider_name: str
    provider_version: str

    def track(
        self,
        *,
        model_path: Path,
        video_path: Path,
        tracker_config_path: Path,
        confidence_threshold: float,
        iou_threshold: float,
        requested_device: str,
        every_n_frames: int,
    ) -> tuple[Iterator[TrackedFrame], str]: ...

    def unload(self) -> None: ...


class UltralyticsVideoTrackingAdapter:
    provider_name = "ultralytics"

    def __init__(self, provider_version: str) -> None:
        self.provider_version = provider_version
        self._model: Any | None = None

    def track(
        self,
        *,
        model_path: Path,
        video_path: Path,
        tracker_config_path: Path,
        confidence_threshold: float,
        iou_threshold: float,
        requested_device: str,
        every_n_frames: int,
    ) -> tuple[Iterator[TrackedFrame], str]:
        configure_provider_runtime()
        require_provider_ready(self.provider_name)
        try:
            from ultralytics import YOLO  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - environment-specific dependency failure
            raise ValidationError(f"Ultralytics tracking is unavailable: {exc}") from exc
        resolved_device = resolve_torch_device(requested_device)
        resolved_name = (
            f"cuda:{resolved_device}" if isinstance(resolved_device, int) else str(resolved_device)
        )
        model = YOLO(str(model_path))
        if str(getattr(model, "task", "") or "") != "detect":
            raise ValidationError("The registered video model is not an object detector")
        self._model = model
        results = model.track(
            source=str(video_path),
            stream=True,
            persist=True,
            tracker=str(tracker_config_path),
            conf=confidence_threshold,
            iou=iou_threshold,
            device=resolved_device,
            vid_stride=every_n_frames,
            verbose=False,
        )

        def frames() -> Iterator[TrackedFrame]:
            for result_index, result in enumerate(results):
                detections: list[TrackedDetection] = []
                boxes = getattr(result, "boxes", None)
                if boxes is not None and boxes.id is not None:
                    xyxy = boxes.xyxy.tolist()
                    track_ids = boxes.id.int().tolist()
                    confidences = boxes.conf.tolist()
                    classes = boxes.cls.int().tolist()
                    names = getattr(result, "names", None) or getattr(model, "names", None) or {}
                    for index, raw_track_id in enumerate(track_ids):
                        class_index = int(classes[index])
                        label = (
                            str(names.get(class_index, class_index))
                            if isinstance(names, dict)
                            else str(names[class_index])
                            if class_index < len(names)
                            else str(class_index)
                        )
                        coords = xyxy[index]
                        detections.append(
                            TrackedDetection(
                                tracker_id=int(raw_track_id),
                                class_index=class_index,
                                label=label,
                                confidence=float(confidences[index]),
                                x_min=float(coords[0]),
                                y_min=float(coords[1]),
                                x_max=float(coords[2]),
                                y_max=float(coords[3]),
                            )
                        )
                yield TrackedFrame(
                    frame_index=result_index * every_n_frames,
                    detections=tuple(detections),
                )

        return frames(), resolved_name

    def unload(self) -> None:
        self._model = None
        try:  # pragma: no cover - depends on CUDA availability
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return


def build_video_tracking_adapter(
    provider_name: str,
    provider_version: str,
) -> VideoTrackingAdapter:
    if provider_name == "ultralytics":
        return UltralyticsVideoTrackingAdapter(provider_version)
    raise ValidationError(f"Provider {provider_name!r} does not support managed video tracking")
