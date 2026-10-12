"""Held-out learning evaluation and explicit deployment endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.learning_evaluation import (
    LearningDeploymentResponse,
    LearningEvaluationRequest,
    LearningEvaluationResponse,
)
from reefvision.services.learning_evaluation import LearningEvaluationService

router = APIRouter(tags=["project-learning"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> LearningEvaluationService:
    return LearningEvaluationService(session, request.app.state.settings)


@router.post(
    "/projects/{project_id}/learning/evaluations",
    response_model=LearningEvaluationResponse,
)
def create_evaluation(
    project_id: str,
    payload: LearningEvaluationRequest,
    request: Request,
    session: DbSession,
) -> LearningEvaluationResponse:
    return service(request, session).create(project_id, payload)


@router.get(
    "/projects/{project_id}/learning/evaluations/{evaluation_id}",
    response_model=LearningEvaluationResponse,
)
def get_evaluation(
    project_id: str, evaluation_id: str, request: Request, session: DbSession
) -> LearningEvaluationResponse:
    return service(request, session).get(project_id, evaluation_id)


@router.post(
    "/projects/{project_id}/learning/evaluations/{evaluation_id}/promote",
    response_model=LearningDeploymentResponse,
)
def promote_evaluation(
    project_id: str, evaluation_id: str, request: Request, session: DbSession
) -> LearningDeploymentResponse:
    return service(request, session).promote(project_id, evaluation_id)


@router.post(
    "/projects/{project_id}/learning/deployments/{deployment_id}/rollback",
    response_model=LearningDeploymentResponse,
)
def rollback_deployment(
    project_id: str, deployment_id: str, request: Request, session: DbSession
) -> LearningDeploymentResponse:
    return service(request, session).rollback(project_id, deployment_id)
