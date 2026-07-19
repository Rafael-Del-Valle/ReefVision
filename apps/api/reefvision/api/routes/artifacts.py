"""Unified artifact provenance, lineage, preview, and content endpoints."""

from __future__ import annotations

import mimetypes
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.artifacts import (
    ArtifactCreateRequest,
    ArtifactLineageResponse,
    ArtifactPreviewResponse,
    ArtifactResponse,
)
from reefvision.services.artifact_previews import ArtifactPreviewService
from reefvision.services.artifacts import ArtifactService

router = APIRouter(tags=["artifacts"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _service(request: Request, session: Session) -> ArtifactService:
    settings: Settings = request.app.state.settings
    return ArtifactService(session, settings)


def _preview_service(request: Request, session: Session) -> ArtifactPreviewService:
    settings: Settings = request.app.state.settings
    return ArtifactPreviewService(session, settings)


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


@router.get("/artifacts/{artifact_id}/preview", response_model=ArtifactPreviewResponse)
def preview_artifact(
    artifact_id: str,
    request: Request,
    session: DbSession,
) -> ArtifactPreviewResponse:
    return _preview_service(request, session).preview(artifact_id)


@router.get("/artifacts/{artifact_id}/content")
def artifact_content(
    artifact_id: str,
    request: Request,
    session: DbSession,
    download: bool = Query(default=False),
) -> FileResponse:
    artifact, path = _preview_service(request, session).content_path(artifact_id)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    disposition = "attachment" if download else "inline"
    headers = {
        "Content-Disposition": f'{disposition}; filename="{path.name.replace(chr(34), "")}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=60",
        "ETag": artifact.checksum,
    }
    if media_type in {"text/html", "application/xhtml+xml"}:
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    return FileResponse(path, media_type=media_type, headers=headers)


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
