"""SAM 2 sidecar registration endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.schemas.sam2_sidecar import Sam2SidecarRegistrationRequest
from reefvision.services.sam2_sidecar_models import Sam2SidecarModelService

router = APIRouter(tags=["sam2-sidecar"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/sam2-sidecar-models",
    response_model=ModelRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_sam2_sidecar_model(
    project_id: str,
    payload: Sam2SidecarRegistrationRequest,
    request: Request,
    session: DbSession,
) -> ModelRegistrationResponse:
    return Sam2SidecarModelService(
        session,
        request.app.state.settings,
    ).register(project_id, payload)
