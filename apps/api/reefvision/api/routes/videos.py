"""Managed video import, extraction, track editing, analytics, and tracking routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.pose_interoperability import (
    PoseInteroperabilityFormat,
    PoseInteroperabilityImportResponse,
    PoseInteroperabilityRuntimeResponse,
)
from reefvision.schemas.pose_tracking import (
    PoseAssociationCorrectionRequest,
    PoseIdentityBreakCreateRequest,
    PoseIdentityBreakReviewRequest,
    PoseLandmarkAssociationDecisionResponse,
    PoseLandmarkIdentityBreakResponse,
    PoseTemporalAssociationBuildRequest,
    PoseTemporalBuildResponse,
    PoseTemporalExportFormat,
    PoseTemporalMetricsResponse,
    PoseTemporalQcResponse,
    PoseTemporalTrackSummaryResponse,
)
from reefvision.schemas.pose_visualization import (
    PoseVisualizationExportFormat,
    PoseVisualizationRequest,
    PoseVisualizationResponse,
)
from reefvision.schemas.video_georeferencing_readiness import (
    VideoGeoreferencingReadinessResponse,
)
from reefvision.schemas.video_track_exchange import (
    VideoTrackExchangeFormat,
    VideoTrackImportResponse,
)
from reefvision.schemas.videos import (
    AnnotatedVideoExportCreateRequest,
    Scientific3DCalibrationValidationRequest,
    VideoAssetResponse,
    VideoExtractRequest,
    VideoFrameSpatialMetricsResponse,
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
from reefvision.services.pose_interoperability import PoseInteroperabilityService
from reefvision.services.pose_temporal_tracking import PoseTemporalTrackingService
from reefvision.services.pose_visualization import PoseVisualizationService
from reefvision.services.scientific_3d_calibration import Scientific3DCalibrationValidationService
from reefvision.services.video_assets import VideoAssetService
from reefvision.services.video_georeferencing_readiness import (
    VideoGeoreferencingReadinessService,
)
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
    telemetry_file: Annotated[UploadFile | None, File()] = None,
    airdata_file: Annotated[UploadFile | None, File()] = None,
    airdata_time_offset_s: Annotated[float, Form()] = 0.0,
    airdata_time_offset_evidence: Annotated[str | None, Form()] = None,
) -> VideoAssetResponse:
    return asset_service(request, session).import_video(
        project_id,
        filename=file.filename,
        stream=file.file,
        media_type=file.content_type,
        telemetry_filename=telemetry_file.filename if telemetry_file is not None else None,
        telemetry_stream=telemetry_file.file if telemetry_file is not None else None,
        airdata_filename=airdata_file.filename if airdata_file is not None else None,
        airdata_stream=airdata_file.file if airdata_file is not None else None,
        airdata_time_offset_s=airdata_time_offset_s,
        airdata_time_offset_evidence=airdata_time_offset_evidence,
    )


@router.post(
    "/projects/{project_id}/imports/videos/path",
    response_model=VideoAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_video_path(
    project_id: str,
    request: Request,
    session: DbSession,
    source_path: Annotated[str, Form()],
) -> VideoAssetResponse:
    path = Path(source_path).expanduser()

    if not path.is_absolute():
        raise ValidationError("Desktop video source path must be absolute")

    if not path.is_file():
        raise ValidationError("Desktop video source path does not exist")

    return asset_service(request, session).import_video_path(
        project_id,
        path,
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


@router.get(
    "/videos/{video_id}/georeferencing-readiness",
    response_model=VideoGeoreferencingReadinessResponse,
)
def georeferencing_readiness(
    video_id: str,
    request: Request,
    session: DbSession,
) -> VideoGeoreferencingReadinessResponse:
    settings: Settings = request.app.state.settings
    return VideoGeoreferencingReadinessService(session, settings).evaluate(video_id)


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


@router.delete("/videos/{video_id}/tracks")
def delete_video_tracks(
    video_id: str,
    session: DbSession,
    machine_only: Annotated[bool, Query()] = True,
) -> dict[str, int]:
    deleted = VideoTrackService(session).delete_for_video(
        video_id,
        machine_only=machine_only,
    )
    return {"deleted_tracks": deleted}


@router.get(
    "/videos/{video_id}/spatial-metrics",
    response_model=VideoFrameSpatialMetricsResponse,
)
def frame_spatial_metrics(
    video_id: str,
    session: DbSession,
    frame: Annotated[int, Query(ge=0)],
) -> VideoFrameSpatialMetricsResponse:
    return VideoTrackService(session).frame_spatial_metrics(video_id, frame)


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


@router.post(
    "/video-tracks/{track_id}/pose-temporal-associations",
    response_model=PoseTemporalBuildResponse,
)
def build_pose_temporal_associations(
    track_id: str,
    payload: PoseTemporalAssociationBuildRequest,
    session: DbSession,
) -> PoseTemporalBuildResponse:
    return PoseTemporalTrackingService(session).build(track_id, payload)


@router.get(
    "/video-tracks/{track_id}/pose-temporal",
    response_model=PoseTemporalTrackSummaryResponse,
)
def get_pose_temporal_summary(
    track_id: str,
    session: DbSession,
) -> PoseTemporalTrackSummaryResponse:
    return PoseTemporalTrackingService(session).summary(track_id)


@router.post(
    "/video-tracks/{track_id}/pose-visualization",
    response_model=PoseVisualizationResponse,
)
def get_pose_visualization(
    track_id: str,
    payload: PoseVisualizationRequest,
    session: DbSession,
) -> PoseVisualizationResponse:
    return PoseVisualizationService(session).analyze(track_id, payload)


@router.get("/video-tracks/{track_id}/pose-visualization/export")
def export_pose_visualization(
    track_id: str,
    session: DbSession,
    export_format: Annotated[
        PoseVisualizationExportFormat,
        Query(alias="format"),
    ] = "json",
    grid_rows: Annotated[int, Query(ge=1, le=100)] = 24,
    grid_columns: Annotated[int, Query(ge=1, le=100)] = 24,
    start_frame: Annotated[int | None, Query(ge=0)] = None,
    end_frame: Annotated[int | None, Query(ge=0)] = None,
    include_predicted: bool = False,
    include_uncertain: bool = True,
    minimum_landmark_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
) -> Response:
    if start_frame is not None and end_frame is not None and end_frame < start_frame:
        raise ValidationError("Pose visualization end frame must be at or after the start frame")
    request_payload = PoseVisualizationRequest(
        grid_rows=grid_rows,
        grid_columns=grid_columns,
        start_frame=start_frame,
        end_frame=end_frame,
        include_predicted=include_predicted,
        include_uncertain=include_uncertain,
        minimum_landmark_confidence=minimum_landmark_confidence,
    )
    payload = PoseVisualizationService(session).export(
        track_id,
        request_payload,
        export_format,
    )
    encoded_filename = quote(payload.filename, safe="")
    return Response(
        content=payload.content,
        media_type=payload.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-ReefVision-Pose-Visualization-Format": export_format,
        },
    )


@router.get(
    "/video-tracks/{track_id}/pose-temporal/qc",
    response_model=PoseTemporalQcResponse,
)
def get_pose_temporal_qc(
    track_id: str,
    session: DbSession,
    association_confidence_threshold: Annotated[float, Query(ge=0, le=1)] = 0.60,
    landmark_confidence_threshold: Annotated[float, Query(ge=0, le=1)] = 0.50,
    motion_cost_threshold: Annotated[float, Query(ge=0)] = 0.25,
) -> PoseTemporalQcResponse:
    return PoseTemporalTrackingService(session).qc(
        track_id,
        association_confidence_threshold=association_confidence_threshold,
        landmark_confidence_threshold=landmark_confidence_threshold,
        motion_cost_threshold=motion_cost_threshold,
    )


@router.get(
    "/video-tracks/{track_id}/pose-temporal/metrics",
    response_model=PoseTemporalMetricsResponse,
)
def get_pose_temporal_metrics(
    track_id: str,
    session: DbSession,
) -> PoseTemporalMetricsResponse:
    return PoseTemporalTrackingService(session).metrics(track_id)


@router.get("/video-tracks/{track_id}/pose-temporal/export")
def export_pose_temporal(
    track_id: str,
    session: DbSession,
    export_format: Annotated[
        PoseTemporalExportFormat,
        Query(alias="format"),
    ] = "csv",
) -> Response:
    payload = PoseTemporalTrackingService(session).export(track_id, export_format)
    encoded_filename = quote(payload.filename, safe="")
    return Response(
        content=payload.content,
        media_type=payload.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-ReefVision-Pose-Format": export_format,
        },
    )


@router.get("/pose-interoperability/runtime", response_model=PoseInteroperabilityRuntimeResponse)
def pose_interoperability_runtime() -> PoseInteroperabilityRuntimeResponse:
    return PoseInteroperabilityService.runtime_status()


@router.get("/videos/{video_id}/pose-interoperability/export")
def export_pose_interoperability(
    video_id: str,
    request: Request,
    session: DbSession,
    exchange_format: Annotated[
        PoseInteroperabilityFormat,
        Query(alias="format"),
    ] = "slp",
) -> Response:
    settings: Settings = request.app.state.settings
    payload = PoseInteroperabilityService(session, settings).export(
        video_id,
        exchange_format,
    )
    encoded_filename = quote(payload.filename, safe="")
    return Response(
        content=payload.content,
        media_type=payload.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-ReefVision-Pose-Interoperability-Format": exchange_format,
            "X-ReefVision-Pose-Lossy": "true" if payload.lossy else "false",
        },
    )


@router.post(
    "/videos/{video_id}/pose-interoperability/import",
    response_model=PoseInteroperabilityImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_pose_interoperability(
    video_id: str,
    request: Request,
    session: DbSession,
    file: Annotated[UploadFile, File()],
    exchange_format: Annotated[
        PoseInteroperabilityFormat,
        Query(alias="format"),
    ],
    label_class_id: Annotated[str, Query(min_length=1, max_length=36)],
    confirm_frame_mapping: Annotated[bool, Query()] = False,
) -> PoseInteroperabilityImportResponse:
    raw = file.file.read(200 * 1024 * 1024 + 1)
    if len(raw) > 200 * 1024 * 1024:
        raise ValidationError("Pose interoperability upload exceeds 200 MiB")
    settings: Settings = request.app.state.settings
    return PoseInteroperabilityService(session, settings).import_bytes(
        video_id,
        exchange_format,
        raw,
        source_filename=file.filename,
        label_class_id=label_class_id,
        confirm_frame_mapping=confirm_frame_mapping,
    )


@router.post(
    "/pose-landmark-observations/{observation_id}/association-corrections",
    response_model=PoseLandmarkAssociationDecisionResponse,
)
def correct_pose_landmark_association(
    observation_id: str,
    payload: PoseAssociationCorrectionRequest,
    session: DbSession,
) -> PoseLandmarkAssociationDecisionResponse:
    return PoseTemporalTrackingService(session).correct_association(
        observation_id,
        payload,
    )


@router.post(
    "/pose-landmark-tracks/{landmark_track_id}/identity-breaks",
    response_model=PoseLandmarkIdentityBreakResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_pose_identity_break(
    landmark_track_id: str,
    payload: PoseIdentityBreakCreateRequest,
    session: DbSession,
) -> PoseLandmarkIdentityBreakResponse:
    return PoseTemporalTrackingService(session).create_identity_break(
        landmark_track_id,
        payload,
    )


@router.post(
    "/pose-landmark-identity-breaks/{identity_break_id}/review",
    response_model=PoseLandmarkIdentityBreakResponse,
)
def review_pose_identity_break(
    identity_break_id: str,
    payload: PoseIdentityBreakReviewRequest,
    session: DbSession,
) -> PoseLandmarkIdentityBreakResponse:
    return PoseTemporalTrackingService(session).review_identity_break(
        identity_break_id,
        payload,
    )


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


@router.get(
    "/videos/{video_id}/annotated-video-exports",
    response_model=list[JobResponse],
)
def list_annotated_video_exports(
    video_id: str,
    request: Request,
    session: DbSession,
) -> list[JobResponse]:
    video = asset_service(request, session).get_record(video_id)
    jobs = list(
        session.scalars(
            select(Job)
            .where(
                Job.project_id == video.project_id,
                Job.job_type == "video_annotated_export",
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
        )
    )
    return [
        JobResponse.model_validate(job)
        for job in jobs
        if str((job.request_json or {}).get("video_id") or "") == video_id
    ]


@router.post(
    "/videos/{video_id}/annotated-video-exports",
    response_model=JobResponse,
)
def create_annotated_video_export(
    video_id: str,
    payload: AnnotatedVideoExportCreateRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    video = asset_service(request, session).get_record(video_id)
    source_job = session.get(Job, payload.source_tracking_job_id)
    if (
        source_job is None
        or source_job.job_type != "video_tracking"
        or source_job.project_id != video.project_id
        or source_job.status != "succeeded"
        or str((source_job.request_json or {}).get("video_id") or "") != video.id
    ):
        raise ValidationError(
            "Annotated video export requires a succeeded tracking run for the selected video"
        )

    job = Job(
        project_id=video.project_id,
        job_type="video_annotated_export",
        status="queued",
        progress_total=video.frame_count,
        request_json={"video_id": video.id, **payload.model_dump()},
        result_json={
            "stage": "queued",
            "video_id": video.id,
            "source_tracking_job_id": payload.source_tracking_job_id,
            "preset": payload.preset,
        },
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return JobResponse.model_validate(job)


@router.get(
    "/video-annotated-exports/{job_id}/content",
    response_class=FileResponse,
)
def annotated_video_export_content(
    job_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    job = session.get(Job, job_id)
    if job is None or job.job_type != "video_annotated_export":
        raise NotFoundError("Annotated video export not found")
    if job.status != "succeeded":
        raise ValidationError("Annotated video export is not ready for download")
    result = dict(job.result_json or {})
    output_path = result.get("output_path")
    if not isinstance(output_path, str) or not output_path:
        raise NotFoundError("Annotated video export file is missing")
    settings: Settings = request.app.state.settings
    from reefvision.storage.projects import resolve_managed_project_path

    path = resolve_managed_project_path(settings, output_path)
    if not path.is_file():
        raise NotFoundError("Annotated video export file is missing")
    filename = result.get("filename")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=filename if isinstance(filename, str) else path.name,
    )


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
        "pose",
    }:
        raise ValidationError("Video tracking requires a detection, instance, or pose model")
    if payload.tracking_mode in {"detect", "hybrid"} and model.task != "detect":
        raise ValidationError("Detection and hybrid tracking require a detection model")
    if payload.tracking_mode == "segment" and model.task != "segment":
        raise ValidationError("Segmentation tracking requires an instance-segmentation model")
    if payload.tracking_mode == "hybrid":
        secondary = session.get(ModelRegistration, payload.segmentation_model_id)
        if (
            secondary is None
            or secondary.project_id != video.project_id
            or secondary.task != "segment"
            or secondary.purpose != "segmenter"
            or secondary.provider_name != "ultralytics"
            or model.provider_name != "ultralytics"
        ):
            raise ValidationError(
                "Hybrid tracking requires an Ultralytics detector and segmentation model "
                "registered in the same project"
            )

        def mapped_classes(registration: ModelRegistration) -> set[str]:
            raw = dict(registration.class_map_json or {})
            mapping = raw.get("mapping")
            if isinstance(mapping, dict):
                return {str(value) for value in mapping.values() if value}
            provider_classes = raw.get("provider_classes")
            if isinstance(provider_classes, dict):
                return {
                    str(metadata["label_class_id"])
                    for metadata in provider_classes.values()
                    if isinstance(metadata, dict) and metadata.get("label_class_id")
                }
            return set()

        detector_classes = mapped_classes(model)
        segmenter_classes = mapped_classes(secondary)
        if not detector_classes.intersection(segmenter_classes):
            raise ValidationError(
                "Hybrid tracking models must map at least one class to the same project label"
            )
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


@router.post("/videos/{video_id}/georeference-tracks")
def georeference_existing_video_tracks(
    video_id: str,
    request: Request,
    session: DbSession,
) -> dict[str, object]:
    """Recompute geographic observations for active video tracks."""

    from sqlalchemy import select

    from reefvision.db.models import VideoTrack
    from reefvision.schemas.georeferenced_observation import BoundingBoxPixels
    from reefvision.services.georeferenced_observations import (
        GeoReferencedObservationService,
    )
    from reefvision.services.video_georeferencing import VideoGeoreferencingService
    from reefvision.services.video_georeferencing_readiness import (
        VideoGeoreferencingReadinessService,
    )

    settings: Settings = request.app.state.settings
    readiness = VideoGeoreferencingReadinessService(session, settings).evaluate(video_id)
    if not readiness.ready:
        blockers = "; ".join(issue.message for issue in readiness.issues)
        raise ValidationError("Georeferencing is not ready" + (f": {blockers}" if blockers else ""))

    tracks = list(
        session.scalars(
            select(VideoTrack)
            .where(
                VideoTrack.video_id == video_id,
                VideoTrack.deleted_at.is_(None),
            )
            .order_by(VideoTrack.track_number, VideoTrack.created_at, VideoTrack.id)
        )
    )
    if not tracks:
        raise ValidationError("No active video tracks are available to georeference")

    service = VideoGeoreferencingService(session, settings)
    persistence = GeoReferencedObservationService(session)
    configuration_hash = service.configuration_hash(video_id)

    persistence.delete_for_tracks(str(track.id) for track in tracks)

    attempted = 0
    succeeded = 0
    skipped_zoom_mismatch = 0
    failed = 0

    for track in tracks:
        for raw in list(track.keyframes_json or []):
            attempted += 1
            try:
                frame = int(raw["frame"])
                bbox = raw["bbox"]
                if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    raise ValidationError("Track keyframe bbox must contain x, y, width, height")
                x, y, width, height = (float(value) for value in bbox)
                if width <= 0 or height <= 0:
                    raise ValidationError("Track keyframe bbox requires positive dimensions")

                observation = service.georeference_detection(
                    video_id,
                    frame_index=frame,
                    bbox=BoundingBoxPixels(
                        x_min=x,
                        y_min=y,
                        x_max=x + width,
                        y_max=y + height,
                    ),
                    track_id=str(track.id),
                )
                persistence.persist(
                    observation,
                    configuration_hash=configuration_hash,
                )
            except ValidationError as exc:
                if "zoom does not match" in str(exc).casefold():
                    skipped_zoom_mismatch += 1
                else:
                    failed += 1
            except (KeyError, TypeError, ValueError):
                failed += 1
            else:
                succeeded += 1

    session.commit()
    return {
        "video_id": video_id,
        "track_count": len(tracks),
        "attempted_count": attempted,
        "georeferenced_observation_count": succeeded,
        "skipped_zoom_mismatch_count": skipped_zoom_mismatch,
        "failure_count": failed,
        "configuration_hash": configuration_hash,
    }
