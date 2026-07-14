"""Video frame extraction and sparse track-annotation endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import Job, Project, VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.videos import (
    VideoExtractJobRequest,
    VideoTrackCreateRequest,
    VideoTrackResponse,
)

router = APIRouter(tags=["videos"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/video-extract-jobs",
    response_model=JobResponse,
)
def create_video_extract_job(
    project_id: str,
    payload: VideoExtractJobRequest,
    session: DbSession,
) -> JobResponse:
    if session.get(Project, project_id) is None:
        raise NotFoundError("Project not found")
    if ".." in payload.video_path.replace("\\", "/").split("/"):
        raise ValidationError("video_path must be a managed relative path")
    if ".." in payload.frames_path.replace("\\", "/").split("/"):
        raise ValidationError("frames_path must be a managed relative path")

    job = Job(
        project_id=project_id,
        job_type="video_extract",
        status="queued",
        request_json=payload.model_dump(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return JobResponse.model_validate(job, from_attributes=True)


@router.get(
    "/projects/{project_id}/video-tracks",
    response_model=list[VideoTrackResponse],
)
def list_video_tracks(project_id: str, session: DbSession) -> list[VideoTrackResponse]:
    video_ids = select(VideoAsset.id).where(VideoAsset.project_id == project_id)
    tracks = session.scalars(
        select(VideoTrack)
        .where(VideoTrack.video_id.in_(video_ids))
        .order_by(VideoTrack.video_id, VideoTrack.track_number)
    ).all()
    return [
        VideoTrackResponse(
            id=item.id,
            video_id=item.video_id,
            label_class_id=item.label_class_id,
            track_number=item.track_number,
            geometry_kind=item.geometry_kind,
            keyframes=item.keyframes_json,
            interpolation=item.interpolation,
            status=item.status,
        )
        for item in tracks
    ]


@router.post(
    "/projects/{project_id}/video-tracks",
    response_model=VideoTrackResponse,
)
def create_video_track(
    project_id: str,
    payload: VideoTrackCreateRequest,
    session: DbSession,
) -> VideoTrackResponse:
    video = session.get(VideoAsset, payload.video_id)
    if video is None or video.project_id != project_id:
        raise NotFoundError("Video not found in this project")
    track = VideoTrack(
        video_id=payload.video_id,
        label_class_id=payload.label_class_id,
        track_number=payload.track_number,
        geometry_kind=payload.geometry_kind,
        keyframes_json=payload.keyframes,
        interpolation=payload.interpolation,
    )
    session.add(track)
    session.commit()
    session.refresh(track)
    return VideoTrackResponse(
        id=track.id,
        video_id=track.video_id,
        label_class_id=track.label_class_id,
        track_number=track.track_number,
        geometry_kind=track.geometry_kind,
        keyframes=track.keyframes_json,
        interpolation=track.interpolation,
        status=track.status,
    )
