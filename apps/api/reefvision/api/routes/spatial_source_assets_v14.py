"""Local project-scoped imported 3D source routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.spatial_source_asset_v14 import SpatialSourceAssetResponse
from reefvision.services.spatial_source_assets_v14 import SpatialSourceAssetService

router = APIRouter(tags=["spatial-source-assets"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _service(request: Request, session: Session) -> SpatialSourceAssetService:
    settings: Settings = request.app.state.settings
    return SpatialSourceAssetService(session, settings)


@router.post(
    "/projects/{project_id}/spatial/assets",
    response_model=SpatialSourceAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_spatial_source(
    project_id: str,
    request: Request,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> SpatialSourceAssetResponse:
    record = _service(request, session).import_source(project_id, file.filename, file.file)
    return SpatialSourceAssetResponse.model_validate(record)


@router.get(
    "/projects/{project_id}/spatial/assets",
    response_model=list[SpatialSourceAssetResponse],
)
def list_spatial_sources(
    project_id: str, request: Request, session: DbSession
) -> list[SpatialSourceAssetResponse]:
    return [
        SpatialSourceAssetResponse.model_validate(record)
        for record in _service(request, session).list(project_id)
    ]


@router.get(
    "/projects/{project_id}/spatial/assets/{asset_id}",
    response_model=SpatialSourceAssetResponse,
)
def get_spatial_source(
    project_id: str, asset_id: str, request: Request, session: DbSession
) -> SpatialSourceAssetResponse:
    return SpatialSourceAssetResponse.model_validate(
        _service(request, session).get(project_id, asset_id)
    )


@router.get("/projects/{project_id}/spatial/assets/{asset_id}/content")
def read_spatial_source(
    project_id: str, asset_id: str, request: Request, session: DbSession
) -> Response:
    return Response(
        content=_service(request, session).read_verified(project_id, asset_id),
        media_type="application/octet-stream",
    )
