"""SAM 3 localhost sidecar registration routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.schemas.sam3_sidecar import Sam3SidecarRegistrationRequest
from reefvision.services.sam3_sidecar_models import Sam3SidecarModelService

router = APIRouter(tags=["sam3-sidecar"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/sam3-sidecar-models",
    response_model=ModelRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_sam3_sidecar_model(
    project_id: str,
    payload: Sam3SidecarRegistrationRequest,
    request: Request,
    session: DbSession,
) -> ModelRegistrationResponse:
    return Sam3SidecarModelService(
        session,
        request.app.state.settings,
    ).register(project_id, payload)
