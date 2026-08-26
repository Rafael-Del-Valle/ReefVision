"""Managed video import, extraction, track editing, analytics, and tracking routes."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.video_track_exchange import (
    VideoTrackExchangeFormat,
    VideoTrackImportResponse,
)
from reefvision.schemas.videos import (
    Scientific3DCalibrationValidationRequest,
    VideoAssetResponse,
    VideoExtractRequest,
    VideoMetricDepth3DCreateRequest,
    VideoTrackAnalyticsResponse,
    VideoTrackCreate,
    VideoTrackingBenchmarkRequest,
    VideoTrackingBenchmarkResponse,
    VideoTrackingCreateRequest,
    VideoTrackingEvaluationRequest,
    VideoTrackingEvaluationResponse,
    VideoTrackingRunResponse,
    VideoTrackInterpolationResponse,
    VideoTrackResponse,
    VideoTrackUpdate,
)
from reefvision.services.scientific_3d_calibration import Scientific3DCalibrationValidationService
from reefvision.services.video_assets import VideoAssetService
from reefvision.services.video_metric_depth_preview import VideoMetricDepthPreviewService
from reefvision.services.video_track_exchange import VideoTrackExchangeService
from reefvision.services.video_tracking_benchmark import VideoTrackingBenchmarkService
from reefvision.services.video_tracking_evaluation import VideoTrackingEvaluationService
from reefvision.services.video_tracking_runs import VideoTrackingRunService
from reefvision.services.video_tracks import VideoTrackService

router = APIRouter(tags=["videos"])
DbSession = Annotated[Session, Depends(get_db_session)]
MAX_TRACK_EXCHANGE_BYTES = 50 * 1024 * 1024


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


@router.get("/videos/{video_id}/tracks/export")
def export_tracks(
    video_id: str,
    session: DbSession,
    exchange_format: Annotated[
        VideoTrackExchangeFormat,
        Query(alias="format"),
    ] = "reefvision_json",
) -> Response:
    payload = VideoTrackExchangeService(session).export(video_id, exchange_format)
    encoded_filename = quote(payload.filename, safe="")
    return Response(
        content=payload.content,
        media_type=payload.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-ReefVision-Track-Format": exchange_format,
        },
    )


@router.post(
    "/videos/{video_id}/tracks/import",
    response_model=VideoTrackImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_tracks(
    video_id: str,
    session: DbSession,
    file: Annotated[UploadFile, File()],
    exchange_format: Annotated[
        VideoTrackExchangeFormat,
        Query(alias="format"),
    ] = "reefvision_json",
    mot_label_class_id: Annotated[
        str | None,
        Query(min_length=1, max_length=100),
    ] = None,
) -> VideoTrackImportResponse:
    raw = file.file.read(MAX_TRACK_EXCHANGE_BYTES + 1)
    if len(raw) > MAX_TRACK_EXCHANGE_BYTES:
        raise ValidationError(
            f"Track exchange upload exceeds {MAX_TRACK_EXCHANGE_BYTES // (1024 * 1024)} MiB"
        )
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("Track exchange files must be UTF-8 text") from exc
    return VideoTrackExchangeService(session).import_text(
        video_id,
        exchange_format,
        content,
        mot_label_class_id=mot_label_class_id,
    )


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


@router.get(
    "/videos/{video_id}/tracking-runs",
    response_model=list[VideoTrackingRunResponse],
)
def list_tracking_runs(
    video_id: str,
    session: DbSession,
) -> list[VideoTrackingRunResponse]:
    return VideoTrackingRunService(session).list(video_id)


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


@router.post(
    "/videos/{video_id}/metric-depth-3d-jobs/{job_id}/calibration-validation",
)
def validate_metric_depth_3d_calibration(
    video_id: str,
    job_id: str,
    payload: Scientific3DCalibrationValidationRequest,
    session: DbSession,
) -> dict[str, object]:
    return Scientific3DCalibrationValidationService(session).validate(
        video_id,
        job_id,
        payload,
    )


@router.get(
    "/videos/{video_id}/metric-depth-3d-jobs/{job_id}/depth-preview",
    response_class=Response,
)
def metric_depth_3d_preview(
    video_id: str,
    job_id: str,
    frame: Annotated[int, Query(ge=0)],
    request: Request,
    session: DbSession,
) -> Response:
    settings: Settings = request.app.state.settings
    preview = VideoMetricDepthPreviewService(session, settings).render(
        video_id,
        job_id,
        frame,
    )
    return Response(
        content=preview.png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-ReefVision-Depth-Frame": str(preview.frame),
            "X-ReefVision-Depth-Min-M": f"{preview.display_min_m:.9g}",
            "X-ReefVision-Depth-Max-M": f"{preview.display_max_m:.9g}",
            "X-ReefVision-Depth-Scaling": preview.scaling,
            "X-ReefVision-Depth-Tier": preview.depth_tier,
        },
    )


@router.post("/videos/{video_id}/metric-depth-3d-jobs", response_model=JobResponse)
def create_metric_depth_3d_job(
    video_id: str,
    payload: VideoMetricDepth3DCreateRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    video = asset_service(request, session).get_record(video_id)
    active_track_ids = {item.id for item in VideoTrackService(session).list(video_id)}
    missing = [track_id for track_id in payload.track_ids if track_id not in active_track_ids]
    if missing:
        raise ValidationError(
            "Scientific 3D tracks must be active and belong to the selected video: "
            + ", ".join(missing)
        )
    from reefvision.services.video_science import VideoScienceService

    VideoScienceService(session).get_camera_intrinsics(video_id)
    job = Job(
        project_id=video.project_id,
        job_type="video_metric_depth_3d",
        status="queued",
        progress_total=video.frame_count,
        request_json={"video_id": video.id, **payload.model_dump()},
        result_json={
            "stage": "queued",
            "depth_tier": "model_estimated_metric",
            "physical_measurement_claim_allowed": False,
        },
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return JobResponse.model_validate(job)


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
