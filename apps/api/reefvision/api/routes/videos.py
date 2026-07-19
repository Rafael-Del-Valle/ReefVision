"""Managed video, tracking, analytics, and export endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import Job
from reefvision.domain.errors import ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.videos import (
    VideoAnalyticsRequest,
    VideoAnalyticsResponse,
    VideoAssetResponse,
    VideoCalibrationUpdate,
    VideoExtractJobRequest,
    VideoImportResponse,
    VideoTrackCreateRequest,
    VideoTrackingJobRequest,
    VideoTrackResponse,
    VideoTrackUpdateRequest,
)
from reefvision.services.videos import VideoService

router = APIRouter(tags=["videos"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> VideoService:
    return VideoService(session, request.app.state.settings)


@router.post(
    "/projects/{project_id}/imports/videos",
    response_model=VideoImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_video(
    project_id: str,
    request: Request,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> VideoImportResponse:
    return service(request, session).import_video(
        project_id,
        filename=file.filename,
        media_type=file.content_type,
        stream=file.file,
    )


@router.get("/projects/{project_id}/videos", response_model=list[VideoAssetResponse])
def list_videos(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[VideoAssetResponse]:
    return service(request, session).list_videos(project_id)


@router.get("/videos/{video_id}", response_model=VideoAssetResponse)
def get_video(
    video_id: str,
    request: Request,
    session: DbSession,
) -> VideoAssetResponse:
    return service(request, session).get_video(video_id)


@router.get("/videos/{video_id}/content", response_class=FileResponse)
def get_video_content(
    video_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    video_service = service(request, session)
    video = video_service.get_video(video_id)
    return FileResponse(
        video_service.video_path(video_id),
        media_type=video.media_type,
        filename=video.original_filename,
    )


@router.delete("/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video(
    video_id: str,
    request: Request,
    session: DbSession,
) -> None:
    service(request, session).delete_video(video_id)


@router.put("/videos/{video_id}/calibration", response_model=VideoAssetResponse)
def update_video_calibration(
    video_id: str,
    payload: VideoCalibrationUpdate,
    request: Request,
    session: DbSession,
) -> VideoAssetResponse:
    return service(request, session).update_calibration(video_id, payload)


@router.post(
    "/projects/{project_id}/video-extract-jobs",
    response_model=JobResponse,
)
def create_video_extract_job(
    project_id: str,
    payload: VideoExtractJobRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    service(request, session)._project(project_id)
    if ".." in payload.video_path.replace("\\", "/").split("/"):
        raise ValidationError("video_path must be a managed relative path")
    if ".." in payload.frames_path.replace("\\", "/").split("/"):
        raise ValidationError("frames_path must be a managed relative path")
    job = Job(
        project_id=project_id,
        job_type="video_extract",
        status="queued",
        request_json=payload.model_dump(mode="json"),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return JobResponse.model_validate(job)


@router.get("/videos/{video_id}/tracks", response_model=list[VideoTrackResponse])
def list_video_tracks(
    video_id: str,
    request: Request,
    session: DbSession,
) -> list[VideoTrackResponse]:
    return service(request, session).list_tracks(video_id)


@router.post(
    "/videos/{video_id}/tracks",
    response_model=VideoTrackResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_video_track(
    video_id: str,
    payload: VideoTrackCreateRequest,
    request: Request,
    session: DbSession,
) -> VideoTrackResponse:
    return service(request, session).create_track(video_id, payload)


@router.patch("/video-tracks/{track_id}", response_model=VideoTrackResponse)
def update_video_track(
    track_id: str,
    payload: VideoTrackUpdateRequest,
    request: Request,
    session: DbSession,
) -> VideoTrackResponse:
    return service(request, session).update_track(track_id, payload)


@router.delete("/video-tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video_track(
    track_id: str,
    request: Request,
    session: DbSession,
) -> None:
    service(request, session).delete_track(track_id)


@router.post(
    "/videos/{video_id}/tracking-jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_video_tracking_job(
    video_id: str,
    payload: VideoTrackingJobRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    return service(request, session).create_tracking_job(video_id, payload)


@router.post("/videos/{video_id}/analytics", response_model=VideoAnalyticsResponse)
def analyze_video_tracks(
    video_id: str,
    payload: VideoAnalyticsRequest,
    request: Request,
    session: DbSession,
) -> VideoAnalyticsResponse:
    return service(request, session).analytics(video_id, payload)


@router.get("/videos/{video_id}/tracking-export")
def export_video_tracks(
    video_id: str,
    request: Request,
    session: DbSession,
    export_format: Annotated[
        Literal["csv", "mot", "json"],
        Query(alias="format"),
    ] = "csv",
) -> Response:
    content, media_type, filename = service(request, session).export_tracks(
        video_id,
        export_format,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
