"""Managed video import, track editing, analytics, and research exports."""

from __future__ import annotations

import csv
import io
import itertools
import os
import re
from collections import Counter, defaultdict
from hashlib import sha256
from math import hypot, sqrt
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    LabelClass,
    ModelRegistration,
    Project,
    VideoAsset,
    VideoTrack,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.videos import (
    VideoAnalyticsRequest,
    VideoAnalyticsResponse,
    VideoAssetResponse,
    VideoCalibrationUpdate,
    VideoFrameSchoolAnalytics,
    VideoHeatmapCell,
    VideoImportResponse,
    VideoTrackAnalytics,
    VideoTrackCreateRequest,
    VideoTrackingJobRequest,
    VideoTrackKeyframe,
    VideoTrackResponse,
    VideoTrackUpdateRequest,
)
from reefvision.storage.datasets import canonical_json_bytes
from reefvision.storage.projects import resolve_managed_project_path

SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


def _safe_filename(filename: str | None) -> str:
    raw = Path(filename or "video.mp4").name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")
    if not sanitized:
        sanitized = "video.mp4"
    suffix = Path(sanitized).suffix.casefold()
    if suffix not in SUPPORTED_VIDEO_SUFFIXES:
        raise ValidationError("Supported video containers are MP4, MOV, AVI, MKV, and M4V")
    return sanitized


def _track_response(track: VideoTrack) -> VideoTrackResponse:
    return VideoTrackResponse(
        id=track.id,
        video_id=track.video_id,
        label_class_id=track.label_class_id,
        track_number=track.track_number,
        geometry_kind=track.geometry_kind,
        keyframes=[VideoTrackKeyframe.model_validate(item) for item in track.keyframes_json],
        interpolation=track.interpolation,
        status=track.status,
        metadata_json=dict(track.metadata_json or {}),
    )


def _center(keyframe: VideoTrackKeyframe) -> tuple[float, float]:
    return (
        (keyframe.x_min + keyframe.x_max) / 2.0,
        (keyframe.y_min + keyframe.y_max) / 2.0,
    )


def interpolate_track(track: VideoTrack) -> list[VideoTrackKeyframe]:
    keyframes = sorted(
        [VideoTrackKeyframe.model_validate(item) for item in track.keyframes_json],
        key=lambda item: item.frame_index,
    )
    if len(keyframes) <= 1:
        return keyframes
    interpolated: list[VideoTrackKeyframe] = []
    for left, right in itertools.pairwise(keyframes):
        frame_delta = right.frame_index - left.frame_index
        if frame_delta <= 0:
            continue
        for frame_index in range(left.frame_index, right.frame_index):
            ratio = (frame_index - left.frame_index) / frame_delta
            if track.interpolation == "hold":
                ratio = 0.0
            confidence = (
                left.confidence
                if right.confidence is None or left.confidence is None
                else left.confidence + (right.confidence - left.confidence) * ratio
            )
            interpolated.append(
                VideoTrackKeyframe(
                    frame_index=frame_index,
                    x_min=left.x_min + (right.x_min - left.x_min) * ratio,
                    y_min=left.y_min + (right.y_min - left.y_min) * ratio,
                    x_max=left.x_max + (right.x_max - left.x_max) * ratio,
                    y_max=left.y_max + (right.y_max - left.y_max) * ratio,
                    confidence=confidence,
                    source="interpolated" if frame_index != left.frame_index else left.source,
                )
            )
    interpolated.append(keyframes[-1])
    return interpolated


