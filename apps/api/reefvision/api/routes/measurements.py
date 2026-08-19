"""Scientific mask measurement endpoints."""

from __future__ import annotations

import io
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.image_calibration import (
    ApplyCalibrationProfileRequest,
    CalibrationProfileResponse,
    MarkerCalibrationCandidate,
    MarkerCalibrationDetectRequest,
    RulerCalibrationCandidate,
    RulerCalibrationDetectRequest,
)
from reefvision.schemas.measurements import (
    MaskMeasurementProfileResponse,
    MaskMeasurementProfileUpdate,
    MaskMeasurementResponse,
    MeasurementCalibrationResponse,
    MeasurementCalibrationUpdate,
    ProjectMeasurementSummaryResponse,
)
from reefvision.services.image_scale_calibration import ImageScaleCalibrationService
from reefvision.services.mask_measurements import MaskMeasurementService
from reefvision.services.measurement_analytics import MeasurementAnalyticsService

router = APIRouter(tags=["measurements"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> MaskMeasurementService:
    settings: Settings = request.app.state.settings
    return MaskMeasurementService(session, settings)


def calibration_service(request: Request, session: Session) -> ImageScaleCalibrationService:
    settings: Settings = request.app.state.settings
    return ImageScaleCalibrationService(session, settings)


def analytics_service(request: Request, session: Session) -> MeasurementAnalyticsService:
    settings: Settings = request.app.state.settings
    return MeasurementAnalyticsService(session, settings)


@router.get(
    "/images/{image_id}/measurement-calibration",
    response_model=MeasurementCalibrationResponse | None,
)
def get_measurement_calibration(
    image_id: str,
    request: Request,
    session: DbSession,
) -> MeasurementCalibrationResponse | None:
    return service(request, session).get_calibration(image_id)


@router.put(
    "/images/{image_id}/measurement-calibration",
    response_model=MeasurementCalibrationResponse,
)
def update_measurement_calibration(
    image_id: str,
    payload: MeasurementCalibrationUpdate,
    request: Request,
    session: DbSession,
) -> MeasurementCalibrationResponse:
    prepared = calibration_service(request, session).prepare_saved_calibration(
        image_id, payload
    )
    return service(request, session).update_calibration(image_id, prepared)


@router.post(
    "/images/{image_id}/measurement-calibration/ruler-detect",
    response_model=RulerCalibrationCandidate,
)
def detect_ruler_calibration(
    image_id: str,
    payload: RulerCalibrationDetectRequest,
    request: Request,
    session: DbSession,
) -> RulerCalibrationCandidate:
    return calibration_service(request, session).detect_ruler(image_id, payload)


@router.post(
    "/images/{image_id}/measurement-calibration/marker-detect",
    response_model=MarkerCalibrationCandidate,
)
def detect_marker_calibration(
    image_id: str,
    payload: MarkerCalibrationDetectRequest,
    request: Request,
    session: DbSession,
) -> MarkerCalibrationCandidate:
    return calibration_service(request, session).detect_marker(image_id, payload)


@router.get(
    "/projects/{project_id}/measurement-calibration-profiles",
    response_model=list[CalibrationProfileResponse],
)
def list_measurement_calibration_profiles(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[CalibrationProfileResponse]:
    return calibration_service(request, session).profiles(project_id)


@router.post(
    "/images/{image_id}/measurement-calibration/apply-profile",
    response_model=MeasurementCalibrationResponse,
)
def apply_measurement_calibration_profile(
    image_id: str,
    payload: ApplyCalibrationProfileRequest,
    request: Request,
    session: DbSession,
) -> MeasurementCalibrationResponse:
    return calibration_service(request, session).apply_profile(image_id, payload)


@router.delete(
    "/images/{image_id}/measurement-calibration",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_measurement_calibration(
    image_id: str,
    request: Request,
    session: DbSession,
) -> Response:
    service(request, session).clear_calibration(image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/mask-annotations/{mask_annotation_id}/measurement-profile",
    response_model=MaskMeasurementProfileResponse,
)
def get_mask_measurement_profile(
    mask_annotation_id: str,
    request: Request,
    session: DbSession,
) -> MaskMeasurementProfileResponse:
    return service(request, session).get_profile(mask_annotation_id)


@router.put(
    "/mask-annotations/{mask_annotation_id}/measurement-profile",
    response_model=MaskMeasurementProfileResponse,
)
def update_mask_measurement_profile(
    mask_annotation_id: str,
    payload: MaskMeasurementProfileUpdate,
    request: Request,
    session: DbSession,
) -> MaskMeasurementProfileResponse:
    return service(request, session).update_profile(mask_annotation_id, payload)


@router.get(
    "/mask-annotations/{mask_annotation_id}/measurements",
    response_model=MaskMeasurementResponse,
)
def get_mask_measurements(
    mask_annotation_id: str,
    request: Request,
    session: DbSession,
    label_class_id: Annotated[list[str] | None, Query()] = None,
    scientific_name: Annotated[list[str] | None, Query()] = None,
    state_name: Annotated[list[str] | None, Query()] = None,
) -> MaskMeasurementResponse:
    return service(request, session).measure(
        mask_annotation_id,
        label_class_ids=label_class_id,
        scientific_names=scientific_name,
        state_names=state_name,
    )


@router.get(
    "/projects/{project_id}/measurement-summary",
    response_model=ProjectMeasurementSummaryResponse,
)
def summarize_project_measurements(
    project_id: str,
    request: Request,
    session: DbSession,
    label_class_id: Annotated[list[str] | None, Query()] = None,
    scientific_name: Annotated[list[str] | None, Query()] = None,
    state_name: Annotated[list[str] | None, Query()] = None,
) -> ProjectMeasurementSummaryResponse:
    return analytics_service(request, session).summarize(
        project_id,
        label_class_ids=label_class_id,
        scientific_names=scientific_name,
        state_names=state_name,
    )


@router.get("/projects/{project_id}/measurement-export")
def export_project_measurements(
    project_id: str,
    request: Request,
    session: DbSession,
    export_format: Annotated[Literal["csv", "numpy"], Query(alias="format")] = "csv",
) -> StreamingResponse:
    measurement_service = service(request, session)
    if export_format == "csv":
        content = measurement_service.csv_export(project_id)
        filename = f"reefvision-{project_id}-measurements.csv"
        media_type = "text/csv; charset=utf-8"
    else:
        content = measurement_service.numpy_export(project_id)
        filename = f"reefvision-{project_id}-measurements-numpy.zip"
        media_type = "application/zip"
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
