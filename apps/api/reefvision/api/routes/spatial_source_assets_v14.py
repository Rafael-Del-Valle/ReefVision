"""Local project-scoped imported 3D source routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.spatial_asset_metadata_revision_v14 import (
    SpatialAssetMetadataRevisionCreate,
    SpatialAssetMetadataRevisionResponse,
)
from reefvision.schemas.spatial_calibration_review_v14 import (
    SpatialCalibrationReviewCreate,
    SpatialCalibrationReviewResponse,
)
from reefvision.schemas.spatial_source_asset_v14 import SpatialSourceAssetResponse
from reefvision.services.spatial_asset_metadata_revisions_v14 import (
    SpatialAssetMetadataRevisionService,
)
from reefvision.services.spatial_calibration_review_v14 import SpatialCalibrationReviewService
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
    service = _service(request, session)
    record = service.import_source(project_id, file.filename, file.file)
    return service.response(record)


@router.get(
    "/projects/{project_id}/spatial/assets",
    response_model=list[SpatialSourceAssetResponse],
)
def list_spatial_sources(
    project_id: str, request: Request, session: DbSession
) -> list[SpatialSourceAssetResponse]:
    service = _service(request, session)
    return [service.response(record) for record in service.list(project_id)]


@router.get(
    "/projects/{project_id}/spatial/assets/{asset_id}",
    response_model=SpatialSourceAssetResponse,
)
def get_spatial_source(
    project_id: str, asset_id: str, request: Request, session: DbSession
) -> SpatialSourceAssetResponse:
    service = _service(request, session)
    return service.response(service.get(project_id, asset_id))


@router.get("/projects/{project_id}/spatial/assets/{asset_id}/content")
def read_spatial_source(
    project_id: str, asset_id: str, request: Request, session: DbSession
) -> Response:
    return Response(
        content=_service(request, session).read_verified(project_id, asset_id),
        media_type="application/octet-stream",
    )


def _review_service(request: Request, session: Session) -> SpatialCalibrationReviewService:
    settings: Settings = request.app.state.settings
    return SpatialCalibrationReviewService(session, settings)


@router.post(
    "/projects/{project_id}/spatial/assets/{asset_id}/calibration-reviews",
    response_model=SpatialCalibrationReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_spatial_calibration_review(
    project_id: str,
    asset_id: str,
    payload: SpatialCalibrationReviewCreate,
    request: Request,
    session: DbSession,
) -> SpatialCalibrationReviewResponse:
    return _review_service(request, session).create(project_id, asset_id, payload.evidence)


@router.get(
    "/projects/{project_id}/spatial/assets/{asset_id}/calibration-reviews",
    response_model=list[SpatialCalibrationReviewResponse],
)
def list_spatial_calibration_reviews(
    project_id: str,
    asset_id: str,
    request: Request,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    after_review_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> list[SpatialCalibrationReviewResponse]:
    return _review_service(request, session).list(
        project_id,
        asset_id,
        limit=limit,
        offset=offset,
        after_review_id=after_review_id,
    )


@router.get(
    "/projects/{project_id}/spatial/assets/{asset_id}/calibration-reviews/{review_id}",
    response_model=SpatialCalibrationReviewResponse,
)
def get_spatial_calibration_review(
    project_id: str,
    asset_id: str,
    review_id: str,
    request: Request,
    session: DbSession,
) -> SpatialCalibrationReviewResponse:
    return _review_service(request, session).get(project_id, asset_id, review_id)


def _metadata_service(request: Request, session: Session) -> SpatialAssetMetadataRevisionService:
    settings: Settings = request.app.state.settings
    return SpatialAssetMetadataRevisionService(session, settings)


@router.post(
    "/projects/{project_id}/spatial/assets/{asset_id}/metadata-revisions",
    response_model=SpatialAssetMetadataRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_spatial_asset_metadata_revision(
    project_id: str,
    asset_id: str,
    payload: SpatialAssetMetadataRevisionCreate,
    request: Request,
    session: DbSession,
) -> SpatialAssetMetadataRevisionResponse:
    return _metadata_service(request, session).create(project_id, asset_id, payload)


@router.get(
    "/projects/{project_id}/spatial/assets/{asset_id}/metadata-revisions",
    response_model=list[SpatialAssetMetadataRevisionResponse],
)
def list_spatial_asset_metadata_revisions(
    project_id: str,
    asset_id: str,
    request: Request,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SpatialAssetMetadataRevisionResponse]:
    return _metadata_service(request, session).list(
        project_id, asset_id, limit=limit, offset=offset
    )


@router.get(
    "/projects/{project_id}/spatial/assets/{asset_id}/metadata-revisions/{revision_id}",
    response_model=SpatialAssetMetadataRevisionResponse,
)
def get_spatial_asset_metadata_revision(
    project_id: str,
    asset_id: str,
    revision_id: str,
    request: Request,
    session: DbSession,
) -> SpatialAssetMetadataRevisionResponse:
    return _metadata_service(request, session).get(project_id, asset_id, revision_id)
