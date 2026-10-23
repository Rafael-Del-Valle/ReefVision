"""Revisioned sparse video tracks, interpolation, and trajectory analytics."""

from __future__ import annotations

import builtins
from itertools import pairwise
from math import hypot
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    GeoReferencedObservation,
    LabelClass,
    VideoAsset,
    VideoTrack,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.geospatial.geodesy import geodesic_distance_m
from reefvision.schemas.videos import (
    InterpolatedTrackFrame,
    VideoFrameObjectMetric,
    VideoFrameSpatialMetricsResponse,
    VideoTrackAnalyticsResponse,
    VideoTrackCreate,
    VideoTrackInterpolationResponse,
    VideoTrackKeyframe,
    VideoTrackResponse,
    VideoTrackUpdate,
)
from reefvision.services.georeferenced_observations import GeoReferencedObservationService
from reefvision.services.video_observation_location import (
    select_video_observation_image_location,
)


class _FrameSpatialObject(TypedDict):
    track: VideoTrack
    bbox: tuple[float, float, float, float]
    center_x: float
    center_y: float


def _keyframe_payload(item: VideoTrackKeyframe) -> dict[str, object]:
    payload: dict[str, object] = {
        "frame": item.frame,
        "bbox": list(item.bbox),
        "confidence": item.confidence,
    }
    if item.keypoints is not None:
        payload["keypoints"] = [list(point) for point in item.keypoints]
    if item.mask_polygons is not None:
        payload["mask_polygons"] = [
            [list(point) for point in polygon] for polygon in item.mask_polygons
        ]
    if item.pose_observations is not None:
        payload["pose_observations"] = [
            observation.model_dump(mode="json") for observation in item.pose_observations
        ]
    return payload


