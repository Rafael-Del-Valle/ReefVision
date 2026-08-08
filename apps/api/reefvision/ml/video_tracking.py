"""Provider-neutral detector-plus-tracker video inference."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

from reefvision.domain.errors import ValidationError


@dataclass(frozen=True)
class TrackObservation:
    frame: int
    provider_track_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]


class VideoTrackingProvider(Protocol):
    provider_id: str

    @property
    def provider_version(self) -> str: ...

    def track(
        self,
        checkpoint_path: Path,
        video_path: Path,
        *,
        tracker: str,
        confidence: float,
        iou: float,
        device: str,
    ) -> list[TrackObservation]: ...


class UltralyticsVideoTrackingProvider:
    provider_id = "ultralytics"

    def __init__(self) -> None:
        try:
            self._ultralytics = cast(Any, import_module("ultralytics"))
        except ImportError as exc:
            raise ValidationError("Ultralytics is not installed") from exc

    @property
    def provider_version(self) -> str:
        return str(vars(self._ultralytics).get("__version__", "unknown"))

    @staticmethod
    def _device(device: str) -> str | int:
        normalized = device.strip().casefold()
        if normalized in {"", "auto"}:
            try:
                torch = cast(Any, import_module("torch"))
                return 0 if bool(torch.cuda.is_available()) else "cpu"
            except ImportError:
                return "cpu"
        if normalized.isdigit():
            return int(normalized)
        return normalized

    def track(
        self,
        checkpoint_path: Path,
        video_path: Path,
        *,
        tracker: str,
        confidence: float,
        iou: float,
        device: str,
    ) -> list[TrackObservation]:
        if not checkpoint_path.is_file():
            raise ValidationError("Tracking checkpoint is missing")
        if not video_path.is_file():
            raise ValidationError("Tracking source video is missing")
        model = self._ultralytics.YOLO(str(checkpoint_path))
        stream = model.track(
            source=str(video_path),
            stream=True,
            persist=True,
            tracker=tracker,
            conf=confidence,
            iou=iou,
            device=self._device(device),
            verbose=False,
        )
        observations: list[TrackObservation] = []
        for frame_index, result in enumerate(stream):
            boxes = getattr(result, "boxes", None)
            if boxes is None or getattr(boxes, "id", None) is None:
                continue
            ids = boxes.id.int().cpu().tolist()
            classes = boxes.cls.int().cpu().tolist()
            confidences = boxes.conf.cpu().tolist()
            coordinates = boxes.xywh.cpu().tolist()
            names = dict(getattr(result, "names", {}))
            for track_id, class_index, score, xywh in zip(
                ids,
                classes,
                confidences,
                coordinates,
                strict=False,
            ):
                center_x, center_y, width, height = (float(value) for value in xywh)
                observations.append(
                    TrackObservation(
                        frame=frame_index,
                        provider_track_id=int(track_id),
                        class_name=str(names.get(int(class_index), class_index)),
                        confidence=float(score),
                        bbox=(center_x - width / 2.0, center_y - height / 2.0, width, height),
                    )
                )
        return observations


def video_tracking_provider_for_name(provider_id: str) -> VideoTrackingProvider:
    normalized = provider_id.strip().casefold()
    if normalized == "ultralytics":
        return UltralyticsVideoTrackingProvider()
    raise ValidationError(f"Unsupported video tracking provider: {provider_id}")
