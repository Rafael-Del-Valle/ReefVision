"""Project anatomical skeleton template routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.pose_schemas import (
    AnatomyRevisionRequest,
    AnatomySchemaCreateRequest,
    AnatomySchemaDetailResponse,
    AnatomySchemaRevisionResponse,
)
from reefvision.services.pose_schemas import PoseSchemaService

router = APIRouter(tags=["pose-schemas"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/pose-schemas",
    response_model=AnatomySchemaRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_pose_schema(
    project_id: str,
    payload: AnatomySchemaCreateRequest,
    session: DbSession,
) -> AnatomySchemaRevisionResponse:
    return PoseSchemaService(session).create(project_id, payload)


@router.get(
    "/projects/{project_id}/pose-schemas",
    response_model=list[AnatomySchemaRevisionResponse],
)
def list_pose_schemas(
    project_id: str,
    session: DbSession,
) -> list[AnatomySchemaRevisionResponse]:
    return PoseSchemaService(session).list_project(project_id)


@router.get(
    "/pose-schemas/{schema_id}",
    response_model=AnatomySchemaDetailResponse,
)
def get_pose_schema(
    schema_id: str,
    session: DbSession,
) -> AnatomySchemaDetailResponse:
    return PoseSchemaService(session).detail(schema_id)


@router.post(
    "/pose-schemas/{schema_id}/revisions",
    response_model=AnatomySchemaRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_pose_schema_revision(
    schema_id: str,
    payload: AnatomyRevisionRequest,
    session: DbSession,
) -> AnatomySchemaRevisionResponse:
    return PoseSchemaService(session).append_revision(schema_id, payload)
