"""Managed video import, metadata inspection, extraction, and frame access."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import cv2
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job, Project, VideoAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.geospatial.models import TelemetryMetadata
from reefvision.geospatial.synchronization import TelemetrySource
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.videos import VideoAssetResponse, VideoExtractRequest
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.telemetry import (
    find_paired_srt,
    load_dji_srt,
    matching_srt_name,
    open_video_source,
    read_srt_stream,
    remove_srt,
    write_srt,
)

LOGGER = logging.getLogger(__name__)

SUPPORTED_VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}


def _safe_video_name(filename: str | None) -> str:
    name = Path(filename or "video.mp4").name.strip()
    if not name:
        raise ValidationError("Video filename is required")
    suffix = Path(name).suffix.casefold()
    if suffix not in SUPPORTED_VIDEO_EXTENSIONS:
        raise ValidationError("Unsupported video extension; use AVI, M4V, MKV, MOV, MP4, or WebM")
    return name


def _stream_video(source: BinaryIO, destination: Path) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            output.write(chunk)
            size += len(chunk)
    if size == 0:
        destination.unlink(missing_ok=True)
        raise ValidationError("Uploaded video is empty")
    return digest.hexdigest(), size


def _inspect_video(path: Path) -> dict[str, float | int]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValidationError("Uploaded video could not be opened")
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
    finally:
        capture.release()
    if width <= 0 or height <= 0 or frame_count <= 0 or fps <= 0:
        raise ValidationError("Uploaded video metadata is incomplete or unsupported")
    return {
        "width_px": width,
        "height_px": height,
        "frame_count": frame_count,
        "fps": fps,
        "duration_seconds": frame_count / fps,
    }


class VideoAssetService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def get_record(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def get(self, video_id: str) -> VideoAssetResponse:
        return VideoAssetResponse.model_validate(self.get_record(video_id))

    def list(self, project_id: str) -> list[VideoAssetResponse]:
        self._project(project_id)
        statement = (
            select(VideoAsset)
            .where(VideoAsset.project_id == project_id)
            .order_by(VideoAsset.created_at.desc(), VideoAsset.id)
        )
        return [VideoAssetResponse.model_validate(item) for item in self.session.scalars(statement)]

    def import_video(
        self,
        project_id: str,
        *,
        filename: str | None,
        stream: BinaryIO,
        media_type: str | None,
        telemetry_filename: str | None = None,
        telemetry_stream: BinaryIO | None = None,
        source_path: Path | None = None,
    ) -> VideoAssetResponse:
        project = self._project(project_id)
        safe_name = _safe_video_name(filename)
        telemetry, telemetry_data = self._prepare_telemetry(
            safe_name, source_path, telemetry_filename, telemetry_stream
        )
        suffix = Path(safe_name).suffix.casefold()
        staging_relative = f"{project.storage_root}/videos/staging/{uuid4()}.part"
        staging = resolve_managed_project_path(self.settings, staging_relative)
        managed_path: Path | None = None
        telemetry_path: Path | None = None
        try:
            checksum, size = _stream_video(stream, staging)
            duplicate = self.session.scalar(
                select(VideoAsset).where(
                    VideoAsset.project_id == project_id,
                    VideoAsset.sha256 == checksum,
                )
            )
            if duplicate is not None:
                existing = TelemetryMetadata.model_validate(
                    dict(duplicate.metadata_json or {}).get("telemetry", {})
                )
                if telemetry.found and not existing.available:
                    telemetry_path = self._store_telemetry(
                        project, duplicate.id, telemetry, telemetry_data
                    )
                    duplicate.metadata_json = {
                        **dict(duplicate.metadata_json or {}),
                        "telemetry": telemetry.model_dump(mode="json"),
                    }
                    duplicate.revision += 1
                    self.session.commit()
                    self.session.refresh(duplicate)
                staging.unlink(missing_ok=True)
                return VideoAssetResponse.model_validate(duplicate)
            metadata = _inspect_video(staging)
            video_id = str(uuid4())
            relative_managed = f"{project.storage_root}/videos/originals/{video_id}{suffix}"
            managed_path = resolve_managed_project_path(self.settings, relative_managed)
            managed_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging), managed_path)
            telemetry_path = self._store_telemetry(project, video_id, telemetry, telemetry_data)
            video = VideoAsset(
                id=video_id,
                project_id=project_id,
                original_filename=safe_name,
                managed_path=relative_managed,
                sha256=checksum,
                media_type=media_type or "application/octet-stream",
                width_px=int(metadata["width_px"]),
                height_px=int(metadata["height_px"]),
                frame_count=int(metadata["frame_count"]),
                fps=float(metadata["fps"]),
                duration_seconds=float(metadata["duration_seconds"]),
                metadata_json={
                    "file_size_bytes": size,
                    "telemetry": telemetry.model_dump(mode="json"),
                },
                status="imported",
            )
            self.session.add(video)
            self.session.commit()
            self.session.refresh(video)
            return VideoAssetResponse.model_validate(video)
        except Exception:
            self.session.rollback()
            staging.unlink(missing_ok=True)
            if managed_path is not None:
                managed_path.unlink(missing_ok=True)
            if telemetry_path is not None:
                remove_srt(telemetry_path)
            raise

    def _prepare_telemetry(
        self,
        video_name: str,
        source_path: Path | None,
        telemetry_filename: str | None,
        telemetry_stream: BinaryIO | None,
    ) -> tuple[TelemetryMetadata, bytes | None]:
        if telemetry_stream is not None:
            if not matching_srt_name(video_name, telemetry_filename or ""):
                raise ValidationError(
                    "Telemetry must be an SRT with the same filename stem as the video"
                )
            data, source = read_srt_stream(telemetry_stream)
            return TelemetryMetadata(
                found=True,
                available=True,
                source_type="dji_srt",
                path_kind="managed",
                sample_count=len(source.samples),
            ), data
        metadata = TelemetryMetadata()
        if source_path is not None:
            try:
                paired = find_paired_srt(source_path)
                if paired is not None:
                    metadata = TelemetryMetadata(
                        found=True,
                        source_type="dji_srt",
                        source_path=str(paired.resolve()),
                        path_kind="external",
                    )
                    metadata.sample_count = len(load_dji_srt(paired).samples)
                    metadata.available = True
            except ValidationError as exc:
                metadata.error = str(exc)
                LOGGER.warning("Optional video telemetry unavailable: %s", exc)
        return metadata, None

    def _store_telemetry(
        self, project: Project, video_id: str, metadata: TelemetryMetadata, data: bytes | None
    ) -> Path | None:
        if data is None:
            return None
        # Unique names also make rollback safe when enriching a duplicate import.
        relative = f"{project.storage_root}/videos/telemetry/{video_id}-{uuid4()}.srt"
        path = resolve_managed_project_path(self.settings, relative)
        try:
            write_srt(path, data)
        except OSError:
            remove_srt(path)
            raise
        metadata.source_path = relative
        return path

    def import_video_path(self, project_id: str, source_path: Path) -> VideoAssetResponse:
        """Backend local-file import with optional sibling discovery; no dataset assumptions."""
        with open_video_source(source_path) as stream:
            return self.import_video(
                project_id,
                filename=source_path.name,
                stream=stream,
                media_type=None,
                source_path=source_path,
            )

    def telemetry_source(self, video_id: str) -> TelemetrySource | None:
        """Load once per job, then reuse the source for frame lookups.

        Persisted metadata is an import-time snapshot. Missing/moved resources
        return None here so ordinary inference remains independent of telemetry.
        """
        metadata = self.get(video_id).telemetry
        if not metadata.available or metadata.source_path is None:
            return None
        try:
            if metadata.path_kind == "managed":
                path = resolve_managed_project_path(self.settings, metadata.source_path)
            elif metadata.path_kind == "external":
                path = Path(metadata.source_path)
            else:
                return None
            return load_dji_srt(path)
        except ValidationError as exc:
            LOGGER.warning("Video %s telemetry unavailable: %s", video_id, exc)
            return None

    def content_path(self, video_id: str) -> Path:
        video = self.get_record(video_id)
        path = resolve_managed_project_path(self.settings, video.managed_path)
        if not path.is_file():
            raise NotFoundError("Managed video file is missing")
        return path

    def queue_extraction(
        self,
        video_id: str,
        payload: VideoExtractRequest,
    ) -> JobResponse:
        video = self.get_record(video_id)
        project = self._project(video.project_id)
        frames_relative = f"{project.storage_root}/videos/frames/{video.id}"
        job = Job(
            project_id=video.project_id,
            job_type="video_extract",
            status="queued",
            progress_total=max(
                1,
                (video.frame_count + payload.every_n_frames - 1) // payload.every_n_frames,
            ),
            request_json={
                "video_asset_id": video.id,
                "video_path": video.managed_path,
                "frames_path": frames_relative,
                "every_n_frames": payload.every_n_frames,
            },
        )
        self.session.add(job)
        self.session.flush()
        video.frame_directory_path = frames_relative
        video.extraction_job_id = job.id
        video.status = "extracting"
        video.metadata_json = {
            **dict(video.metadata_json or {}),
            "extraction_every_n_frames": payload.every_n_frames,
        }
        video.revision += 1
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)

    def frame_path(self, video_id: str, frame_index: int) -> Path:
        video = self.get_record(video_id)
        if frame_index < 0 or frame_index >= video.frame_count:
            raise NotFoundError("Video frame is outside the source frame range")
        if not video.frame_directory_path:
            raise NotFoundError("Video frames have not been extracted")
        stride = max(1, int(dict(video.metadata_json or {}).get("extraction_every_n_frames", 1)))
        if frame_index % stride != 0:
            raise NotFoundError("Requested frame was not part of the extraction stride")
        path = resolve_managed_project_path(
            self.settings,
            f"{video.frame_directory_path}/frame_{frame_index:08d}.jpg",
        )
        if not path.is_file():
            raise NotFoundError("Requested frame was not extracted")
        return path
