"""Classification performance and calibration endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.classification_evaluation import (
    ClassificationEvaluationRequest,
    ClassificationEvaluationResponse,
)
from reefvision.services.classification_evaluation import (
    ClassificationEvaluationService,
)
from reefvision.services.classification_evaluation_metrics_runtime import (
    install_classification_evaluation_metrics_runtime,
)

install_classification_evaluation_metrics_runtime()

router = APIRouter(tags=["classification-evaluation"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/classification-evaluations",
    response_model=ClassificationEvaluationResponse,
)
def evaluate_classifier(
    project_id: str,
    payload: ClassificationEvaluationRequest,
    session: DbSession,
) -> ClassificationEvaluationResponse:
    return ClassificationEvaluationService(session).evaluate(project_id, payload)
