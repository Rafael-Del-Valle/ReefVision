"""Explicit held-out segmentation inference queue and evaluation finalization."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.segmentation_evaluation_queue import SegmentationEvaluationQueueRequest
from reefvision.services.segmentation_evaluation_queue import SegmentationEvaluationQueueService

router = APIRouter(tags=["project-learning"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/learning/segmentation/queue",
    response_model=JobResponse,
)
def queue_segmentation_evaluation(
    project_id: str,
    payload: SegmentationEvaluationQueueRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    record = SegmentationEvaluationQueueService(session, request.app.state.settings).queue(
        project_id,
        payload.dataset_version_id,
        split=payload.split,
        candidate_model_id=payload.candidate_model_id,
        incumbent_model_id=payload.incumbent_model_id,
        minimum_images=payload.minimum_images,
        minimum_masks=payload.minimum_masks,
        minimum_mask_map50=payload.minimum_mask_map50,
        minimum_gain=payload.minimum_gain,
    )
    return JobResponse.model_validate(record)


@router.post(
    "/projects/{project_id}/learning/segmentation/queue/{evaluation_id}/finalize",
    response_model=JobResponse,
)
def finalize_segmentation_evaluation(
    project_id: str, evaluation_id: str, request: Request, session: DbSession
) -> JobResponse:
    """Finalize a waiting evaluation after its queued child inference jobs finish."""
    record = SegmentationEvaluationQueueService(session, request.app.state.settings).advance(
        project_id, evaluation_id
    )
    return JobResponse.model_validate(record)
