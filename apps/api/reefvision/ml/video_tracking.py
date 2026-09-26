"""Provider-neutral detector-plus-tracker video inference."""

from __future__ import annotations

from collections.abc import Callable
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


@dataclass(frozen=True)
class VideoTrackingProgress:
    frames_processed: int
    detections_seen: int
    tracked_observations_seen: int
    unique_tracks_seen: int
    stage: str = "tracking"


class VideoTrackingCancelled(RuntimeError):
    """Raised when a video-tracking run is cancelled between frames."""


VideoTrackingProgressCallback = Callable[[VideoTrackingProgress], None]
VideoTrackingCancellationCheck = Callable[[], bool]


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
        mode: str,
        confidence: float,
        iou: float,
        device: str,
        on_progress: VideoTrackingProgressCallback | None = None,
        should_cancel: VideoTrackingCancellationCheck | None = None,
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
        mode: str,
        confidence: float,
        iou: float,
        device: str,
        on_progress: VideoTrackingProgressCallback | None = None,
        should_cancel: VideoTrackingCancellationCheck | None = None,
    ) -> list[TrackObservation]:
        if not checkpoint_path.is_file():
            raise ValidationError("Tracking checkpoint is missing")
        if not video_path.is_file():
            raise ValidationError("Tracking source video is missing")
        if should_cancel is not None and should_cancel():
            raise VideoTrackingCancelled("Video tracking cancelled before inference")

        def report_stage(stage: str) -> None:
            if on_progress is not None:
                on_progress(
                    VideoTrackingProgress(
                        frames_processed=0,
                        detections_seen=0,
                        tracked_observations_seen=0,
                        unique_tracks_seen=0,
                        stage=stage,
                    )
                )

        report_stage("loading_model")
        model = self._ultralytics.YOLO(str(checkpoint_path))

        report_stage("model_loaded")
        report_stage("starting_stream")

        normalized_mode = mode.strip().casefold()
        if normalized_mode not in {"track", "detect_only"}:
            raise ValidationError("Video inference mode must be track or detect_only")

        if normalized_mode == "detect_only":
            stream = model.predict(
                source=str(video_path),
                stream=True,
                conf=confidence,
                iou=iou,
                device=self._device(device),
                verbose=False,
            )
        else:
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

        report_stage("waiting_for_first_frame")

        observations: list[TrackObservation] = []
        detections_seen = 0
        tracked_observations_seen = 0
        unique_track_ids: set[int] = set()
        next_instance_id = 1

        for frame_index, result in enumerate(stream):
            if should_cancel is not None and should_cancel():
                raise VideoTrackingCancelled(f"Video tracking cancelled after frame {frame_index}")

            boxes = getattr(result, "boxes", None)
            detection_count = 0 if boxes is None else len(boxes)
            detections_seen += detection_count

            if boxes is not None:
                classes = boxes.cls.int().cpu().tolist()
                confidences = boxes.conf.cpu().tolist()
                coordinates = boxes.xywh.cpu().tolist()
                names = dict(getattr(result, "names", {}))

                if normalized_mode == "detect_only":
                    ids = list(range(next_instance_id, next_instance_id + len(classes)))
                    next_instance_id += len(classes)
                elif getattr(boxes, "id", None) is not None:
                    ids = boxes.id.int().cpu().tolist()
                else:
                    ids = []

                tracked_observations_seen += len(ids)
                unique_track_ids.update(int(track_id) for track_id in ids)

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
                            bbox=(
                                center_x - width / 2.0,
                                center_y - height / 2.0,
                                width,
                                height,
                            ),
                        )
                    )

            if on_progress is not None:
                on_progress(
                    VideoTrackingProgress(
                        frames_processed=frame_index + 1,
                        detections_seen=detections_seen,
                        tracked_observations_seen=tracked_observations_seen,
                        unique_tracks_seen=len(unique_track_ids),
                    )
                )

        return observations


def video_tracking_provider_for_name(provider_id: str) -> VideoTrackingProvider:
    normalized = provider_id.strip().casefold()
    if normalized == "ultralytics":
        return UltralyticsVideoTrackingProvider()
    raise ValidationError(f"Unsupported video tracking provider: {provider_id}")
