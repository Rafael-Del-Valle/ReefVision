"""Diversity-aware active-learning queue endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.active_learning import (
    ActiveLearningQueueCreateRequest,
    ActiveLearningQueuePromotionRequest,
    ActiveLearningQueuePromotionResponse,
)
from reefvision.schemas.review_queues import ReviewQueueResponse
from reefvision.services.active_learning_queues import ActiveLearningQueueService

router = APIRouter(tags=["active_learning"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ActiveLearningQueueService:
    settings: Settings = request.app.state.settings
    return ActiveLearningQueueService(session, settings)


@router.post(
    "/projects/{project_id}/active-learning-queues",
    response_model=ReviewQueueResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_active_learning_queue(
    project_id: str,
    payload: ActiveLearningQueueCreateRequest,
    request: Request,
    session: DbSession,
) -> ReviewQueueResponse:
    return service(request, session).create_for_project(project_id, payload)


@router.post(
    "/dataset-versions/{version_id}/active-learning-queues",
    response_model=ReviewQueueResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_active_learning_queue(
    version_id: str,
    payload: ActiveLearningQueueCreateRequest,
    request: Request,
    session: DbSession,
) -> ReviewQueueResponse:
    return service(request, session).create_for_dataset_version(version_id, payload)


@router.post(
    "/active-learning-queues/{queue_id}/regenerate",
    response_model=ReviewQueueResponse,
)
def regenerate_active_learning_queue(
    queue_id: str,
    request: Request,
    session: DbSession,
) -> ReviewQueueResponse:
    return service(request, session).regenerate(queue_id)


@router.post(
    "/active-learning-queues/{queue_id}/promote",
    response_model=ActiveLearningQueuePromotionResponse,
)
def promote_active_learning_queue(
    queue_id: str,
    payload: ActiveLearningQueuePromotionRequest,
    request: Request,
    session: DbSession,
) -> ActiveLearningQueuePromotionResponse:
    return service(request, session).promote(queue_id, payload)
