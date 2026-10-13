"""Manual, audited segmentation model activation and reversible rollback."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import Job
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.segmentation_deployment import (
    SegmentationDeploymentAuditResponse,
    SegmentationPromoteRequest,
    SegmentationRollbackRequest,
)
from reefvision.services.segmentation_deployment import SegmentationDeploymentService

router = APIRouter(tags=["project-learning"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _response(record: Job, *, action: str) -> SegmentationDeploymentAuditResponse:
    req = record.request_json
    result = record.result_json or {}
    if action == "promote":
        return SegmentationDeploymentAuditResponse(
            id=record.id,
            status="succeeded",
            action="promote",
            evaluation_id=req["evaluation_id"],
            active_model_id=result["active_model_id"],
            previous_model_id=req.get("previous_model_id"),
            approved_by=req["approved_by"],
            reason=req["reason"],
        )
    return SegmentationDeploymentAuditResponse(
        id=record.id,
        status="succeeded",
        action="rollback",
        deployment_id=req["deployment_id"],
        active_model_id=result.get("restored_model_id"),
        previous_model_id=result.get("rolled_back_model_id"),
        approved_by=req["approved_by"],
        reason=req["reason"],
    )


@router.get(
    "/projects/{project_id}/learning/segmentation/deployments/audit",
    response_model=list[JobResponse],
)
def list_segmentation_deployment_audit(
    project_id: str, session: DbSession
) -> list[JobResponse]:
    """Retrieve committed project-specific segmentation promotion and rollback events."""
    records = session.scalars(
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.job_type.in_(
                (
                    "segmentation_learning_deployment",
                    "segmentation_learning_deployment_rollback",
                )
            ),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(100)
    )
    return [JobResponse.model_validate(record) for record in records]


@router.post(
    "/projects/{project_id}/learning/segmentation/evaluations/{evaluation_id}/promote",
    response_model=SegmentationDeploymentAuditResponse,
)
def promote_segmenter(
    project_id: str,
    evaluation_id: str,
    payload: SegmentationPromoteRequest,
    request: Request,
    session: DbSession,
) -> SegmentationDeploymentAuditResponse:
    audit = SegmentationDeploymentService(session, request.app.state.settings).promote(
        project_id,
        evaluation_id,
        expected_active_model_id=payload.expected_active_model_id,
        approved_by=payload.approved_by,
        reason=payload.reason,
    )
    return _response(audit, action="promote")


@router.post(
    "/projects/{project_id}/learning/segmentation/deployments/{deployment_id}/rollback",
    response_model=SegmentationDeploymentAuditResponse,
)
def rollback_segmenter(
    project_id: str,
    deployment_id: str,
    payload: SegmentationRollbackRequest,
    request: Request,
    session: DbSession,
) -> SegmentationDeploymentAuditResponse:
    audit = SegmentationDeploymentService(session, request.app.state.settings).rollback(
        project_id,
        deployment_id,
        expected_active_model_id=payload.expected_active_model_id,
        approved_by=payload.approved_by,
        reason=payload.reason,
    )
    return _response(audit, action="rollback")
