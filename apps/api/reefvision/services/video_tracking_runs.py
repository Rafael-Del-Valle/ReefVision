"""Read-model summaries for persisted video tracking jobs and their active outputs."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job, VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.videos import VideoTrackingRunResponse

VIDEO_TRACKING_STALE_AFTER = timedelta(seconds=120)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _result_int(result: dict[str, object], key: str, default: int = 0) -> int:
    value = result.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _heartbeat_at(result: dict[str, object]) -> datetime | None:
    raw = result.get("heartbeat_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return _as_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


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
        now = datetime.now(UTC)

        for job in jobs:
            request = dict(job.request_json or {})
            result = dict(job.result_json or {})
            unmapped = result.get("unmapped_labels", [])
            heartbeat_at = _heartbeat_at(result)
            stale_reference = heartbeat_at or _as_utc(job.started_at)

            stale = bool(
                job.status in {"running", "cancel_requested"}
                and stale_reference is not None
                and now - stale_reference > VIDEO_TRACKING_STALE_AFTER
            )

            responses.append(
                VideoTrackingRunResponse(
                    job_id=job.id,
                    project_id=video.project_id,
                    video_id=video_id,
                    status=job.status,
                    stage=str(result.get("stage", job.status)),
                    tracker=str(request.get("tracker", "bytetrack.yaml")),
                    model_id=str(request.get("model_id", "")),
                    tracking_mode=str(request.get("tracking_mode", "auto")),
                    segmentation_model_id=request.get("segmentation_model_id"),
                    link_detections=bool(request.get("link_detections", True)),
                    confidence=float(request.get("confidence", 0.25)),
                    iou=float(request.get("iou", 0.5)),
                    device=str(request.get("device", "auto")),
                    minimum_track_frames=max(
                        1,
                        int(request.get("minimum_track_frames", 2)),
                    ),
                    progress_current=job.progress_current,
                    progress_total=job.progress_total,
                    track_count=track_counts[job.id],
                    observation_count=observation_counts[job.id],
                    live_detection_count=_result_int(
                        result,
                        "detection_count",
                    ),
                    live_observation_count=_result_int(
                        result,
                        "tracked_observations_seen",
                        observation_counts[job.id],
                    ),
                    live_tracks_seen=_result_int(
                        result,
                        "tracks_seen",
                        track_counts[job.id],
                    ),
                    heartbeat_at=heartbeat_at,
                    stale=stale,
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
