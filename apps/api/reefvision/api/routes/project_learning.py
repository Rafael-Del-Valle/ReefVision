"""Explicit verified-annotation learning requests."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.project_learning import (
    LearningConfig,
    LearningImproveResponse,
    LearningStatus,
)
from reefvision.services.project_learning import ProjectLearningService

router = APIRouter(tags=["project-learning"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/projects/{project_id}/learning/status", response_model=LearningStatus)
def learning_status(
    project_id: str, payload: LearningConfig, request: Request, session: DbSession
) -> LearningStatus:
    return ProjectLearningService(session, request.app.state.settings).status(project_id, payload)


@router.post("/projects/{project_id}/learning/improve", response_model=LearningImproveResponse)
def improve_predictions(
    project_id: str, payload: LearningConfig, request: Request, session: DbSession
) -> LearningImproveResponse:
    return ProjectLearningService(session, request.app.state.settings).improve(project_id, payload)
