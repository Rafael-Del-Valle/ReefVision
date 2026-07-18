"""Advanced provider manifests and fail-closed preflight endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.advanced_providers import (
    AdvancedProviderManifestResponse,
    AdvancedProviderPreflightRequest,
    AdvancedProviderPreflightResponse,
)
from reefvision.services.advanced_providers import AdvancedProviderService

router = APIRouter(tags=["advanced-providers"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> AdvancedProviderService:
    return AdvancedProviderService(session, request.app.state.settings)


@router.get(
    "/advanced-providers/manifests",
    response_model=list[AdvancedProviderManifestResponse],
)
def list_advanced_provider_manifests(
    request: Request,
    session: DbSession,
) -> list[AdvancedProviderManifestResponse]:
    return service(request, session).manifests()


@router.post(
    "/projects/{project_id}/advanced-providers/{provider_id}/preflight",
    response_model=AdvancedProviderPreflightResponse,
)
def preflight_advanced_provider(
    project_id: str,
    provider_id: str,
    payload: AdvancedProviderPreflightRequest,
    request: Request,
    session: DbSession,
) -> AdvancedProviderPreflightResponse:
    return service(request, session).preflight(project_id, provider_id, payload)
