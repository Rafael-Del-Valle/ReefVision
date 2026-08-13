"""Spatial calibration and group-level fish trajectory analytics."""

from __future__ import annotations

from collections import defaultdict
from math import hypot
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.video_science import (
    CalibratedVideoTrackAnalyticsResponse,
    VideoSchoolingAnalyticsRequest,
    VideoSchoolingAnalyticsResponse,
    VideoSchoolingFrameMetrics,
    VideoSpatialCalibrationResponse,
    VideoSpatialCalibrationSetRequest,
)
from reefvision.services.video_tracks import VideoTrackService

CALIBRATION_METADATA_KEY = "spatial_calibration"
CALIBRATION_SCHEMA_VERSION = "video-spatial-calibration-0001"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _optional_mean(values: list[float]) -> float | None:
    return _mean(values) if values else None


class VideoScienceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.track_service = VideoTrackService(session)

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    @staticmethod
    def _calibration_from_video(video: VideoAsset) -> VideoSpatialCalibrationResponse:
        metadata = dict(video.metadata_json or {})
        raw = metadata.get(CALIBRATION_METADATA_KEY)
        if not isinstance(raw, dict):
            raise NotFoundError("Video spatial calibration has not been set")
        try:
            reference_distance = float(raw["reference_distance"])
            reference_pixels = float(raw["reference_pixels"])
            unit = str(raw["unit"])
            method = str(raw.get("method", "known_length"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Stored video spatial calibration is invalid") from exc
        if reference_distance <= 0 or reference_pixels <= 0:
            raise ValidationError("Stored video spatial calibration must be positive")
        if unit not in {"mm", "cm", "m"}:
            raise ValidationError("Stored video spatial calibration uses an unsupported unit")
        pixels_per_unit = reference_pixels / reference_distance
        return VideoSpatialCalibrationResponse(
            schema_version=CALIBRATION_SCHEMA_VERSION,
            video_id=video.id,
            unit=unit,
            reference_distance=reference_distance,
            reference_pixels=reference_pixels,
            pixels_per_unit=pixels_per_unit,
            units_per_pixel=1.0 / pixels_per_unit,
            method=method,
            reference_label=(
                str(raw["reference_label"])
                if raw.get("reference_label") is not None
                else None
            ),
            notes=str(raw["notes"]) if raw.get("notes") is not None else None,
            video_revision=video.revision,
        )

    def set_calibration(
        self,
        video_id: str,
        payload: VideoSpatialCalibrationSetRequest,
    ) -> VideoSpatialCalibrationResponse:
        video = self._video(video_id)
        metadata: dict[str, Any] = dict(video.metadata_json or {})
        metadata[CALIBRATION_METADATA_KEY] = {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "unit": payload.unit,
            "reference_distance": payload.reference_distance,
            "reference_pixels": payload.reference_pixels,
            "pixels_per_unit": payload.reference_pixels / payload.reference_distance,
            "method": payload.method,
            "reference_label": payload.reference_label,
            "notes": payload.notes,
        }
        video.metadata_json = metadata
        video.revision += 1
        self.session.commit()
        self.session.refresh(video)
        return self._calibration_from_video(video)

    def get_calibration(self, video_id: str) -> VideoSpatialCalibrationResponse:
        return self._calibration_from_video(self._video(video_id))

    def clear_calibration(self, video_id: str) -> None:
        video = self._video(video_id)
        metadata = dict(video.metadata_json or {})
        if CALIBRATION_METADATA_KEY not in metadata:
            return
        metadata.pop(CALIBRATION_METADATA_KEY, None)
        video.metadata_json = metadata
        video.revision += 1
        self.session.commit()

    def calibrated_track_analytics(
        self,
        track_id: str,
    ) -> CalibratedVideoTrackAnalyticsResponse:
        track = self.session.get(VideoTrack, track_id)
        if track is None or track.deleted_at is not None:
            raise NotFoundError("Video track not found")
        calibration = self.get_calibration(track.video_id)
        analytics = self.track_service.analytics(track_id)
        divisor = calibration.pixels_per_unit
        return CalibratedVideoTrackAnalyticsResponse(
            schema_version="calibrated-video-track-analytics-0001",
            track_id=analytics.track_id,
            video_id=analytics.video_id,
            track_number=analytics.track_number,
            label_class_id=analytics.label_class_id,
            first_frame=analytics.first_frame,
            last_frame=analytics.last_frame,
            observed_frame_count=analytics.observed_frame_count,
            duration_seconds=analytics.duration_seconds,
            path_length_pixels=analytics.path_length_pixels,
            mean_speed_pixels_per_second=analytics.mean_speed_pixels_per_second,
            maximum_speed_pixels_per_second=analytics.maximum_speed_pixels_per_second,
            displacement_pixels=analytics.displacement_pixels,
            distance_unit=calibration.unit,
            path_length=analytics.path_length_pixels / divisor,
            mean_speed_per_second=analytics.mean_speed_pixels_per_second / divisor,
            maximum_speed_per_second=(
                analytics.maximum_speed_pixels_per_second / divisor
            ),
            displacement=analytics.displacement_pixels / divisor,
            calibration=calibration,
        )

    def _selected_tracks(self, video_id: str, track_ids: list[str]) -> list[VideoTrack]:
        rows = list(
            self.session.scalars(
                select(VideoTrack).where(
                    VideoTrack.id.in_(track_ids),
                    VideoTrack.video_id == video_id,
                    VideoTrack.deleted_at.is_(None),
                )
            )
        )
        by_id = {track.id: track for track in rows}
        missing = [track_id for track_id in track_ids if track_id not in by_id]
        if missing:
            raise ValidationError(
                "Schooling tracks must be active and belong to the selected video: "
                + ", ".join(missing)
            )
        return [by_id[track_id] for track_id in track_ids]

    @staticmethod
    def _pairwise_distances(points: list[tuple[float, float]]) -> list[float]:
        distances: list[float] = []
        for index, first in enumerate(points):
            for second in points[index + 1 :]:
                distances.append(hypot(first[0] - second[0], first[1] - second[1]))
        return distances

    @staticmethod
    def _nearest_neighbor_distances(points: list[tuple[float, float]]) -> list[float]:
        distances: list[float] = []
        for index, first in enumerate(points):
            candidates = [
                hypot(first[0] - second[0], first[1] - second[1])
                for other_index, second in enumerate(points)
                if other_index != index
            ]
            distances.append(min(candidates))
        return distances

    @staticmethod
    def _polarization(vectors: list[tuple[float, float]]) -> float | None:
        unit_vectors: list[tuple[float, float]] = []
        for dx, dy in vectors:
            magnitude = hypot(dx, dy)
            if magnitude <= 0:
                continue
            unit_vectors.append((dx / magnitude, dy / magnitude))
        if len(unit_vectors) < 2:
            return None
        mean_x = _mean([item[0] for item in unit_vectors])
        mean_y = _mean([item[1] for item in unit_vectors])
        return min(1.0, hypot(mean_x, mean_y))

    def schooling_analytics(
        self,
        video_id: str,
        payload: VideoSchoolingAnalyticsRequest,
    ) -> VideoSchoolingAnalyticsResponse:
        video = self._video(video_id)
        calibration = self.get_calibration(video_id)
        tracks = self._selected_tracks(video_id, payload.track_ids)
        start_frame = payload.start_frame if payload.start_frame is not None else 0
        end_frame = (
            payload.end_frame
            if payload.end_frame is not None
            else max(0, video.frame_count - 1)
        )
        if start_frame >= video.frame_count or end_frame >= video.frame_count:
            raise ValidationError("Schooling frame range cannot exceed the source video")

        centers_by_frame: dict[int, dict[str, tuple[float, float]]] = defaultdict(dict)
        for track in tracks:
            interpolation = self.track_service.interpolate(track.id)
            for item in interpolation.frames:
                if start_frame <= item.frame <= end_frame:
                    centers_by_frame[item.frame][track.id] = (
                        item.center_x,
                        item.center_y,
                    )

        divisor = calibration.pixels_per_unit
        frame_metrics: list[VideoSchoolingFrameMetrics] = []
        previous_centers: dict[str, tuple[float, float]] = {}
        previous_frame: int | None = None

        for frame in range(start_frame, end_frame + 1):
            current = centers_by_frame.get(frame, {})
            if len(current) < 2:
                previous_centers = current
                previous_frame = frame
                continue
            points = list(current.values())
            pairwise = self._pairwise_distances(points)
            nearest = self._nearest_neighbor_distances(points)
            centroid_x = _mean([point[0] for point in points])
            centroid_y = _mean([point[1] for point in points])
            centroid_distances = [
                hypot(point[0] - centroid_x, point[1] - centroid_y) for point in points
            ]

            movement_vectors: list[tuple[float, float]] = []
            speeds_px_per_second: list[float] = []
            if previous_frame is not None and frame == previous_frame + 1:
                for track_id, center in current.items():
                    previous = previous_centers.get(track_id)
                    if previous is None:
                        continue
                    dx = center[0] - previous[0]
                    dy = center[1] - previous[1]
                    movement_vectors.append((dx, dy))
                    speeds_px_per_second.append(hypot(dx, dy) * video.fps)

            mean_speed_px = _optional_mean(speeds_px_per_second)
            frame_metrics.append(
                VideoSchoolingFrameMetrics(
                    frame=frame,
                    timestamp_seconds=frame / video.fps,
                    active_track_count=len(current),
                    mean_pairwise_distance_pixels=_mean(pairwise),
                    mean_nearest_neighbor_distance_pixels=_mean(nearest),
                    mean_distance_to_centroid_pixels=_mean(centroid_distances),
                    mean_pairwise_distance=_mean(pairwise) / divisor,
                    mean_nearest_neighbor_distance=_mean(nearest) / divisor,
                    mean_distance_to_centroid=_mean(centroid_distances) / divisor,
                    mean_speed_pixels_per_second=mean_speed_px,
                    mean_speed_per_second=(
                        mean_speed_px / divisor if mean_speed_px is not None else None
                    ),
                    polarization=self._polarization(movement_vectors),
                )
            )
            previous_centers = current
            previous_frame = frame

        if not frame_metrics:
            raise ValidationError(
                "Selected trajectories do not overlap on any frame with at least two tracks"
            )

        speed_values = [
            item.mean_speed_pixels_per_second
            for item in frame_metrics
            if item.mean_speed_pixels_per_second is not None
        ]
        polarization_values = [
            item.polarization for item in frame_metrics if item.polarization is not None
        ]
        mean_speed_px = _optional_mean(speed_values)

        return VideoSchoolingAnalyticsResponse(
            schema_version="video-schooling-analytics-0001",
            video_id=video_id,
            track_ids=payload.track_ids,
            start_frame=start_frame,
            end_frame=end_frame,
            trajectory_policy="configured_track_interpolation",
            frames_evaluated=len(frame_metrics),
            mean_group_size=_mean(
                [float(item.active_track_count) for item in frame_metrics]
            ),
            mean_pairwise_distance_pixels=_mean(
                [item.mean_pairwise_distance_pixels for item in frame_metrics]
            ),
            mean_nearest_neighbor_distance_pixels=_mean(
                [item.mean_nearest_neighbor_distance_pixels for item in frame_metrics]
            ),
            mean_distance_to_centroid_pixels=_mean(
                [item.mean_distance_to_centroid_pixels for item in frame_metrics]
            ),
            mean_pairwise_distance=_mean(
                [item.mean_pairwise_distance for item in frame_metrics]
            ),
            mean_nearest_neighbor_distance=_mean(
                [item.mean_nearest_neighbor_distance for item in frame_metrics]
            ),
            mean_distance_to_centroid=_mean(
                [item.mean_distance_to_centroid for item in frame_metrics]
            ),
            mean_speed_pixels_per_second=mean_speed_px,
            mean_speed_per_second=(
                mean_speed_px / divisor if mean_speed_px is not None else None
            ),
            mean_polarization=_optional_mean(polarization_values),
            distance_unit=calibration.unit,
            calibration=calibration,
            frames=frame_metrics,
        )
