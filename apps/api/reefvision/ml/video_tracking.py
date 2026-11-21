"""Provider-neutral detector-plus-tracker video inference."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib import import_module
from math import isfinite
from pathlib import Path
from typing import Any, Protocol, cast

from reefvision.domain.errors import ValidationError
from reefvision.ml.sleap_nn_provider import SLEAP_NN_RETIREMENT_REASON

POSE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION = "pose-provider-uncertainty-0001"


def _optional_uncertainty_score(
    value: float | None,
    *,
    name: str,
) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValidationError(f"{name} must be a finite value between 0 and 1")
    return number


def build_pose_uncertainty_evidence(
    *,
    provider_id: str,
    provider_version: str,
    keypoints: tuple[tuple[float, float, float], ...],
    heatmap_entropy: float | None = None,
    paf_ambiguity: float | None = None,
) -> dict[str, Any]:
    """Build explicit provider evidence without inventing unsupported signals."""

    normalized_confidences = [
        min(max(float(point[2]), 0.0), 1.0)
        for point in keypoints
        if len(point) >= 3 and isfinite(float(point[2]))
    ]

    mean_confidence = (
        sum(normalized_confidences) / len(normalized_confidences)
        if normalized_confidences
        else None
    )
    minimum_confidence = min(normalized_confidences) if normalized_confidences else None

    validated_heatmap = _optional_uncertainty_score(
        heatmap_entropy,
        name="heatmap_entropy",
    )
    validated_paf = _optional_uncertainty_score(
        paf_ambiguity,
        name="paf_ambiguity",
    )

    capabilities = {
        "keypoint_confidence": bool(normalized_confidences),
        "heatmap_entropy": validated_heatmap is not None,
        "paf_ambiguity": validated_paf is not None,
    }

    available_signals = [key for key, available in capabilities.items() if available]

    return {
        "schema_version": POSE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION,
        "provider_id": provider_id,
        "provider_version": provider_version,
        "capabilities": capabilities,
        "available_signals": available_signals,
        "mean_keypoint_confidence": mean_confidence,
        "minimum_keypoint_confidence": minimum_confidence,
        "heatmap_entropy": validated_heatmap,
        "paf_ambiguity": validated_paf,
    }


@dataclass(frozen=True)
class TrackObservation:
    frame: int
    provider_track_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]
    keypoints: tuple[tuple[float, float, float], ...] | None = None
    pose_uncertainty: dict[str, Any] | None = None
    # Zero or more source-pixel polygons for an instance segmentation result.
    mask_polygons: tuple[tuple[tuple[float, float], ...], ...] | None = None
    timestamp_seconds: float | None = None


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

    def resolve_tracker_name(
        self,
        requested: str,
        *,
        link_detections: bool,
    ) -> str: ...

    def track(
        self,
        checkpoint_path: Path,
        video_path: Path,
        *,
        tracker: str,
        confidence: float,
        iou: float,
        device: str,
        link_detections: bool = True,
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

    def resolve_tracker_name(
        self,
        requested: str,
        *,
        link_detections: bool,
    ) -> str:
        return requested if link_detections else "instances-only"

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
        link_detections: bool = True,
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

        if link_detections:
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
        else:
            stream = model.predict(
                source=str(video_path),
                stream=True,
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
                keypoints = getattr(result, "keypoints", None)
                raw_masks = getattr(getattr(result, "masks", None), "xy", None)
                mask_rows: list[tuple[tuple[tuple[float, float], ...], ...] | None] = []
                for polygon in list(raw_masks or [])[: len(classes)]:
                    mask_points = tuple(
                        (float(point[0]), float(point[1]))
                        for point in polygon
                        if len(point) >= 2
                        and isfinite(float(point[0]))
                        and isfinite(float(point[1]))
                        and float(point[0]) >= 0
                        and float(point[1]) >= 0
                    )
                    mask_rows.append((mask_points,) if len(mask_points) >= 3 else None)
                mask_rows.extend([None] * max(0, len(classes) - len(mask_rows)))
                keypoint_data = getattr(keypoints, "data", None)
                if keypoint_data is None:
                    keypoint_rows: list[list[list[float]] | None] = [None] * len(classes)
                else:
                    keypoint_rows = keypoint_data.cpu().tolist()

                if link_detections:
                    if getattr(boxes, "id", None) is None:
                        ids: list[int] = []
                    else:
                        ids = boxes.id.int().cpu().tolist()
                else:
                    ids = list(range(next_instance_id, next_instance_id + len(classes)))
                    next_instance_id += len(classes)

                tracked_observations_seen += len(ids)
                unique_track_ids.update(int(track_id) for track_id in ids)

                # Ultralytics may return no track IDs on early frames; masks
                # must align to detection rows rather than shortened IDs.
                for row_index, (track_id, class_index, score, xywh, raw_keypoints) in enumerate(
                    zip(
                        ids,
                        classes,
                        confidences,
                        coordinates,
                        keypoint_rows,
                        strict=False,
                    )
                ):
                    center_x, center_y, width, height = (float(value) for value in xywh)
                    normalized_keypoints: tuple[tuple[float, float, float], ...] | None = None
                    if raw_keypoints is not None:
                        pose_points: list[tuple[float, float, float]] = []
                        for point in raw_keypoints:
                            if len(point) < 2:
                                continue
                            point_confidence = float(point[2]) if len(point) >= 3 else 1.0
                            pose_points.append(
                                (
                                    float(point[0]),
                                    float(point[1]),
                                    point_confidence,
                                )
                            )
                        normalized_keypoints = tuple(pose_points)

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
                            keypoints=normalized_keypoints,
                            mask_polygons=mask_rows[row_index],
                            pose_uncertainty=(
                                build_pose_uncertainty_evidence(
                                    provider_id=self.provider_id,
                                    provider_version=self.provider_version,
                                    keypoints=normalized_keypoints,
                                )
                                if normalized_keypoints is not None
                                else None
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


class ReefPoseVideoTrackingProvider:
    """Stream a native single-animal ReefPose checkpoint over a video."""

    provider_id = "reefpose"

    @property
    def provider_version(self) -> str:
        from reefvision.ml.reefpose.constants import REEFPOSE_PROVIDER_VERSION

        return REEFPOSE_PROVIDER_VERSION

    def resolve_tracker_name(
        self,
        requested: str,
        *,
        link_detections: bool,
    ) -> str:
        del requested
        return "reefpose:single-animal" if link_detections else "instances-only"

    def track(
        self,
        checkpoint_path: Path,
        video_path: Path,
        *,
        tracker: str,
        confidence: float,
        iou: float,
        device: str,
        link_detections: bool = True,
        on_progress: VideoTrackingProgressCallback | None = None,
        should_cancel: VideoTrackingCancellationCheck | None = None,
    ) -> list[TrackObservation]:
        del tracker, iou
        if not checkpoint_path.is_file():
            raise ValidationError("ReefPose tracking checkpoint is missing")
        if not video_path.is_file():
            raise ValidationError("Tracking source video is missing")
        if should_cancel is not None and should_cancel():
            raise VideoTrackingCancelled("Video tracking cancelled before inference")

        try:
            cv2 = cast(Any, import_module("cv2"))
            image_module = import_module("PIL.Image")
            from reefvision.ml.reefpose.checkpoints import load_checkpoint
            from reefvision.ml.reefpose.errors import ReefPoseError
            from reefvision.ml.reefpose.inference import ReefPosePredictor
        except ImportError as exc:
            raise ValidationError("ReefPose video inference dependencies are unavailable") from exc

        if on_progress is not None:
            on_progress(VideoTrackingProgress(0, 0, 0, 0, stage="loading_model"))

        try:
            checkpoint = load_checkpoint(checkpoint_path, device="cpu")
            predictor = ReefPosePredictor(checkpoint.model, checkpoint.schema, device=device)
        except ReefPoseError as exc:
            raise ValidationError(f"ReefPose checkpoint is invalid: {exc}") from exc

        class_name = str(checkpoint.training_config.get("class_label") or "animal").strip()
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            capture.release()
            raise ValidationError("Tracking source video could not be opened")

        observations: list[TrackObservation] = []
        detections_seen = 0
        unique_track_ids: set[int] = set()
        frame_index = 0
        previous_timestamp = -1.0
        try:
            has_presentation_times = capture.getBackendName() == "FFMPEG"
            while True:
                if should_cancel is not None and should_cancel():
                    raise VideoTrackingCancelled(
                        f"Video tracking cancelled before frame {frame_index}"
                    )
                ok, frame = capture.read()
                if not ok or frame is None:
                    break

                timestamp_seconds = None
                if has_presentation_times:
                    # The FFmpeg millisecond clock retains the stream time base for VFR media.
                    timestamp = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000
                    has_presentation_times = (
                        isfinite(timestamp) and timestamp >= 0 and timestamp > previous_timestamp
                    )
                    if has_presentation_times:
                        timestamp_seconds = previous_timestamp = timestamp
                source = image_module.fromarray(frame[:, :, ::-1].copy(), mode="RGB")
                try:
                    pose = predictor.predict(source, confidence_threshold=confidence)
                except ReefPoseError as exc:
                    raise ValidationError(f"ReefPose video inference failed: {exc}") from exc

                if pose.bbox is not None:
                    x_min, y_min, x_max, y_max = pose.bbox
                    provider_track_id = 1 if link_detections else frame_index + 1
                    keypoints = tuple(
                        (
                            float(item.x),
                            float(item.y),
                            float(item.confidence) if item.visibility_state == "visible" else 0.0,
                        )
                        for item in pose.landmarks
                    )
                    detections_seen += 1
                    unique_track_ids.add(provider_track_id)
                    observations.append(
                        TrackObservation(
                            frame=frame_index,
                            provider_track_id=provider_track_id,
                            class_name=class_name,
                            confidence=float(pose.confidence),
                            bbox=(
                                float(x_min),
                                float(y_min),
                                float(x_max - x_min),
                                float(y_max - y_min),
                            ),
                            keypoints=keypoints,
                            timestamp_seconds=timestamp_seconds,
                            pose_uncertainty=build_pose_uncertainty_evidence(
                                provider_id=self.provider_id,
                                provider_version=self.provider_version,
                                keypoints=keypoints,
                            ),
                        )
                    )

                frame_index += 1
                if on_progress is not None:
                    on_progress(
                        VideoTrackingProgress(
                            frames_processed=frame_index,
                            detections_seen=detections_seen,
                            tracked_observations_seen=len(observations),
                            unique_tracks_seen=len(unique_track_ids),
                        )
                    )
        finally:
            capture.release()

        if frame_index == 0:
            raise ValidationError("Tracking source video contains no decodable frames")
        if not has_presentation_times and previous_timestamp >= 0:
            # A nonmonotonic decoder clock supplies no reliable presentation evidence.
            return [replace(item, timestamp_seconds=None) for item in observations]
        return observations


def video_tracking_provider_for_name(provider_id: str) -> VideoTrackingProvider:
    normalized = provider_id.strip().casefold()
    if normalized == "ultralytics":
        return UltralyticsVideoTrackingProvider()
    if normalized == "sleap_nn":
        raise ValidationError(SLEAP_NN_RETIREMENT_REASON)
    if normalized == "reefpose":
        return ReefPoseVideoTrackingProvider()
    raise ValidationError(f"Unsupported video tracking provider: {provider_id}")
