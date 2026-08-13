"""Managed video import, extraction, track editing, analytics, and tracking routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.videos import (
    VideoAssetResponse,
    VideoExtractRequest,
    VideoTrackAnalyticsResponse,
    VideoTrackCreate,
    VideoTrackingBenchmarkRequest,
    VideoTrackingBenchmarkResponse,
    VideoTrackingCreateRequest,
    VideoTrackingEvaluationRequest,
    VideoTrackingEvaluationResponse,
    VideoTrackInterpolationResponse,
    VideoTrackResponse,
    VideoTrackUpdate,
)
from reefvision.services.video_assets import VideoAssetService
from reefvision.services.video_tracking_benchmark import VideoTrackingBenchmarkService
from reefvision.services.video_tracking_evaluation import VideoTrackingEvaluationService
from reefvision.services.video_tracks import VideoTrackService

router = APIRouter(tags=["videos"])
DbSession = Annotated[Session, Depends(get_db_session)]


def asset_service(request: Request, session: Session) -> VideoAssetService:
    settings: Settings = request.app.state.settings
    return VideoAssetService(session, settings)


@router.post(
    "/projects/{project_id}/imports/videos",
    response_model=VideoAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_video(
    project_id: str,
    request: Request,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> VideoAssetResponse:
    return asset_service(request, session).import_video(
        project_id,
        filename=file.filename,
        stream=file.file,
        media_type=file.content_type,
    )


@router.get("/projects/{project_id}/videos", response_model=list[VideoAssetResponse])
def list_videos(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[VideoAssetResponse]:
    return asset_service(request, session).list(project_id)


@router.get("/videos/{video_id}", response_model=VideoAssetResponse)
def get_video(video_id: str, request: Request, session: DbSession) -> VideoAssetResponse:
    return asset_service(request, session).get(video_id)


@router.get("/videos/{video_id}/content", response_class=FileResponse)
def video_content(video_id: str, request: Request, session: DbSession) -> FileResponse:
    service = asset_service(request, session)
    video = service.get_record(video_id)
    return FileResponse(
        service.content_path(video_id),
        media_type=video.media_type,
        filename=video.original_filename,
        content_disposition_type="inline",
    )


@router.post("/videos/{video_id}/extract", response_model=JobResponse)
def extract_video_frames(
    video_id: str,
    payload: VideoExtractRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    return asset_service(request, session).queue_extraction(video_id, payload)


@router.get("/videos/{video_id}/frames/{frame_index}", response_class=FileResponse)
def video_frame(
    video_id: str,
    frame_index: int,
    request: Request,
    session: DbSession,
) -> FileResponse:
    path = asset_service(request, session).frame_path(video_id, frame_index)
    return FileResponse(
        path,
        media_type="image/jpeg",
        filename=f"frame_{frame_index:08d}.jpg",
        content_disposition_type="inline",
    )


@router.get("/videos/{video_id}/tracks", response_model=list[VideoTrackResponse])
def list_tracks(video_id: str, session: DbSession) -> list[VideoTrackResponse]:
    return VideoTrackService(session).list(video_id)


@router.post(
    "/videos/{video_id}/tracks",
    response_model=VideoTrackResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_track(
    video_id: str,
    payload: VideoTrackCreate,
    session: DbSession,
) -> VideoTrackResponse:
    return VideoTrackService(session).create(video_id, payload)


@router.put("/video-tracks/{track_id}", response_model=VideoTrackResponse)
def update_track(
    track_id: str,
    payload: VideoTrackUpdate,
    session: DbSession,
) -> VideoTrackResponse:
    return VideoTrackService(session).update(track_id, payload)


@router.delete("/video-tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_track(track_id: str, session: DbSession) -> Response:
    VideoTrackService(session).delete(track_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/video-tracks/{track_id}/interpolation",
    response_model=VideoTrackInterpolationResponse,
)
def interpolate_track(
    track_id: str,
    session: DbSession,
) -> VideoTrackInterpolationResponse:
    return VideoTrackService(session).interpolate(track_id)


@router.get(
    "/video-tracks/{track_id}/analytics",
    response_model=VideoTrackAnalyticsResponse,
)
def track_analytics(
    track_id: str,
    session: DbSession,
) -> VideoTrackAnalyticsResponse:
    return VideoTrackService(session).analytics(track_id)


@router.post(
    "/videos/{video_id}/tracking-evaluation",
    response_model=VideoTrackingEvaluationResponse,
)
def evaluate_tracking(
    video_id: str,
    payload: VideoTrackingEvaluationRequest,
    session: DbSession,
) -> VideoTrackingEvaluationResponse:
    return VideoTrackingEvaluationService(session).evaluate(video_id, payload)


@router.post(
    "/videos/{video_id}/tracking-benchmark",
    response_model=VideoTrackingBenchmarkResponse,
)
def benchmark_tracking(
    video_id: str,
    payload: VideoTrackingBenchmarkRequest,
    session: DbSession,
) -> VideoTrackingBenchmarkResponse:
    return VideoTrackingBenchmarkService(session).benchmark(video_id, payload)


@router.post("/videos/{video_id}/tracking-jobs", response_model=JobResponse)
def create_tracking_job(
    video_id: str,
    payload: VideoTrackingCreateRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    video = asset_service(request, session).get_record(video_id)
    model = session.get(ModelRegistration, payload.model_id)
    if model is None or model.project_id != video.project_id:
        raise NotFoundError("Detector model not found in the video project")
    if model.purpose not in {"detector", "segmenter"} or model.task not in {
        "detect",
        "segment",
    }:
        raise ValidationError("Video tracking requires a detection or instance model")
    job = Job(
        project_id=video.project_id,
        job_type="video_tracking",
        status="queued",
        progress_total=video.frame_count,
        request_json={"video_id": video.id, **payload.model_dump()},
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return JobResponse.model_validate(job)
