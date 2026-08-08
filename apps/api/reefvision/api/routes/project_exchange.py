"""ReefVision project exchange export and inspection endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.project_exchange import (
    ProjectExchangeCreateRequest,
    ProjectExchangeCreateResponse,
    ProjectExchangeInspectionResponse,
    ProjectExchangePackageResponse,
)
from reefvision.services.project_exchange import ProjectExchangeService
from reefvision.services.project_exchange_inspection import inspect_project_exchange

router = APIRouter(tags=["project-exchange"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ProjectExchangeService:
    return ProjectExchangeService(session, request.app.state.settings)


@router.post(
    "/projects/{project_id}/exchange-packages",
    response_model=ProjectExchangeCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_project_exchange(
    project_id: str,
    payload: ProjectExchangeCreateRequest,
    request: Request,
    session: DbSession,
) -> ProjectExchangeCreateResponse:
    return service(request, session).queue_export(project_id, payload)


@router.get(
    "/projects/{project_id}/exchange-packages",
    response_model=list[ProjectExchangePackageResponse],
)
def list_project_exchanges(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[ProjectExchangePackageResponse]:
    return service(request, session).list_packages(project_id)


@router.get(
    "/exchange-packages/{package_id}",
    response_model=ProjectExchangePackageResponse,
)
def get_project_exchange(
    package_id: str,
    request: Request,
    session: DbSession,
) -> ProjectExchangePackageResponse:
    return service(request, session).get_package(package_id)


@router.get("/exchange-packages/{package_id}/download")
def download_project_exchange(
    package_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    path = service(request, session).archive_path(package_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post(
    "/exchange-packages/inspect",
    response_model=ProjectExchangeInspectionResponse,
)
def inspect_project_exchange_upload(
    file: Annotated[UploadFile, File(...)],
) -> ProjectExchangeInspectionResponse:
    return inspect_project_exchange(file.file)
