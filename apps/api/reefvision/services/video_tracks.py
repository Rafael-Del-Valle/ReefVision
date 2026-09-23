"""Revisioned sparse video tracks, interpolation, and trajectory analytics."""

from __future__ import annotations

import builtins
from itertools import pairwise
from math import hypot

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import LabelClass, VideoAsset, VideoTrack
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.videos import (
    InterpolatedTrackFrame,
    VideoTrackAnalyticsResponse,
    VideoTrackCreate,
    VideoTrackInterpolationResponse,
    VideoTrackKeyframe,
    VideoTrackResponse,
    VideoTrackUpdate,
)
from reefvision.services.video_observation_location import (
    select_video_observation_image_location,
)


def _keyframe_payload(item: VideoTrackKeyframe) -> dict[str, object]:
    return {
        "frame": item.frame,
        "bbox": list(item.bbox),
        "confidence": item.confidence,
    }


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
