"""Authenticated local project sources and immutable acquisition receipts."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.acquisition_source import (
    AcquisitionCapturePage,
    AcquisitionCaptureReceipt,
    AcquisitionCaptureRequest,
    AcquisitionDispatch,
    AcquisitionSourceCreate,
    AcquisitionSourcePage,
    AcquisitionSourceResponse,
    AcquisitionStateChange,
)
from reefvision.services.acquisition_sources import AcquisitionSourceService

router = APIRouter(prefix="/projects/{project_id}/acquisition-sources", tags=["acquisition"])


def _service(
    request: Request, session: Annotated[Session, Depends(get_db_session)]
) -> AcquisitionSourceService:
    return AcquisitionSourceService(session, request.app.state.settings)


Service = Annotated[AcquisitionSourceService, Depends(_service)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("", response_model=AcquisitionSourcePage)
def list_sources(
    project_id: UUID, service: Service, page: Page = 1, page_size: PageSize = 25
) -> AcquisitionSourcePage:
    return service.list_sources(str(project_id), page, page_size)


@router.post("", response_model=AcquisitionSourceResponse, status_code=201)
def create_source(
    project_id: UUID, payload: AcquisitionSourceCreate, service: Service
) -> AcquisitionSourceResponse:
    return service.create(str(project_id), payload)


@router.get("/{source_id}", response_model=AcquisitionSourceResponse)
def get_source(project_id: UUID, source_id: UUID, service: Service) -> AcquisitionSourceResponse:
    return service.read_source(str(project_id), str(source_id))


@router.patch("/{source_id}/state", response_model=AcquisitionSourceResponse)
def change_source_state(
    project_id: UUID, source_id: UUID, payload: AcquisitionStateChange, service: Service
) -> AcquisitionSourceResponse:
    return service.change_state(str(project_id), str(source_id), payload)


@router.post("/{source_id}/captures", response_model=AcquisitionCaptureReceipt)
def capture_one(
    project_id: UUID, source_id: UUID, payload: AcquisitionCaptureRequest, service: Service
) -> AcquisitionCaptureReceipt:
    return service.capture(
        str(project_id),
        str(source_id),
        payload.source_sha256,
        f"manual:{payload.capture_key}",
        AcquisitionDispatch(kind="manual"),
        confirm_camera=payload.confirm_camera,
    )


@router.get("/{source_id}/captures", response_model=AcquisitionCapturePage)
def list_captures(
    project_id: UUID, source_id: UUID, service: Service, page: Page = 1, page_size: PageSize = 25
) -> AcquisitionCapturePage:
    return service.list_captures(str(project_id), str(source_id), page, page_size)


@router.get("/{source_id}/captures/{capture_id}", response_model=AcquisitionCaptureReceipt)
def get_capture(
    project_id: UUID, source_id: UUID, capture_id: UUID, service: Service
) -> AcquisitionCaptureReceipt:
    return service.get_capture(str(project_id), str(capture_id), source_id=str(source_id))
