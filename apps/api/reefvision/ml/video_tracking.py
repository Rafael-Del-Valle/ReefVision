"""Provider-neutral detector-plus-tracker video inference."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from math import isfinite
from pathlib import Path
from typing import Any, Protocol, cast

from reefvision.domain.errors import ValidationError
from reefvision.ml.sleap_nn_provider import (
    SLEAP_NN_SUPPORTED_VERSION,
    extract_sleap_nn_bundle,
    keypoint_bbox,
    normalize_sleap_keypoints,
    sleap_predictor_types,
)

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


class SleapNNVideoTrackingProvider:
    provider_id = "sleap_nn"

    @property
    def provider_version(self) -> str:
        return SLEAP_NN_SUPPORTED_VERSION

    def resolve_tracker_name(
        self,
        requested: str,
        *,
        link_detections: bool,
    ) -> str:
        del requested
        return "sleap_nn:fixed_window:oks:hungarian" if link_detections else "instances-only"

    @staticmethod
    def _cuda_available() -> bool:
        try:
            torch = cast(Any, import_module("torch"))
        except ImportError:
            return False
        return bool(torch.cuda.is_available())

    @staticmethod
    def _device(device: str) -> str:
        normalized = device.strip().casefold()
        if normalized in {"", "auto"}:
            return "cuda" if SleapNNVideoTrackingProvider._cuda_available() else "cpu"
        if normalized == "cpu":
            return "cpu"

        if normalized == "gpu":
            normalized = "cuda"
        elif normalized.isdigit():
            normalized = f"cuda:{int(normalized)}"
        elif normalized.startswith("cuda:"):
            device_index = normalized.removeprefix("cuda:")
            if not device_index.isdigit():
                raise ValidationError(
                    "SLEAP-NN CUDA device must use cuda:N with a numeric device index"
                )
            normalized = f"cuda:{int(device_index)}"
        elif normalized != "cuda":
            raise ValidationError(
                "SLEAP-NN supports auto, cpu, cuda, cuda:N, or numeric CUDA devices"
            )

        if not SleapNNVideoTrackingProvider._cuda_available():
            raise ValidationError("SLEAP-NN CUDA device was requested but CUDA is not available")
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
        del tracker, iou
        if not checkpoint_path.is_file():
            raise ValidationError("SLEAP-NN pose bundle is missing")
        if not video_path.is_file():
            raise ValidationError("Tracking source video is missing")
        if should_cancel is not None and should_cancel():
            raise VideoTrackingCancelled("Video tracking cancelled before inference")

        if on_progress is not None:
            on_progress(
                VideoTrackingProgress(
                    frames_processed=0,
                    detections_seen=0,
                    tracked_observations_seen=0,
                    unique_tracks_seen=0,
                    stage="loading_model",
                )
            )

        manifest, model_paths = extract_sleap_nn_bundle(checkpoint_path)
        Predictor, TrackerConfig = sleap_predictor_types()
        tracker_config = (
            TrackerConfig(
                window_size=5,
                candidates_method="fixed_window",
                features="keypoints",
                scoring_method="oks",
                track_matching_method="hungarian",
            )
            if link_detections and manifest.instance_mode == "multi"
            else None
        )
        predictor = Predictor.from_model_paths(
            [str(path) for path in model_paths],
            device=self._device(device),
            peak_threshold=confidence,
            tracker_config=tracker_config,
        )

        if on_progress is not None:
            on_progress(
                VideoTrackingProgress(
                    frames_processed=0,
                    detections_seen=0,
                    tracked_observations_seen=0,
                    unique_tracks_seen=0,
                    stage="starting_stream",
                )
            )

        labels = predictor.predict(str(video_path))
        if should_cancel is not None and should_cancel():
            raise VideoTrackingCancelled("Video tracking cancelled after SLEAP-NN inference")

        observations: list[TrackObservation] = []
        track_ids: dict[str, int] = {}
        next_track_id = 1
        detections_seen = 0
        unique_track_ids: set[int] = set()
        labeled_frames = list(getattr(labels, "labeled_frames", []))

        for fallback_frame, labeled_frame in enumerate(labeled_frames):
            if should_cancel is not None and should_cancel():
                raise VideoTrackingCancelled(
                    f"Video tracking cancelled while reading frame {fallback_frame}"
                )
            frame_index = int(
                getattr(
                    labeled_frame,
                    "frame_idx",
                    getattr(labeled_frame, "frame_index", fallback_frame),
                )
            )
            instances = list(getattr(labeled_frame, "instances", []))
            detections_seen += len(instances)

            for instance_index, instance in enumerate(instances):
                raw_points = instance.numpy(scores=True)
                keypoints = normalize_sleap_keypoints(raw_points)
                if len(keypoints) != len(manifest.landmark_labels):
                    raise ValidationError(
                        "SLEAP-NN prediction landmark count does not match "
                        "the registered bundle landmark_labels"
                    )
                bbox = keypoint_bbox(keypoints)
                if bbox is None:
                    continue

                if manifest.instance_mode == "single":
                    provider_track_id = 1
                elif link_detections:
                    provider_track = getattr(instance, "track", None)
                    if provider_track is None:
                        track_key = f"untracked:{frame_index}:{instance_index}"
                    else:
                        track_key = str(
                            getattr(provider_track, "name", None)
                            or getattr(provider_track, "id", None)
                            or repr(provider_track)
                        )
                    if track_key not in track_ids:
                        track_ids[track_key] = next_track_id
                        next_track_id += 1
                    provider_track_id = track_ids[track_key]
                else:
                    provider_track_id = next_track_id
                    next_track_id += 1

                score = float(getattr(instance, "score", 0.0) or 0.0)
                if not 0.0 <= score <= 1.0:
                    visible_scores = [point[2] for point in keypoints if point[2] > 0]
                    score = sum(visible_scores) / len(visible_scores) if visible_scores else 0.0

                unique_track_ids.add(provider_track_id)
                observations.append(
                    TrackObservation(
                        frame=frame_index,
                        provider_track_id=provider_track_id,
                        class_name=manifest.class_name,
                        confidence=score,
                        bbox=bbox,
                        keypoints=keypoints,
                        pose_uncertainty=build_pose_uncertainty_evidence(
                            provider_id=self.provider_id,
                            provider_version=self.provider_version,
                            keypoints=keypoints,
                        ),
                    )
                )

            if on_progress is not None:
                on_progress(
                    VideoTrackingProgress(
                        frames_processed=fallback_frame + 1,
                        detections_seen=detections_seen,
                        tracked_observations_seen=len(observations),
                        unique_tracks_seen=len(unique_track_ids),
                    )
                )

        return observations


def video_tracking_provider_for_name(provider_id: str) -> VideoTrackingProvider:
    normalized = provider_id.strip().casefold()
    if normalized == "ultralytics":
        return UltralyticsVideoTrackingProvider()
    if normalized == "sleap_nn":
        return SleapNNVideoTrackingProvider()
    raise ValidationError(f"Unsupported video tracking provider: {provider_id}")
