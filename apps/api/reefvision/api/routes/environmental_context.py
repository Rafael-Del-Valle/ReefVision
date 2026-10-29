"""Environmental acquisition stays in the local backend for browser and Tauri clients."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.copernicus import CopernicusRequest
from reefvision.schemas.environmental_context import (
    EnvironmentalDatasetPage,
    EnvironmentalImportResponse,
    EnvironmentalLookup,
    EnvironmentalLookupResponse,
    EnvironmentalSubjectContext,
    EnvironmentalSubjectLookup,
    EnvironmentalThresholdRequest,
    EnvironmentalThresholdResponse,
    NOAAImportRequest,
)
from reefvision.services.copernicus_environment import CopernicusEnvironmentService
from reefvision.services.environmental_context import EnvironmentalContextService

router = APIRouter(tags=["environmental-context"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/projects/{project_id}/environment/noaa", response_model=EnvironmentalImportResponse)
def import_noaa(
    project_id: UUID, payload: NOAAImportRequest, session: DbSession
) -> EnvironmentalImportResponse:
    return EnvironmentalContextService(session).import_noaa(str(project_id), payload)


@router.post(
    "/projects/{project_id}/environment/lookup", response_model=EnvironmentalLookupResponse
)
def lookup_environment(
    project_id: UUID, payload: EnvironmentalLookup, session: DbSession
) -> EnvironmentalLookupResponse:
    return EnvironmentalContextService(session).lookup(str(project_id), payload)


@router.post(
    "/projects/{project_id}/environment/events/threshold",
    response_model=EnvironmentalThresholdResponse,
)
def environmental_threshold_samples(
    project_id: UUID, payload: EnvironmentalThresholdRequest, session: DbSession
) -> EnvironmentalThresholdResponse:
    return EnvironmentalContextService(session).threshold_samples(str(project_id), payload)


@router.post(
    "/projects/{project_id}/environment/subject-context", response_model=EnvironmentalSubjectContext
)
def subject_environment(
    project_id: UUID, payload: EnvironmentalSubjectLookup, session: DbSession
) -> EnvironmentalSubjectContext:
    return EnvironmentalContextService(session).subject_context(str(project_id), payload)


@router.post(
    "/projects/{project_id}/environment/copernicus", response_model=EnvironmentalImportResponse
)
def import_copernicus(
    project_id: UUID, payload: CopernicusRequest, request: Request, session: DbSession
) -> EnvironmentalImportResponse:
    return CopernicusEnvironmentService(session, request.app.state.settings).acquire(
        str(project_id), payload
    )


@router.get("/projects/{project_id}/environment/datasets", response_model=EnvironmentalDatasetPage)
def list_environmental_datasets(
    project_id: UUID,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EnvironmentalDatasetPage:
    return EnvironmentalContextService(session).datasets(str(project_id), limit, offset)


@router.get(
    "/projects/{project_id}/environment/datasets/{cache_key}",
    response_model=EnvironmentalImportResponse,
)
def open_environmental_dataset(
    project_id: UUID, cache_key: str, session: DbSession
) -> EnvironmentalImportResponse:
    return EnvironmentalContextService(session).cached_dataset(str(project_id), cache_key)
