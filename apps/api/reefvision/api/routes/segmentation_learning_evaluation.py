"""Read-only mask evaluation records from completed isolated inference jobs.

No endpoints for model promotion, rollback or deployment are provided here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import Job
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.segmentation_learning_evaluation import (
    SegmentationCompletedEvaluationRequest,
    SegmentationCompletedEvaluationResponse,
)
from reefvision.services.segmentation_learning_evaluation import (
    SegmentationLearningEvaluationService,
)

router = APIRouter(tags=["project-learning"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _response(record: Job) -> SegmentationCompletedEvaluationResponse:
    request = record.request_json
    result = record.result_json or {}
    return SegmentationCompletedEvaluationResponse(
        id=record.id,
        status=record.status,
        dataset_version_id=request["dataset_version_id"],
        manifest_sha256=request["manifest_sha256"],
        split=request["split"],
        candidate_model_id=request["candidate_model_id"],
        candidate_job_id=request["candidate_job_id"],
        candidate_checksum=request["candidate_checksum"],
        incumbent_model_id=request.get("incumbent_model_id"),
        incumbent_job_id=request.get("incumbent_job_id"),
        incumbent_checksum=request.get("incumbent_checksum"),
        candidate_metrics=result.get("candidate_metrics"),
        incumbent_metrics=result.get("incumbent_metrics"),
        promotion_eligible=bool(result.get("promotion_eligible", False)),
        blockers=list(result.get("blockers") or []),
    )


@router.post(
    "/projects/{project_id}/learning/segmentation/evaluations",
    response_model=SegmentationCompletedEvaluationResponse,
)
def record_segmentation_evaluation(
    project_id: str,
    payload: SegmentationCompletedEvaluationRequest,
    request: Request,
    session: DbSession,
) -> SegmentationCompletedEvaluationResponse:
    record = SegmentationLearningEvaluationService(
        session, request.app.state.settings
    ).record_completed_evaluation(
        project_id,
        payload.dataset_version_id,
        split=payload.split,
        candidate_model_id=payload.candidate_model_id,
        candidate_job_id=payload.candidate_job_id,
        incumbent_model_id=payload.incumbent_model_id,
        incumbent_job_id=payload.incumbent_job_id,
        minimum_images=payload.minimum_images,
        minimum_masks=payload.minimum_masks,
        minimum_mask_map50=payload.minimum_mask_map50,
        minimum_gain=payload.minimum_gain,
    )
    return _response(record)


@router.get(
    "/projects/{project_id}/learning/segmentation/evaluations",
    response_model=list[JobResponse],
)
def list_segmentation_evaluations(
    project_id: str, session: DbSession
) -> list[JobResponse]:
    """Read immutable evaluation history, including queued and failed jobs."""
    records = session.scalars(
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.job_type == "segmentation_learning_evaluation",
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(100)
    )
    return [JobResponse.model_validate(record) for record in records]


@router.get(
    "/projects/{project_id}/learning/segmentation/evaluations/{evaluation_id}",
    response_model=SegmentationCompletedEvaluationResponse,
)
def get_segmentation_evaluation(
    project_id: str, evaluation_id: str, session: DbSession
) -> SegmentationCompletedEvaluationResponse:
    record = session.get(Job, evaluation_id)
    if (
        record is None
        or record.project_id != project_id
        or record.job_type != "segmentation_learning_evaluation"
    ):
        raise NotFoundError("Segmentation evaluation record not found")
    return _response(record)
