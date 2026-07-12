"""Dataset-version snapshot and export endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.dataset_versions import (
    DatasetExportCreateRequest,
    DatasetExportCreateResponse,
    DatasetVersionComparisonResponse,
    DatasetVersionCreateRequest,
    DatasetVersionItemResponse,
    DatasetVersionManifestResponse,
    DatasetVersionPreviewRequest,
    DatasetVersionPreviewResponse,
    DatasetVersionResponse,
    ExportResponse,
)
from reefvision.services.dataset_versions import DatasetVersionService

router = APIRouter(tags=["dataset_versions"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> DatasetVersionService:
    settings: Settings = request.app.state.settings
    return DatasetVersionService(session, settings)


@router.get("/projects/{project_id}/dataset-versions", response_model=list[DatasetVersionResponse])
def list_dataset_versions(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[DatasetVersionResponse]:
    return service(request, session).list_versions(project_id)


@router.post(
    "/projects/{project_id}/dataset-version-previews",
    response_model=DatasetVersionPreviewResponse,
)
def preview_dataset_version(
    project_id: str,
    payload: DatasetVersionPreviewRequest,
    request: Request,
    session: DbSession,
) -> DatasetVersionPreviewResponse:
    return service(request, session).preview_version(project_id, payload)


@router.post(
    "/projects/{project_id}/dataset-versions",
    response_model=DatasetVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_version(
    project_id: str,
    payload: DatasetVersionCreateRequest,
    request: Request,
    session: DbSession,
) -> DatasetVersionResponse:
    return service(request, session).create_version(project_id, payload)


@router.get("/dataset-versions/{version_id}", response_model=DatasetVersionResponse)
def get_dataset_version(
    version_id: str,
    request: Request,
    session: DbSession,
) -> DatasetVersionResponse:
    return service(request, session).get_version(version_id)


@router.get("/dataset-versions/{version_id}/items", response_model=list[DatasetVersionItemResponse])
def get_dataset_version_items(
    version_id: str,
    request: Request,
    session: DbSession,
) -> list[DatasetVersionItemResponse]:
    return service(request, session).get_version_items(version_id)


@router.get(
    "/dataset-versions/{version_id}/manifest", response_model=DatasetVersionManifestResponse
)
def get_dataset_version_manifest(
    version_id: str,
    request: Request,
    session: DbSession,
) -> DatasetVersionManifestResponse:
    return service(request, session).get_manifest(version_id)


@router.get(
    "/dataset-versions/{version_id}/compare",
    response_model=DatasetVersionComparisonResponse,
)
def compare_dataset_versions(
    version_id: str,
    other_version_id: Annotated[str, Query(min_length=1)],
    request: Request,
    session: DbSession,
) -> DatasetVersionComparisonResponse:
    return service(request, session).compare_versions(version_id, other_version_id)


@router.post(
    "/dataset-versions/{version_id}/exports",
    response_model=DatasetExportCreateResponse,
)
def create_dataset_export(
    version_id: str,
    payload: DatasetExportCreateRequest,
    request: Request,
    session: DbSession,
) -> DatasetExportCreateResponse:
    return service(request, session).create_export(version_id, payload)


@router.get("/projects/{project_id}/exports", response_model=list[ExportResponse])
def list_exports(
    project_id: str,
    request: Request,
    session: DbSession,
    dataset_version_id: str | None = None,
) -> list[ExportResponse]:
    return service(request, session).list_exports(project_id, dataset_version_id=dataset_version_id)


@router.get("/exports/{export_id}", response_model=ExportResponse)
def get_export(export_id: str, request: Request, session: DbSession) -> ExportResponse:
    return service(request, session).get_export(export_id)


@router.get("/exports/{export_id}/download", response_class=FileResponse)
def download_export_archive(
    export_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    export_service = service(request, session)
    export = export_service.get_export(export_id)
    path = export_service.export_archive_path(export_id)
    return FileResponse(path, media_type="application/zip", filename=f"{export.id}.zip")


@router.get("/exports/{export_id}/manifest", response_class=FileResponse)
def download_export_manifest(
    export_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    export_service = service(request, session)
    path = export_service.export_manifest_path(export_id)
    return FileResponse(path, media_type="application/json", filename=f"{export_id}-manifest.json")
