"""Environmental acquisition stays in the local backend for browser and Tauri clients."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.environmental_context import (
    EnvironmentalImportResponse,
    EnvironmentalLookup,
    EnvironmentalLookupResponse,
    EnvironmentalSubjectContext,
    EnvironmentalSubjectLookup,
    NOAAImportRequest,
)
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
    "/projects/{project_id}/environment/subject-context", response_model=EnvironmentalSubjectContext
)
def subject_environment(
    project_id: UUID, payload: EnvironmentalSubjectLookup, session: DbSession
) -> EnvironmentalSubjectContext:
    return EnvironmentalContextService(session).subject_context(str(project_id), payload)
