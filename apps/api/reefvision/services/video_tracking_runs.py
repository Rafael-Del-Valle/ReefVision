"""Read-model summaries for persisted video tracking jobs and their active outputs."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job, VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.videos import VideoTrackingRunResponse


class VideoTrackingRunService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, video_id: str) -> list[VideoTrackingRunResponse]:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")

        jobs = list(
            self.session.scalars(
                select(Job)
                .where(
                    Job.project_id == video.project_id,
                    Job.job_type == "video_tracking",
                )
                .order_by(Job.created_at.desc(), Job.id.desc())
            )
        )
        jobs = [
            job for job in jobs if str(dict(job.request_json or {}).get("video_id", "")) == video_id
        ]
        if not jobs:
            return []

        job_ids = [job.id for job in jobs]
        tracks = list(
            self.session.scalars(
                select(VideoTrack).where(
                    VideoTrack.video_id == video_id,
                    VideoTrack.source_job_id.in_(job_ids),
                    VideoTrack.deleted_at.is_(None),
                )
            )
        )
        track_counts: dict[str, int] = defaultdict(int)
        observation_counts: dict[str, int] = defaultdict(int)
        for track in tracks:
            if track.source_job_id is None:
                continue
            track_counts[track.source_job_id] += 1
            observation_counts[track.source_job_id] += len(track.keyframes_json or [])

        responses: list[VideoTrackingRunResponse] = []
        for job in jobs:
            request = dict(job.request_json or {})
            result = dict(job.result_json or {})
            unmapped = result.get("unmapped_labels", [])
            responses.append(
                VideoTrackingRunResponse(
                    job_id=job.id,
                    project_id=video.project_id,
                    video_id=video_id,
                    status=job.status,
                    tracker=str(request.get("tracker", "bytetrack.yaml")),
                    model_id=str(request.get("model_id", "")),
                    confidence=float(request.get("confidence", 0.25)),
                    iou=float(request.get("iou", 0.5)),
                    device=str(request.get("device", "auto")),
                    minimum_track_frames=max(
                        1,
                        int(request.get("minimum_track_frames", 2)),
                    ),
                    track_count=track_counts[job.id],
                    observation_count=observation_counts[job.id],
                    unmapped_labels=(
                        [str(item) for item in unmapped] if isinstance(unmapped, list) else []
                    ),
                    error_message=job.error_message,
                    created_at=job.created_at,
                    started_at=job.started_at,
                    completed_at=job.completed_at,
                )
            )
        return responses
