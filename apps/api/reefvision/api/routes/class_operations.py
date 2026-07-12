"""Class reassignment and reassign-delete endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.class_operations import (
    ClassOperationExecuteRequest,
    ClassOperationPreviewRequest,
    ClassOperationResponse,
)
from reefvision.schemas.projects import LabelClassUsageResponse
from reefvision.services.class_operations import ClassOperationsService

router = APIRouter(tags=["class_operations"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ClassOperationsService:
    settings: Settings = request.app.state.settings
    return ClassOperationsService(session, settings)


@router.get(
    "/projects/{project_id}/classes/{class_id}/usage",
    response_model=LabelClassUsageResponse,
)
def project_class_usage(
    project_id: str,
    class_id: str,
    request: Request,
    session: DbSession,
) -> LabelClassUsageResponse:
    return service(request, session).usage_for_class(project_id, class_id)


@router.post(
    "/projects/{project_id}/classes/{class_id}/reassign/preview",
    response_model=ClassOperationResponse,
    status_code=status.HTTP_201_CREATED,
)
def preview_class_reassign(
    project_id: str,
    class_id: str,
    payload: ClassOperationPreviewRequest,
    request: Request,
    session: DbSession,
) -> ClassOperationResponse:
    return service(request, session).preview_reassign(project_id, class_id, payload)


@router.post(
    "/projects/{project_id}/classes/{class_id}/reassign",
    response_model=ClassOperationResponse,
)
def execute_class_reassign(
    project_id: str,
    class_id: str,
    payload: ClassOperationExecuteRequest,
    request: Request,
    session: DbSession,
) -> ClassOperationResponse:
    return service(request, session).execute_reassign(project_id, class_id, payload)


@router.post(
    "/projects/{project_id}/classes/{class_id}/reassign-delete/preview",
    response_model=ClassOperationResponse,
    status_code=status.HTTP_201_CREATED,
)
def preview_class_reassign_delete(
    project_id: str,
    class_id: str,
    payload: ClassOperationPreviewRequest,
    request: Request,
    session: DbSession,
) -> ClassOperationResponse:
    return service(request, session).preview_reassign_delete(project_id, class_id, payload)


@router.post(
    "/projects/{project_id}/classes/{class_id}/reassign-delete",
    response_model=ClassOperationResponse,
)
def execute_class_reassign_delete(
    project_id: str,
    class_id: str,
    payload: ClassOperationExecuteRequest,
    request: Request,
    session: DbSession,
) -> ClassOperationResponse:
    return service(request, session).execute_reassign_delete(project_id, class_id, payload)


@router.get("/class-operations/{operation_id}", response_model=ClassOperationResponse)
def get_class_operation(
    operation_id: str,
    request: Request,
    session: DbSession,
) -> ClassOperationResponse:
    return service(request, session).get_operation(operation_id)
