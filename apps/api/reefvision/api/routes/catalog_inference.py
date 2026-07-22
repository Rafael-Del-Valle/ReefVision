"""Bundled catalog-model inference endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.jobs import JobResponse
from reefvision.services.catalog_inference import (
    CatalogInferenceJobCreateRequest,
    CatalogInferenceService,
)

router = APIRouter(tags=["models"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/catalog-inference-jobs",
    response_model=JobResponse,
)
def create_catalog_inference_job(
    project_id: str,
    payload: CatalogInferenceJobCreateRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    return CatalogInferenceService(session, request.app.state.settings).create_job(
        project_id,
        payload,
    )
