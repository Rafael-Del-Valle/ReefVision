"""Unified artifact provenance and lineage endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.artifacts import (
    ArtifactCreateRequest,
    ArtifactLineageResponse,
    ArtifactResponse,
)
from reefvision.services.artifacts import ArtifactService

router = APIRouter(tags=["artifacts"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _service(request: Request, session: Session) -> ArtifactService:
    settings: Settings = request.app.state.settings
    return ArtifactService(session, settings)


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactResponse])
def list_artifacts(
    project_id: str,
    request: Request,
    session: DbSession,
    artifact_type: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[ArtifactResponse]:
    return _service(request, session).list_for_project(
        project_id,
        artifact_type=artifact_type,
        review_status=review_status,
        limit=limit,
    )


@router.post("/projects/{project_id}/artifacts", response_model=ArtifactResponse)
def create_artifact(
    project_id: str,
    payload: ArtifactCreateRequest,
    request: Request,
    session: DbSession,
) -> ArtifactResponse:
    return _service(request, session).create(project_id, payload)


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(
    artifact_id: str,
    request: Request,
    session: DbSession,
) -> ArtifactResponse:
    return ArtifactResponse.model_validate(_service(request, session).get(artifact_id))


@router.get("/artifacts/{artifact_id}/lineage", response_model=ArtifactLineageResponse)
def get_artifact_lineage(
    artifact_id: str,
    request: Request,
    session: DbSession,
) -> ArtifactLineageResponse:
    return _service(request, session).lineage(artifact_id)


@router.post("/artifacts/{artifact_id}/review/{review_status}", response_model=ArtifactResponse)
def update_artifact_review(
    artifact_id: str,
    review_status: str,
    request: Request,
    session: DbSession,
) -> ArtifactResponse:
    return _service(request, session).update_review_status(artifact_id, review_status)
