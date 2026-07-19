"""Segmentation-model evaluation endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.segmentation_evaluation import (
    SegmentationEvaluationRequest,
    SegmentationEvaluationResponse,
)
from reefvision.services.segmentation_evaluation import SegmentationEvaluationService

router = APIRouter(tags=["segmentation-evaluation"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/segmentation-evaluations",
    response_model=SegmentationEvaluationResponse,
)
def evaluate_segmentation_model(
    project_id: str,
    payload: SegmentationEvaluationRequest,
    request: Request,
    session: DbSession,
) -> SegmentationEvaluationResponse:
    return SegmentationEvaluationService(
        session,
        request.app.state.settings,
    ).evaluate(project_id, payload)
