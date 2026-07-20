"""Queue track-annotated, trajectory, and heatmap video exports."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job, VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.video_exports import (
    VideoRenderExportRequest,
    VideoRenderExportResponse,
)


class VideoRenderExportService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def queue(
        self,
        video_id: str,
        payload: VideoRenderExportRequest,
    ) -> VideoRenderExportResponse:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        query = select(VideoTrack).where(VideoTrack.video_id == video_id)
        if payload.track_ids:
            query = query.where(VideoTrack.id.in_(payload.track_ids))
        if not payload.include_archived_tracks:
            query = query.where(VideoTrack.status != "archived")
        tracks = list(self.session.scalars(query))
        if payload.track_ids and len(tracks) != len(set(payload.track_ids)):
            raise ValidationError("One or more requested tracks are missing or archived")
        if not tracks:
            raise ValidationError("No tracks are available for this video export")
        total_frames = min(
            video.frame_count,
            payload.maximum_frames or video.frame_count,
        )
        job = Job(
            project_id=video.project_id,
            job_type="video_render_export",
            status="queued",
            progress_total=total_frames,
            max_retries=1,
            resume_supported=False,
            request_json={
                "video_id": video_id,
                "resolved_track_ids": [track.id for track in tracks],
                **payload.model_dump(mode="json"),
            },
            result_json={"stage": "queued"},
            resource_requirements_json={
                "device": "cpu",
                "gpu_required": False,
                "cpu_threads": 2,
                "minimum_ram_bytes": 512 * 1024**2,
                "disk_intensive": True,
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return VideoRenderExportResponse(job=JobResponse.model_validate(job))
