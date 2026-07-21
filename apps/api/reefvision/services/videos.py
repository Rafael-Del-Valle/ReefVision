"""Managed video import, track editing, analytics, and research exports."""

from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from math import ceil, hypot, sqrt
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    Project,
    VideoAsset,
    VideoTrack,
)
from reefvision.domain.errors import NotFoundError, ValidationError
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
    VideoTrackResponse,
    VideoTrackUpdateRequest,
)
from reefvision.services.video_tracks import (
    VideoTrackCorrectionService,
    interpolate_track,
    observation_center,
    track_response,
)
from reefvision.storage.datasets import canonical_json_bytes, canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.videos import (
    cleanup_video_upload,
    commit_video_upload,
    probe_video,
    read_video_frame_jpeg,
    remove_managed_video,
    stage_video_upload,
)

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
        if media_type and not (
            media_type.startswith("video/") or media_type == "application/octet-stream"
        ):
            raise ValidationError("The uploaded file does not declare a supported video media type")
        staged = stage_video_upload(
            self.settings,
            project_storage_root=project.storage_root,
            video_id=video_id,
            suffix=suffix,
            stream=stream,
            maximum_bytes=self.settings.model_max_upload_bytes,
        )
        destination_committed = False
        try:
            existing = self.session.scalar(
                select(VideoAsset).where(
                    VideoAsset.project_id == project.id,
                    VideoAsset.sha256 == staged.sha256,
                )
            )
            if existing is not None:
                cleanup_video_upload(staged, include_destination=False)
                return VideoImportResponse(
                    video=VideoAssetResponse.model_validate(existing),
                    duplicate=True,
                )
            probe = probe_video(staged.temporary)
            commit_video_upload(staged)
            destination_committed = True
            video = VideoAsset(
                id=video_id,
                project_id=project.id,
                original_filename=safe_name,
                managed_path=staged.managed_path,
                sha256=staged.sha256,
                media_type=media_type or "video/mp4",
                width_px=probe.width_px,
                height_px=probe.height_px,
                frame_count=probe.frame_count,
                fps=probe.fps,
                duration_seconds=probe.duration_seconds,
                metadata_json={
                    "file_size_bytes": staged.size_bytes,
                    "source_modified": False,
                    "timing_source": "container_fps",
                    "codec": probe.codec,
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
            cleanup_video_upload(staged, include_destination=destination_committed)
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

    def frame_jpeg(self, video_id: str, frame_index: int) -> bytes:
        video = self._video(video_id)
        if frame_index < 0 or frame_index >= video.frame_count:
            raise ValidationError("Video frame index is outside the managed video")
        return read_video_frame_jpeg(self.video_path(video_id), frame_index)

    def delete_video(self, video_id: str) -> None:
        video = self._video(video_id)
        managed_path = video.managed_path
        self.session.delete(video)
        self.session.commit()
        remove_managed_video(self.settings, managed_path)

    def update_calibration(
        self,
        video_id: str,
        request: VideoCalibrationUpdate,
    ) -> VideoAssetResponse:
        video = self._video(video_id)
        existing_calibration = dict(video.metadata_json).get("calibration", {})
        calibration_revision = (
            int(existing_calibration.get("revision", 0))
            if isinstance(existing_calibration, dict)
            else 0
        )
        video.metadata_json = {
            **dict(video.metadata_json),
            "calibration": {
                **request.model_dump(mode="json"),
                "updated_at": datetime.now(UTC).isoformat(),
                "revision": calibration_revision + 1,
            },
        }
        video.revision += 1
        self.session.commit()
        self.session.refresh(video)
        return VideoAssetResponse.model_validate(video)

    def list_tracks(
        self,
        video_id: str,
        *,
        include_deleted: bool = False,
    ) -> list[VideoTrackResponse]:
        return VideoTrackCorrectionService(self.session).list_tracks(
            video_id,
            include_deleted=include_deleted,
        )

    def create_track(
        self,
        video_id: str,
        request: VideoTrackCreateRequest,
    ) -> VideoTrackResponse:
        return VideoTrackCorrectionService(self.session).create_track(video_id, request)

    def update_track(
        self,
        track_id: str,
        request: VideoTrackUpdateRequest,
    ) -> VideoTrackResponse:
        return VideoTrackCorrectionService(self.session).update_track(track_id, request)

    def delete_track(self, track_id: str) -> None:
        VideoTrackCorrectionService(self.session).delete_track(track_id)

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
        if model.provider_name != "ultralytics" or model.framework != "ultralytics":
            raise ValidationError(
                "Video tracking currently requires a compatible Ultralytics detector"
            )
        request_payload = request.model_dump(mode="json", exclude={"force_new_run"})
        requested_device = str(request_payload.pop("device"))
        fingerprint_payload = {
            "video_id": video.id,
            "video_sha256": video.sha256,
            "model_id": model.id,
            "model_sha256": model.sha256,
            **{key: value for key, value in request_payload.items() if key != "request_id"},
            "requested_device": requested_device,
        }
        idempotency_key = request.request_id or canonical_json_sha256(fingerprint_payload)
        if request.force_new_run:
            idempotency_key = str(uuid4())
        prior_jobs = list(
            self.session.scalars(
                select(Job)
                .where(
                    Job.project_id == video.project_id,
                    Job.job_type == "video_track",
                )
                .order_by(Job.created_at.desc(), Job.id.desc())
            )
        )
        for prior in prior_jobs:
            prior_request = dict(prior.request_json or {})
            if prior_request.get("idempotency_key") == idempotency_key and prior.status in {
                "queued",
                "running",
                "cancel_requested",
                "succeeded",
            }:
                return JobResponse.model_validate(prior)
        job = Job(
            project_id=video.project_id,
            job_type="video_track",
            status="queued",
            progress_total=max(1, ceil(video.frame_count / request.every_n_frames)),
            max_retries=1,
            resume_supported=False,
            request_json={
                "video_id": video.id,
                **request_payload,
                "requested_device": requested_device,
                "idempotency_key": idempotency_key,
                "source_video_sha256": video.sha256,
                "model_sha256": model.sha256,
                "provider_name": model.provider_name,
                "provider_version": model.provider_version,
            },
            result_json={"stage": "queued"},
            resource_requirements_json={
                "device": requested_device,
                "gpu_required": requested_device == "cuda",
                "cpu_threads": 2,
                "minimum_ram_bytes": 512 * 1024**2,
                "disk_intensive": True,
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
                .where(
                    VideoTrack.video_id == video.id,
                    VideoTrack.deleted_at.is_(None),
                )
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
            points = interpolate_track(track, video)
            if not points:
                continue
            centers = [observation_center(item) for item in points]
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
                .where(
                    VideoTrack.video_id == video.id,
                    VideoTrack.deleted_at.is_(None),
                )
                .order_by(VideoTrack.track_number)
            )
        )
        if export_format == "json":
            payload = {
                "format": "reefvision_video_tracks_v1",
                "video": VideoAssetResponse.model_validate(video).model_dump(mode="json"),
                "tracks": [
                    {
                        **track_response(track, video).model_dump(mode="json"),
                        "interpolated_keyframes": [
                            item.model_dump(mode="json") for item in interpolate_track(track, video)
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
                    "track_id",
                    "observation_id",
                    "label_class_id",
                    "x",
                    "y",
                    "x_min",
                    "y_min",
                    "x_max",
                    "y_max",
                    "confidence",
                    "source",
                    "manual_edit",
                    "track_revision",
                    "observation_revision",
                    "detector_model_id",
                    "detector_model_checksum",
                    "tracker",
                    "origin_job_id",
                ]
            )
            for track in tracks:
                for point in interpolate_track(track, video):
                    center_x, center_y = observation_center(point)
                    metadata = dict(track.metadata_json or {})
                    writer.writerow(
                        [
                            point.frame_index,
                            point.timestamp_seconds
                            if point.timestamp_seconds is not None
                            else point.frame_index / video.fps,
                            track.track_number,
                            track.id,
                            point.id or "",
                            track.label_class_id or "",
                            center_x,
                            center_y,
                            point.x_min,
                            point.y_min,
                            point.x_max,
                            point.y_max,
                            point.confidence if point.confidence is not None else "",
                            point.source,
                            point.manual_edit,
                            track.revision,
                            point.revision,
                            metadata.get("model_id", ""),
                            metadata.get("model_sha256", metadata.get("model_checksum", "")),
                            metadata.get("tracker", ""),
                            track.origin_job_id or "",
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
                for point in interpolate_track(track, video):
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