class VideoTrackService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _track(self, track_id: str) -> VideoTrack:
        track = self.session.get(VideoTrack, track_id)
        if track is None or track.deleted_at is not None:
            raise NotFoundError("Video track not found")
        return track

    def _validate_class(self, video: VideoAsset, label_class_id: str) -> None:
        label_class = self.session.get(LabelClass, label_class_id)
        if label_class is None or label_class.project_id != video.project_id:
            raise ValidationError("Track class must belong to the video project")

    @staticmethod
    def _validate_keyframes(video: VideoAsset, keyframes: list[VideoTrackKeyframe]) -> None:
        for keyframe in keyframes:
            if keyframe.frame >= video.frame_count:
                raise ValidationError("Track keyframes cannot exceed the video frame range")
            x, y, width, height = keyframe.bbox
            if x + width > video.width_px or y + height > video.height_px:
                raise ValidationError("Track boxes cannot extend outside the source video bounds")
            for keypoint_x, keypoint_y, _confidence in keyframe.keypoints or []:
                if keypoint_x > video.width_px or keypoint_y > video.height_px:
                    raise ValidationError(
                        "Pose keypoints cannot extend outside the source video bounds"
                    )
            for polygon in keyframe.mask_polygons or []:
                for point_x, point_y in polygon:
                    if point_x > video.width_px or point_y > video.height_px:
                        raise ValidationError(
                            "Segmentation polygons cannot extend outside the source video bounds"
                        )
            for observation in keyframe.pose_observations or []:
                if observation.x > video.width_px or observation.y > video.height_px:
                    raise ValidationError(
                        "Pose observations cannot extend outside the source video bounds"
                    )

    def list(self, video_id: str) -> list[VideoTrackResponse]:
        self._video(video_id)
        statement = (
            select(VideoTrack)
            .where(VideoTrack.video_id == video_id, VideoTrack.deleted_at.is_(None))
            .order_by(VideoTrack.track_number, VideoTrack.created_at, VideoTrack.id)
        )
        return [VideoTrackResponse.model_validate(item) for item in self.session.scalars(statement)]

    def create(self, video_id: str, payload: VideoTrackCreate) -> VideoTrackResponse:
        video = self._video(video_id)
        self._validate_class(video, payload.label_class_id)
        self._validate_keyframes(video, payload.keyframes)
        track_number = payload.track_number
        if track_number is None:
            track_number = (
                int(
                    self.session.scalar(
                        select(func.max(VideoTrack.track_number)).where(
                            VideoTrack.video_id == video_id
                        )
                    )
                    or 0
                )
                + 1
            )
        conflict = self.session.scalar(
            select(VideoTrack.id).where(
                VideoTrack.video_id == video_id,
                VideoTrack.track_number == track_number,
                VideoTrack.deleted_at.is_(None),
            )
        )
        if conflict is not None:
            raise ConflictError("Track number already exists for this video")
        track = VideoTrack(
            video_id=video_id,
            label_class_id=payload.label_class_id,
            track_number=track_number,
            geometry_kind=payload.geometry_kind,
            keyframes_json=[_keyframe_payload(item) for item in payload.keyframes],
            interpolation=payload.interpolation,
            status=payload.status,
            metadata_json={"source": "human"},
        )
        self.session.add(track)
        video.revision += 1
        self.session.commit()
        self.session.refresh(track)
        return VideoTrackResponse.model_validate(track)

    def update(self, track_id: str, payload: VideoTrackUpdate) -> VideoTrackResponse:
        track = self._track(track_id)
        video = self._video(track.video_id)
        if track.revision != payload.base_revision:
            raise ConflictError("Video track revision conflict")
        self._validate_class(video, payload.label_class_id)
        self._validate_keyframes(video, payload.keyframes)
        track.label_class_id = payload.label_class_id
        track.keyframes_json = [_keyframe_payload(item) for item in payload.keyframes]
        track.interpolation = payload.interpolation
        track.status = payload.status
        track.metadata_json = {**dict(track.metadata_json or {}), "last_editor": "local_user"}
        track.revision += 1
        video.revision += 1
        self.session.commit()
        self.session.refresh(track)
        return VideoTrackResponse.model_validate(track)

    def delete(self, track_id: str) -> None:
        track = self._track(track_id)
        video = self._video(track.video_id)
        GeoReferencedObservationService(self.session).delete_for_tracks([track.id])
        track.deleted_at = utc_now()
        track.revision += 1
        video.revision += 1
        self.session.commit()

    @staticmethod
    def _keyframes(track: VideoTrack) -> builtins.list[VideoTrackKeyframe]:
        try:
            return [VideoTrackKeyframe.model_validate(item) for item in track.keyframes_json]
        except ValueError as exc:
            raise ValidationError("Stored video track keyframes are invalid") from exc

    @staticmethod
    def _bbox_at_frame(
        track: VideoTrack,
        frame_index: int,
    ) -> tuple[float, float, float, float] | None:
        keyframes = VideoTrackService._keyframes(track)
        if not keyframes or frame_index < keyframes[0].frame or frame_index > keyframes[-1].frame:
            return None

        for item in keyframes:
            if item.frame == frame_index:
                return item.bbox

        # Machine outputs represent actual detector/tracker observations.
        # Do not invent on-screen instances between missed detections.
        if track.source_job_id is not None:
            return None

        for first, second in pairwise(keyframes):
            if first.frame < frame_index < second.frame:
                if track.interpolation == "hold":
                    return first.bbox
                span = second.frame - first.frame
                ratio = (frame_index - first.frame) / span
                return (
                    first.bbox[0] + (second.bbox[0] - first.bbox[0]) * ratio,
                    first.bbox[1] + (second.bbox[1] - first.bbox[1]) * ratio,
                    first.bbox[2] + (second.bbox[2] - first.bbox[2]) * ratio,
                    first.bbox[3] + (second.bbox[3] - first.bbox[3]) * ratio,
                )
        return None

    def delete_for_video(
        self,
        video_id: str,
        *,
        machine_only: bool = True,
    ) -> int:
        video = self._video(video_id)
        statement = select(VideoTrack).where(
            VideoTrack.video_id == video_id,
            VideoTrack.deleted_at.is_(None),
        )
        if machine_only:
            statement = statement.where(VideoTrack.source_job_id.is_not(None))

        tracks = list(self.session.scalars(statement))
        if not tracks:
            return 0

        GeoReferencedObservationService(self.session).delete_for_tracks(
            track.id for track in tracks
        )
        now = utc_now()
        for track in tracks:
            track.deleted_at = now
            track.revision += 1

        video.revision += 1
        self.session.commit()
        return len(tracks)

    def frame_spatial_metrics(
        self,
        video_id: str,
        frame_index: int,
    ) -> VideoFrameSpatialMetricsResponse:
        video = self._video(video_id)
        if frame_index < 0 or frame_index >= video.frame_count:
            raise ValidationError("Video frame is outside the source frame range")

        active_tracks = list(
            self.session.scalars(
                select(VideoTrack)
                .where(
                    VideoTrack.video_id == video_id,
                    VideoTrack.deleted_at.is_(None),
                )
                .order_by(VideoTrack.track_number, VideoTrack.id)
            )
        )

        objects: list[_FrameSpatialObject] = []
        for track in active_tracks:
            bbox = self._bbox_at_frame(track, frame_index)
            if bbox is None:
                continue
            location = select_video_observation_image_location(
                bbox=bbox,
                image_width_px=video.width_px,
                image_height_px=video.height_px,
            )
            objects.append(
                {
                    "track": track,
                    "bbox": bbox,
                    "center_x": location.pixel_x,
                    "center_y": location.pixel_y,
                }
            )

        geographic = {
            item.track_id: item
            for item in self.session.scalars(
                select(GeoReferencedObservation).where(
                    GeoReferencedObservation.video_id == video_id,
                    GeoReferencedObservation.frame_index == frame_index,
                    GeoReferencedObservation.is_stale.is_(False),
                    GeoReferencedObservation.track_id.is_not(None),
                )
            )
            if item.track_id is not None
        }

        results: list[VideoFrameObjectMetric] = []
        pixel_nearest: list[float] = []
        meter_nearest: list[float] = []

        for index, item in enumerate(objects):
            track = item["track"]
            assert isinstance(track, VideoTrack)
            nearest_track_id: str | None = None
            nearest_pixels: float | None = None

            for other_index, other in enumerate(objects):
                if index == other_index:
                    continue
                distance = hypot(
                    float(item["center_x"]) - float(other["center_x"]),
                    float(item["center_y"]) - float(other["center_y"]),
                )
                if nearest_pixels is None or distance < nearest_pixels:
                    nearest_pixels = distance
                    other_track = other["track"]
                    assert isinstance(other_track, VideoTrack)
                    nearest_track_id = other_track.id

            nearest_meters: float | None = None
            nearest_track_id_meters: str | None = None
            source_geo = geographic.get(track.id)
            if source_geo is not None:
                for other in objects:
                    other_track = other["track"]
                    assert isinstance(other_track, VideoTrack)
                    if other_track.id == track.id:
                        continue
                    target_geo = geographic.get(other_track.id)
                    if target_geo is None:
                        continue
                    distance_m = geodesic_distance_m(
                        source_geo.latitude_deg,
                        source_geo.longitude_deg,
                        target_geo.latitude_deg,
                        target_geo.longitude_deg,
                    )
                    if nearest_meters is None or distance_m < nearest_meters:
                        nearest_meters = distance_m
                        nearest_track_id_meters = other_track.id

            if nearest_pixels is not None:
                pixel_nearest.append(nearest_pixels)
            if nearest_meters is not None:
                meter_nearest.append(nearest_meters)

            results.append(
                VideoFrameObjectMetric(
                    track_id=track.id,
                    track_number=track.track_number,
                    label_class_id=track.label_class_id,
                    bbox=item["bbox"],
                    center_x=float(item["center_x"]),
                    center_y=float(item["center_y"]),
                    nearest_neighbor_track_id=nearest_track_id,
                    nearest_neighbor_distance_pixels=nearest_pixels,
                    nearest_neighbor_track_id_meters=nearest_track_id_meters,
                    nearest_neighbor_distance_meters=nearest_meters,
                )
            )

        return VideoFrameSpatialMetricsResponse(
            video_id=video_id,
            frame_index=frame_index,
            object_count=len(results),
            mean_nearest_neighbor_distance_pixels=(
                sum(pixel_nearest) / len(pixel_nearest) if pixel_nearest else None
            ),
            minimum_nearest_neighbor_distance_pixels=(
                min(pixel_nearest) if pixel_nearest else None
            ),
            mean_nearest_neighbor_distance_meters=(
                sum(meter_nearest) / len(meter_nearest) if meter_nearest else None
            ),
            minimum_nearest_neighbor_distance_meters=(
                min(meter_nearest) if meter_nearest else None
            ),
            objects=results,
        )

    def interpolate(self, track_id: str) -> VideoTrackInterpolationResponse:
        track = self._track(track_id)
        video = self._video(track.video_id)
        keyframes = self._keyframes(track)
        by_frame = {item.frame: item for item in keyframes}
        frames: list[InterpolatedTrackFrame] = []
        for first, second in pairwise(keyframes):
            span = second.frame - first.frame
            for frame in range(first.frame, second.frame):
                ratio = 0.0 if track.interpolation == "hold" else (frame - first.frame) / span
                bbox = (
                    first.bbox[0] + (second.bbox[0] - first.bbox[0]) * ratio,
                    first.bbox[1] + (second.bbox[1] - first.bbox[1]) * ratio,
                    first.bbox[2] + (second.bbox[2] - first.bbox[2]) * ratio,
                    first.bbox[3] + (second.bbox[3] - first.bbox[3]) * ratio,
                )
                location = select_video_observation_image_location(
                    bbox=bbox,
                    image_width_px=video.width_px,
                    image_height_px=video.height_px,
                )
                frames.append(
                    InterpolatedTrackFrame(
                        frame=frame,
                        timestamp_seconds=frame / video.fps,
                        bbox=bbox,
                        center_x=location.pixel_x,
                        center_y=location.pixel_y,
                        source="keyframe" if frame in by_frame else "interpolated",
                    )
                )
        last = keyframes[-1]
        location = select_video_observation_image_location(
            bbox=last.bbox,
            image_width_px=video.width_px,
            image_height_px=video.height_px,
        )
        frames.append(
            InterpolatedTrackFrame(
                frame=last.frame,
                timestamp_seconds=last.frame / video.fps,
                bbox=last.bbox,
                center_x=location.pixel_x,
                center_y=location.pixel_y,
                source="keyframe",
            )
        )
        return VideoTrackInterpolationResponse(
            track_id=track.id,
            video_id=track.video_id,
            interpolation=track.interpolation,
            frames=frames,
        )

    def analytics(self, track_id: str) -> VideoTrackAnalyticsResponse:
        track = self._track(track_id)
        video = self._video(track.video_id)
        interpolation = self.interpolate(track_id)
        frames = interpolation.frames
        centers = [(item.center_x, item.center_y) for item in frames]
        distances = [
            hypot(second[0] - first[0], second[1] - first[1]) for first, second in pairwise(centers)
        ]
        path_length = sum(distances)
        duration = max(0.0, (frames[-1].frame - frames[0].frame) / video.fps)
        speeds = [distance * video.fps for distance in distances]
        displacement = hypot(
            centers[-1][0] - centers[0][0],
            centers[-1][1] - centers[0][1],
        )
        mean_area = sum(item.bbox[2] * item.bbox[3] for item in frames) / len(frames)
        occupancy = {f"row_{row}_column_{column}": 0 for row in range(3) for column in range(3)}
        for center_x, center_y in centers:
            column = min(2, int(center_x / video.width_px * 3))
            row = min(2, int(center_y / video.height_px * 3))
            occupancy[f"row_{row}_column_{column}"] += 1
        return VideoTrackAnalyticsResponse(
            track_id=track.id,
            video_id=track.video_id,
            track_number=track.track_number,
            label_class_id=track.label_class_id,
            first_frame=frames[0].frame,
            last_frame=frames[-1].frame,
            observed_frame_count=len(frames),
            duration_seconds=duration,
            path_length_pixels=path_length,
            mean_speed_pixels_per_second=path_length / duration if duration > 0 else 0.0,
            maximum_speed_pixels_per_second=max(speeds, default=0.0),
            displacement_pixels=displacement,
            mean_bbox_area_pixels=mean_area,
            occupancy_grid=occupancy,
        )