class VideoService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def import_video(
        self,
        project_id: str,
        *,
        filename: str | None,
        media_type: str | None,
        stream: BinaryIO,
    ) -> VideoImportResponse:
        project = self._project(project_id)
        safe_name = _safe_filename(filename)
        video_id = str(uuid4())
        suffix = Path(safe_name).suffix.casefold()
        managed_path = f"{project.storage_root}/videos/{video_id}{suffix}"
        destination = resolve_managed_project_path(self.settings, managed_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.upload")
        digest = sha256()
        size = 0
        try:
            with temporary.open("wb") as output:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > self.settings.model_max_upload_bytes:
                        raise ValidationError("Video exceeds the configured upload limit")
                    digest.update(chunk)
                    output.write(chunk)
            checksum = digest.hexdigest()
            existing = self.session.scalar(
                select(VideoAsset).where(
                    VideoAsset.project_id == project.id,
                    VideoAsset.sha256 == checksum,
                )
            )
            if existing is not None:
                temporary.unlink(missing_ok=True)
                return VideoImportResponse(
                    video=VideoAssetResponse.model_validate(existing),
                    duplicate=True,
                )

            try:
                import cv2
            except Exception as exc:
                raise ValidationError("OpenCV is required to inspect imported videos") from exc
            capture = cv2.VideoCapture(str(temporary))
            if not capture.isOpened():
                capture.release()
                raise ValidationError("The uploaded video could not be opened")
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            capture.release()
            if width <= 0 or height <= 0 or frame_count <= 0 or fps <= 0:
                raise ValidationError("The uploaded video metadata is incomplete")
            duration = frame_count / fps
            os.replace(temporary, destination)
            video = VideoAsset(
                id=video_id,
                project_id=project.id,
                original_filename=safe_name,
                managed_path=managed_path,
                sha256=checksum,
                media_type=media_type or "video/mp4",
                width_px=width,
                height_px=height,
                frame_count=frame_count,
                fps=fps,
                duration_seconds=duration,
                metadata_json={
                    "file_size_bytes": size,
                    "source_modified": False,
                },
            )
            self.session.add(video)
            self.session.commit()
            self.session.refresh(video)
            return VideoImportResponse(
                video=VideoAssetResponse.model_validate(video),
                duplicate=False,
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            self.session.rollback()
            raise

    def list_videos(self, project_id: str) -> list[VideoAssetResponse]:
        self._project(project_id)
        videos = list(
            self.session.scalars(
                select(VideoAsset)
                .where(VideoAsset.project_id == project_id)
                .order_by(VideoAsset.created_at.desc(), VideoAsset.id)
            )
        )
        return [VideoAssetResponse.model_validate(item) for item in videos]

    def get_video(self, video_id: str) -> VideoAssetResponse:
        return VideoAssetResponse.model_validate(self._video(video_id))

    def video_path(self, video_id: str) -> Path:
        video = self._video(video_id)
        path = resolve_managed_project_path(self.settings, video.managed_path)
        if not path.is_file():
            raise NotFoundError("Managed video file is missing")
        return path

    def delete_video(self, video_id: str) -> None:
        video = self._video(video_id)
        path = resolve_managed_project_path(self.settings, video.managed_path)
        self.session.delete(video)
        self.session.commit()
        path.unlink(missing_ok=True)

    def update_calibration(
        self,
        video_id: str,
        request: VideoCalibrationUpdate,
    ) -> VideoAssetResponse:
        video = self._video(video_id)
        video.metadata_json = {
            **dict(video.metadata_json),
            "calibration": request.model_dump(mode="json"),
        }
        self.session.commit()
        self.session.refresh(video)
        return VideoAssetResponse.model_validate(video)

    def _validate_track(
        self,
        video: VideoAsset,
        *,
        label_class_id: str | None,
        keyframes: list[VideoTrackKeyframe],
    ) -> None:
        if label_class_id is not None:
            label_class = self.session.get(LabelClass, label_class_id)
            if label_class is None or label_class.project_id != video.project_id:
                raise ValidationError("Track classes must belong to the video project")
        for keyframe in keyframes:
            if keyframe.frame_index >= video.frame_count:
                raise ValidationError("Track keyframes must fall within the video")
            if keyframe.x_max > video.width_px or keyframe.y_max > video.height_px:
                raise ValidationError("Track boxes must remain inside the video frame")

    def list_tracks(self, video_id: str) -> list[VideoTrackResponse]:
        self._video(video_id)
        tracks = list(
            self.session.scalars(
                select(VideoTrack)
                .where(VideoTrack.video_id == video_id)
                .order_by(VideoTrack.track_number, VideoTrack.id)
            )
        )
        return [_track_response(item) for item in tracks]

    def create_track(
        self,
        video_id: str,
        request: VideoTrackCreateRequest,
    ) -> VideoTrackResponse:
        video = self._video(video_id)
        if request.video_id != video.id:
            raise ValidationError("Track request video_id does not match the route")
        self._validate_track(
            video,
            label_class_id=request.label_class_id,
            keyframes=request.keyframes,
        )
        existing = self.session.scalar(
            select(VideoTrack).where(
                VideoTrack.video_id == video.id,
                VideoTrack.track_number == request.track_number,
            )
        )
        if existing is not None:
            raise ConflictError("A track with this number already exists for the video")
        track = VideoTrack(
            video_id=video.id,
            label_class_id=request.label_class_id,
            track_number=request.track_number,
            geometry_kind=request.geometry_kind,
            keyframes_json=[item.model_dump(mode="json") for item in request.keyframes],
            interpolation=request.interpolation,
            status=request.status,
            metadata_json={"source": "human"},
        )
        self.session.add(track)
        self.session.commit()
        self.session.refresh(track)
        return _track_response(track)

    def update_track(
        self,
        track_id: str,
        request: VideoTrackUpdateRequest,
    ) -> VideoTrackResponse:
        track = self.session.get(VideoTrack, track_id)
        if track is None:
            raise NotFoundError("Video track not found")
        video = self._video(track.video_id)
        keyframes = request.keyframes or [
            VideoTrackKeyframe.model_validate(item) for item in track.keyframes_json
        ]
        label_class_id = (
            request.label_class_id
            if "label_class_id" in request.model_fields_set
            else track.label_class_id
        )
        self._validate_track(
            video,
            label_class_id=label_class_id,
            keyframes=keyframes,
        )
        track.label_class_id = label_class_id
        if request.keyframes is not None:
            track.keyframes_json = [item.model_dump(mode="json") for item in keyframes]
        if request.interpolation is not None:
            track.interpolation = request.interpolation
        if request.status is not None:
            track.status = request.status
        self.session.commit()
        self.session.refresh(track)
        return _track_response(track)

    def delete_track(self, track_id: str) -> None:
        track = self.session.get(VideoTrack, track_id)
        if track is None:
            raise NotFoundError("Video track not found")
        self.session.delete(track)
        self.session.commit()

    def create_tracking_job(
        self,
        video_id: str,
        request: VideoTrackingJobRequest,
    ) -> JobResponse:
        video = self._video(video_id)
        model = self.session.get(ModelRegistration, request.model_id)
        if (
            model is None
            or model.project_id != video.project_id
            or model.purpose != "detector"
            or model.task != "detect"
        ):
            raise ValidationError("Video tracking requires a project detector model")
        job = Job(
            project_id=video.project_id,
            job_type="video_track",
            status="queued",
            progress_total=max(1, video.frame_count // request.every_n_frames),
            request_json={
                "video_id": video.id,
                **request.model_dump(mode="json"),
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)

    def analytics(
        self,
        video_id: str,
        request: VideoAnalyticsRequest,
    ) -> VideoAnalyticsResponse:
        video = self._video(video_id)
        tracks = list(
            self.session.scalars(
                select(VideoTrack)
                .where(VideoTrack.video_id == video.id)
                .order_by(VideoTrack.track_number)
            )
        )
        calibration = dict(video.metadata_json).get("calibration", {})
        distance_per_pixel = (
            float(calibration["distance_per_pixel"])
            if isinstance(calibration, dict) and calibration.get("distance_per_pixel")
            else None
        )
        physical_unit = (
            str(calibration.get("unit"))
            if isinstance(calibration, dict) and calibration.get("unit")
            else None
        )
        track_results: list[VideoTrackAnalytics] = []
        centers_by_frame: dict[int, list[tuple[float, float]]] = defaultdict(list)
        heatmap_counts: Counter[tuple[int, int]] = Counter()
        warnings: list[str] = []
        if distance_per_pixel is None:
            warnings.append(
                "Video calibration is not set; physical distance and speed are unavailable."
            )

        for track in tracks:
            points = interpolate_track(track)
            if not points:
                continue
            centers = [_center(item) for item in points]
            frame_distances: list[float] = []
            frame_speeds: list[float] = []
            interval_seconds: list[float] = []
            zone_counts: Counter[str] = Counter()
            for index, (point, center) in enumerate(zip(points, centers, strict=True)):
                centers_by_frame[point.frame_index].append(center)
                column = min(
                    request.heatmap_bins_x - 1,
                    max(0, int(center[0] / video.width_px * request.heatmap_bins_x)),
                )
                row = min(
                    request.heatmap_bins_y - 1,
                    max(0, int(center[1] / video.height_px * request.heatmap_bins_y)),
                )
                heatmap_counts[(column, row)] += 1
                for zone in request.zones:
                    if (
                        zone.x_min <= center[0] <= zone.x_max
                        and zone.y_min <= center[1] <= zone.y_max
                    ):
                        zone_counts[zone.name] += 1
                if index == 0:
                    continue
                previous = points[index - 1]
                frame_delta = point.frame_index - previous.frame_index
                if frame_delta <= 0:
                    continue
                elapsed = frame_delta / video.fps
                distance = hypot(
                    center[0] - centers[index - 1][0],
                    center[1] - centers[index - 1][1],
                )
                frame_distances.append(distance)
                frame_speeds.append(distance / elapsed)
                interval_seconds.append(elapsed)
            duration = (points[-1].frame_index - points[0].frame_index) / video.fps
            distance_pixels = sum(frame_distances)
            mean_speed = distance_pixels / duration if duration > 0 else 0.0
            maximum_speed = max(frame_speeds, default=0.0)
            active_time = sum(
                elapsed
                for elapsed, speed in zip(interval_seconds, frame_speeds, strict=True)
                if speed >= request.activity_speed_threshold_pixels_per_second
            )
            inactive_time = max(0.0, duration - active_time)
            track_results.append(
                VideoTrackAnalytics(
                    track_id=track.id,
                    tracker_id=track.track_number,
                    label_class_id=track.label_class_id,
                    first_frame=points[0].frame_index,
                    last_frame=points[-1].frame_index,
                    observed_frame_count=len(points),
                    duration_seconds=duration,
                    distance_pixels=distance_pixels,
                    mean_speed_pixels_per_second=mean_speed,
                    maximum_speed_pixels_per_second=maximum_speed,
                    active_time_seconds=active_time,
                    inactive_time_seconds=inactive_time,
                    distance_physical=(
                        distance_pixels * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    mean_speed_physical_per_second=(
                        mean_speed * distance_per_pixel if distance_per_pixel is not None else None
                    ),
                    maximum_speed_physical_per_second=(
                        maximum_speed * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    physical_unit=physical_unit,
                    zone_time_seconds={
                        name: count / video.fps for name, count in sorted(zone_counts.items())
                    },
                )
            )

        school_results: list[VideoFrameSchoolAnalytics] = []
        for frame_index, centers in sorted(centers_by_frame.items()):
            nearest: list[float] = []
            if len(centers) >= 2:
                for index, center in enumerate(centers):
                    nearest.append(
                        min(
                            hypot(center[0] - other[0], center[1] - other[1])
                            for other_index, other in enumerate(centers)
                            if other_index != index
                        )
                    )
                center_x = sum(point[0] for point in centers) / len(centers)
                center_y = sum(point[1] for point in centers) / len(centers)
                spread = sqrt(
                    sum(
                        (point[0] - center_x) ** 2 + (point[1] - center_y) ** 2 for point in centers
                    )
                    / len(centers)
                )
                mean_nearest = sum(nearest) / len(nearest)
            else:
                spread = None
                mean_nearest = None
            school_results.append(
                VideoFrameSchoolAnalytics(
                    frame_index=frame_index,
                    timestamp_seconds=frame_index / video.fps,
                    active_track_count=len(centers),
                    mean_nearest_neighbor_pixels=mean_nearest,
                    school_spread_pixels=spread,
                    mean_nearest_neighbor_physical=(
                        mean_nearest * distance_per_pixel
                        if mean_nearest is not None and distance_per_pixel is not None
                        else None
                    ),
                    school_spread_physical=(
                        spread * distance_per_pixel
                        if spread is not None and distance_per_pixel is not None
                        else None
                    ),
                )
            )

        heatmap = [
            VideoHeatmapCell(
                column=column,
                row=row,
                observation_count=count,
                occupancy_seconds=count / video.fps,
            )
            for (column, row), count in sorted(heatmap_counts.items())
        ]
        return VideoAnalyticsResponse(
            video_id=video.id,
            fps=video.fps,
            distance_per_pixel=distance_per_pixel,
            physical_unit=physical_unit,
            tracks=track_results,
            school_by_frame=school_results,
            heatmap_bins_x=request.heatmap_bins_x,
            heatmap_bins_y=request.heatmap_bins_y,
            heatmap=heatmap,
            warnings=warnings,
        )

    def export_tracks(self, video_id: str, export_format: str) -> tuple[bytes, str, str]:
        video = self._video(video_id)
        tracks = list(
            self.session.scalars(
                select(VideoTrack)
                .where(VideoTrack.video_id == video.id)
                .order_by(VideoTrack.track_number)
            )
        )
        if export_format == "json":
            payload = {
                "format": "reefvision_video_tracks_v1",
                "video": VideoAssetResponse.model_validate(video).model_dump(mode="json"),
                "tracks": [
                    {
                        **_track_response(track).model_dump(mode="json"),
                        "interpolated_keyframes": [
                            item.model_dump(mode="json") for item in interpolate_track(track)
                        ],
                    }
                    for track in tracks
                ],
            }
            return (
                canonical_json_bytes(payload),
                "application/json",
                f"reefvision-{video.id}-tracks.json",
            )

        output = io.StringIO(newline="")
        if export_format == "csv":
            writer = csv.writer(output)
            writer.writerow(
                [
                    "frame",
                    "time_seconds",
                    "tracker_id",
                    "label_class_id",
                    "x",
                    "y",
                    "x_min",
                    "y_min",
                    "x_max",
                    "y_max",
                    "confidence",
                ]
            )
            for track in tracks:
                for point in interpolate_track(track):
                    center_x, center_y = _center(point)
                    writer.writerow(
                        [
                            point.frame_index,
                            point.frame_index / video.fps,
                            track.track_number,
                            track.label_class_id or "",
                            center_x,
                            center_y,
                            point.x_min,
                            point.y_min,
                            point.x_max,
                            point.y_max,
                            point.confidence if point.confidence is not None else "",
                        ]
                    )
            return (
                output.getvalue().encode("utf-8"),
                "text/csv; charset=utf-8",
                f"reefvision-{video.id}-tracks.csv",
            )
        if export_format == "mot":
            writer = csv.writer(output, lineterminator="\n")
            for track in tracks:
                for point in interpolate_track(track):
                    writer.writerow(
                        [
                            point.frame_index + 1,
                            track.track_number,
                            point.x_min,
                            point.y_min,
                            point.x_max - point.x_min,
                            point.y_max - point.y_min,
                            point.confidence if point.confidence is not None else 1.0,
                            -1,
                            -1,
                            -1,
                        ]
                    )
            return (
                output.getvalue().encode("utf-8"),
                "text/plain; charset=utf-8",
                f"reefvision-{video.id}-mot.txt",
            )
        raise ValidationError("Supported tracking exports are csv, mot, and json")
