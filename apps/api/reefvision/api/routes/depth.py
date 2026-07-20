"""Depth-map generation, import, content, and measurement routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.ml.depth_runtime import inspect_depth_provider_readiness
from reefvision.schemas.depth import (
    DepthAwareMaskMeasurementResponse,
    DepthMapGenerateRequest,
    DepthMapImportRequest,
    DepthMapJobResponse,
    DepthMapResponse,
    DepthProviderReadinessResponse,
    DepthTrackAnalyticsRequest,
    DepthTrackAnalyticsResponse,
)
from reefvision.services.depth_maps import DepthMapService
from reefvision.services.depth_tracking import analyze_depth_tracks

router = APIRouter(tags=["depth"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> DepthMapService:
    settings: Settings = request.app.state.settings
    return DepthMapService(session, settings)


@router.get(
    "/depth/provider-readiness",
    response_model=DepthProviderReadinessResponse,
)
def get_depth_provider_readiness(
    provider_id: Annotated[str, Query(min_length=1, max_length=120)],
    model_id: Annotated[str, Query(min_length=1, max_length=500)],
    device: Annotated[str, Query(min_length=1, max_length=60)] = "auto",
    local_files_only: bool = True,
) -> DepthProviderReadinessResponse:
    return DepthProviderReadinessResponse.model_validate(
        inspect_depth_provider_readiness(
            provider_id=provider_id,
            model_id=model_id,
            device=device,
            local_files_only=local_files_only,
        )
    )


@router.get(
    "/images/{image_id}/depth-maps",
    response_model=list[DepthMapResponse],
)
def list_image_depth_maps(
    image_id: str,
    request: Request,
    session: DbSession,
) -> list[DepthMapResponse]:
    return service(request, session).list_for_image(image_id)


@router.post(
    "/images/{image_id}/depth-jobs",
    response_model=DepthMapJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_image_depth_map(
    image_id: str,
    payload: DepthMapGenerateRequest,
    request: Request,
    session: DbSession,
) -> DepthMapJobResponse:
    return service(request, session).queue_generation(image_id, payload)


@router.put(
    "/images/{image_id}/depth-map-values",
    response_model=DepthMapResponse,
)
def import_image_depth_values(
    image_id: str,
    payload: DepthMapImportRequest,
    request: Request,
    session: DbSession,
) -> DepthMapResponse:
    return service(request, session).import_values(image_id, payload)


@router.get("/depth-maps/{depth_map_id}", response_model=DepthMapResponse)
def get_depth_map(
    depth_map_id: str,
    request: Request,
    session: DbSession,
) -> DepthMapResponse:
    return service(request, session).get(depth_map_id)


@router.get("/depth-maps/{depth_map_id}/preview", response_class=FileResponse)
def get_depth_map_preview(
    depth_map_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    path = service(request, session).content_path(depth_map_id, preview=True)
    return FileResponse(
        path,
        media_type="image/png",
        filename=f"{depth_map_id}-depth.png",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-cache"},
    )


@router.get("/depth-maps/{depth_map_id}/content", response_class=FileResponse)
def download_depth_map(
    depth_map_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    path = service(request, session).content_path(depth_map_id, preview=False)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"{depth_map_id}-depth.npy",
    )


@router.get(
    "/mask-annotations/{mask_annotation_id}/depth-measurement",
    response_model=DepthAwareMaskMeasurementResponse,
)
def measure_mask_with_depth(
    mask_annotation_id: str,
    request: Request,
    session: DbSession,
    depth_map_id: Annotated[str | None, Query(max_length=36)] = None,
) -> DepthAwareMaskMeasurementResponse:
    return service(request, session).measure_mask(
        mask_annotation_id,
        depth_map_id=depth_map_id,
    )


@router.post(
    "/depth/track-analytics",
    response_model=DepthTrackAnalyticsResponse,
)
def analyze_metric_depth_tracks(
    payload: DepthTrackAnalyticsRequest,
) -> DepthTrackAnalyticsResponse:
    return analyze_depth_tracks(payload)
