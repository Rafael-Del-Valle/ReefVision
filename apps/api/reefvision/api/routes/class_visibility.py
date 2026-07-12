"""Class-visibility preference and default endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.class_visibility import (
    ClassVisibilityBundleResponse,
    ClassVisibilityScopeStateResponse,
    ClassVisibilityUpdateRequest,
)
from reefvision.services.class_visibility import ClassVisibilityService

router = APIRouter(tags=["class-visibility"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ClassVisibilityService:
    settings: Settings = request.app.state.settings
    return ClassVisibilityService(session, settings)


@router.get(
    "/projects/{project_id}/class-visibility",
    response_model=ClassVisibilityBundleResponse,
)
def get_class_visibility_bundle(
    project_id: str, request: Request, session: DbSession
) -> ClassVisibilityBundleResponse:
    return service(request, session).get_bundle(project_id)


@router.put(
    "/projects/{project_id}/class-visibility/preferences/{layer_type}",
    response_model=ClassVisibilityScopeStateResponse,
)
def save_class_visibility_preference(
    project_id: str,
    layer_type: str,
    payload: ClassVisibilityUpdateRequest,
    request: Request,
    session: DbSession,
) -> ClassVisibilityScopeStateResponse:
    return service(request, session).save_user_preference(project_id, layer_type, payload)


@router.delete(
    "/projects/{project_id}/class-visibility/preferences/{layer_type}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_class_visibility_preference(
    project_id: str,
    layer_type: str,
    request: Request,
    session: DbSession,
) -> None:
    service(request, session).reset_user_preference(project_id, layer_type)


@router.put(
    "/projects/{project_id}/class-visibility/defaults/{layer_type}",
    response_model=ClassVisibilityScopeStateResponse,
)
def save_project_class_visibility_default(
    project_id: str,
    layer_type: str,
    payload: ClassVisibilityUpdateRequest,
    request: Request,
    session: DbSession,
) -> ClassVisibilityScopeStateResponse:
    return service(request, session).save_project_default(project_id, layer_type, payload)


@router.delete(
    "/projects/{project_id}/class-visibility/defaults/{layer_type}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_class_visibility_default(
    project_id: str,
    layer_type: str,
    request: Request,
    session: DbSession,
) -> None:
    service(request, session).reset_project_default(project_id, layer_type)
