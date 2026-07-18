"""Active-learning acquisition round endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.active_learning import (
    ActiveLearningFeedbackResponse,
    ActiveLearningRoundCreateRequest,
    ActiveLearningRoundResponse,
)
from reefvision.services.active_learning_rounds import ActiveLearningRoundService

router = APIRouter(tags=["active-learning"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ActiveLearningRoundService:
    return ActiveLearningRoundService(session, request.app.state.settings)


@router.post(
    "/projects/{project_id}/active-learning-rounds",
    response_model=ActiveLearningRoundResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_active_learning_round(
    project_id: str,
    payload: ActiveLearningRoundCreateRequest,
    request: Request,
    session: DbSession,
) -> ActiveLearningRoundResponse:
    return service(request, session).create_round(project_id, payload)


@router.get(
    "/projects/{project_id}/active-learning-rounds",
    response_model=list[ActiveLearningRoundResponse],
)
def list_active_learning_rounds(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[ActiveLearningRoundResponse]:
    return service(request, session).list_rounds(project_id)


@router.get(
    "/active-learning-rounds/{round_id}",
    response_model=ActiveLearningRoundResponse,
)
def get_active_learning_round(
    round_id: str,
    request: Request,
    session: DbSession,
) -> ActiveLearningRoundResponse:
    return service(request, session).get_round(round_id)


@router.get(
    "/active-learning-rounds/{round_id}/feedback",
    response_model=ActiveLearningFeedbackResponse,
)
def get_active_learning_feedback(
    round_id: str,
    request: Request,
    session: DbSession,
) -> ActiveLearningFeedbackResponse:
    return service(request, session).feedback(round_id)


@router.post(
    "/active-learning-rounds/{round_id}/complete",
    response_model=ActiveLearningRoundResponse,
)
def complete_active_learning_round(
    round_id: str,
    request: Request,
    session: DbSession,
) -> ActiveLearningRoundResponse:
    return service(request, session).complete_round(round_id)
