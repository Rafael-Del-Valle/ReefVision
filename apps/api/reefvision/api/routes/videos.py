"""Managed video, tracking, analytics, and export endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import Job
from reefvision.domain.errors import ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.track_operations import (
    TrackDeleteRequest,
    TrackIdentitySwapRequest,
    TrackMergeRequest,
    TrackObservationAddRequest,
    TrackObservationDeleteRequest,
    TrackObservationReassignRequest,
    TrackObservationRestoreRequest,
    TrackObservationUpdateRequest,
    TrackOperationResponse,
    TrackRestoreRequest,
    TrackSplitRequest,
    VideoTrackEventResponse,
)
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
    VideoZoneCreateRequest,
    VideoZoneResponse,
    VideoZoneUpdateRequest,
)
from reefvision.services.video_behavior import VideoBehaviorAnalysisService
from reefvision.services.video_tracks import VideoTrackCorrectionService
from reefvision.services.video_zones import VideoZoneService
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
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/videos/{video_id}/frames/{frame_index}")
def get_video_frame(
    video_id: str,
    frame_index: int,
    request: Request,
    session: DbSession,
) -> Response:
    video_service = service(request, session)
    video = video_service.get_video(video_id)
    content = video_service.frame_jpeg(video_id, frame_index)
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{video.sha256}-frame-{frame_index}"',
            "X-ReefVision-Frame-Index": str(frame_index),
        },
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
    include_deleted: bool = Query(default=False),
) -> list[VideoTrackResponse]:
    return service(request, session).list_tracks(
        video_id,
        include_deleted=include_deleted,
    )


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


@router.post("/video-tracks/{track_id}/delete", response_model=TrackOperationResponse)
def soft_delete_video_track(
    track_id: str,
    payload: TrackDeleteRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return VideoTrackCorrectionService(session).delete_track(track_id, payload)


@router.post("/video-tracks/{track_id}/restore", response_model=TrackOperationResponse)
def restore_video_track(
    track_id: str,
    payload: TrackRestoreRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return VideoTrackCorrectionService(session).restore_track(track_id, payload)


@router.post(
    "/video-tracks/{track_id}/observations",
    response_model=TrackOperationResponse,
)
def add_video_track_observation(
    track_id: str,
    payload: TrackObservationAddRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return VideoTrackCorrectionService(session).add_observation(track_id, payload)


@router.patch(
    "/video-tracks/{track_id}/observations/{observation_id}",
    response_model=TrackOperationResponse,
)
def update_video_track_observation(
    track_id: str,
    observation_id: str,
    payload: TrackObservationUpdateRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return VideoTrackCorrectionService(session).update_observation(
        track_id,
        observation_id,
        payload,
    )


@router.post(
    "/video-tracks/{track_id}/observations/{observation_id}/delete",
    response_model=TrackOperationResponse,
)
def delete_video_track_observation(
    track_id: str,
    observation_id: str,
    payload: TrackObservationDeleteRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return VideoTrackCorrectionService(session).delete_observation(
        track_id,
        observation_id,
        payload,
    )


@router.post(
    "/video-tracks/{track_id}/observations/{observation_id}/restore",
    response_model=TrackOperationResponse,
)
def restore_video_track_observation(
    track_id: str,
    observation_id: str,
    payload: TrackObservationRestoreRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return VideoTrackCorrectionService(session).restore_observation(
        track_id,
        observation_id,
        payload,
    )


@router.post("/video-tracks/{track_id}/split", response_model=TrackOperationResponse)
def split_video_track(
    track_id: str,
    payload: TrackSplitRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return VideoTrackCorrectionService(session).split_track(track_id, payload)


@router.post("/video-tracks/merge", response_model=TrackOperationResponse)
def merge_video_tracks(
    payload: TrackMergeRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return VideoTrackCorrectionService(session).merge_tracks(payload)


@router.post("/video-tracks/identity-switch", response_model=TrackOperationResponse)
def correct_video_track_identity_switch(
    payload: TrackIdentitySwapRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return VideoTrackCorrectionService(session).identity_swap(payload)


@router.post("/video-tracks/reassign-observations", response_model=TrackOperationResponse)
def reassign_video_track_observations(
    payload: TrackObservationReassignRequest,
    session: DbSession,
) -> TrackOperationResponse:
    return VideoTrackCorrectionService(session).reassign_observations(payload)


@router.get(
    "/video-tracks/{track_id}/events",
    response_model=list[VideoTrackEventResponse],
)
def list_video_track_events(
    track_id: str,
    session: DbSession,
) -> list[VideoTrackEventResponse]:
    return VideoTrackCorrectionService(session).list_events(track_id)


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
    return VideoBehaviorAnalysisService(
        session,
        request.app.state.settings,
    ).analytics(video_id, payload)


@router.get("/videos/{video_id}/analyses", response_model=list[VideoAnalyticsResponse])
def list_video_analyses(
    video_id: str,
    request: Request,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[VideoAnalyticsResponse]:
    return VideoBehaviorAnalysisService(session, request.app.state.settings).list(
        video_id,
        limit=limit,
    )


@router.get("/video-analyses/{analysis_id}", response_model=VideoAnalyticsResponse)
def get_video_analysis(
    analysis_id: str,
    request: Request,
    session: DbSession,
) -> VideoAnalyticsResponse:
    return VideoBehaviorAnalysisService(session, request.app.state.settings).get(analysis_id)


@router.get("/videos/{video_id}/zones", response_model=list[VideoZoneResponse])
def list_video_zones(video_id: str, session: DbSession) -> list[VideoZoneResponse]:
    return VideoZoneService(session).list(video_id)


@router.post(
    "/videos/{video_id}/zones",
    response_model=VideoZoneResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_video_zone(
    video_id: str,
    payload: VideoZoneCreateRequest,
    session: DbSession,
) -> VideoZoneResponse:
    return VideoZoneService(session).create(video_id, payload)


@router.put("/video-zones/{zone_id}", response_model=VideoZoneResponse)
def update_video_zone(
    zone_id: str,
    payload: VideoZoneUpdateRequest,
    session: DbSession,
) -> VideoZoneResponse:
    return VideoZoneService(session).update(zone_id, payload)


@router.delete("/video-zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video_zone(
    zone_id: str,
    session: DbSession,
    expected_revision: int = Query(ge=1),
) -> None:
    VideoZoneService(session).delete(zone_id, expected_revision=expected_revision)


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
