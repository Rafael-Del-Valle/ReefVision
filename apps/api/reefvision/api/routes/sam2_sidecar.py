"""SAM 2 sidecar registration and health endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.schemas.sam2_sidecar import (
    Sam2SidecarHealthRequest,
    Sam2SidecarHealthResponse,
    Sam2SidecarRegistrationRequest,
)

if TYPE_CHECKING:
    from reefvision.services.sam2_sidecar_models import Sam2SidecarModelService

router = APIRouter(tags=["sam2-sidecar"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> Sam2SidecarModelService:
    """Load the experimental sidecar service without blocking API startup.

    The sidecar provider currently depends on a stale prediction type. Keeping the
    import inside this boundary allows the supported ReefVision workflows to start
    while the sidecar remains explicitly unavailable rather than crashing the whole
    application during router import.
    """

    try:
        from reefvision.services.sam2_sidecar_models import Sam2SidecarModelService
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "SAM 2 sidecar is temporarily unavailable because its provider "
                "contract is incomplete."
            ),
        ) from exc
    return Sam2SidecarModelService(session, request.app.state.settings)


@router.post(
    "/sam2-sidecar/health",
    response_model=Sam2SidecarHealthResponse,
)
def check_sam2_sidecar(
    payload: Sam2SidecarHealthRequest,
    request: Request,
    session: DbSession,
) -> Sam2SidecarHealthResponse:
    return service(request, session).health(payload)


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
    return service(request, session).register(project_id, payload)
