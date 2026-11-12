"""Multi-animal pose identity association, review, and export API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.pose_identity_tracking import (
    PoseAnimalIdentityResponse,
    PoseIdentityAssociationCreateRequest,
    PoseIdentityAssociationRunResponse,
    PoseIdentityCorrectionRequest,
    PoseIdentityCorrectionResponse,
    PoseIdentityObservationResponse,
)
from reefvision.services.pose_identity_tracking import PoseIdentityTrackingService

router = APIRouter(tags=["pose-identity-tracking"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/pose-identity-runs",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_pose_identity_run(
    project_id: str,
    payload: PoseIdentityAssociationCreateRequest,
    session: DbSession,
) -> JobResponse:
    return PoseIdentityTrackingService(session).submit(project_id, payload)


@router.get(
    "/projects/{project_id}/pose-identity-runs",
    response_model=list[PoseIdentityAssociationRunResponse],
)
def list_pose_identity_runs(
    project_id: str,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PoseIdentityAssociationRunResponse]:
    return PoseIdentityTrackingService(session).list_for_project(
        project_id, limit=limit, offset=offset
    )


@router.get("/pose-identity-runs/{run_id}", response_model=PoseIdentityAssociationRunResponse)
def get_pose_identity_run(run_id: str, session: DbSession) -> PoseIdentityAssociationRunResponse:
    return PoseIdentityTrackingService(session).get(run_id)


@router.get(
    "/pose-identity-runs/{run_id}/identities",
    response_model=list[PoseAnimalIdentityResponse],
)
def list_pose_identities(run_id: str, session: DbSession) -> list[PoseAnimalIdentityResponse]:
    return PoseIdentityTrackingService(session).identities(run_id)


@router.get(
    "/pose-identity-runs/{run_id}/observations",
    response_model=list[PoseIdentityObservationResponse],
)
def list_pose_identity_observations(
    run_id: str,
    session: DbSession,
    include_history: bool = False,
) -> list[PoseIdentityObservationResponse]:
    return PoseIdentityTrackingService(session).observations(
        run_id, include_history=include_history
    )


@router.get("/pose-identity-runs/{run_id}/decisions")
def list_pose_identity_decisions(run_id: str, session: DbSession) -> list[dict[str, Any]]:
    return PoseIdentityTrackingService(session).decisions(run_id)


@router.get(
    "/pose-identity-runs/{run_id}/review-queue",
    response_model=list[PoseIdentityObservationResponse],
)
def list_pose_identity_review_queue(
    run_id: str, session: DbSession
) -> list[PoseIdentityObservationResponse]:
    return PoseIdentityTrackingService(session).review_queue(run_id)


@router.post(
    "/pose-identity-runs/{run_id}/corrections",
    response_model=PoseIdentityCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def correct_pose_identity(
    run_id: str,
    payload: PoseIdentityCorrectionRequest,
    session: DbSession,
) -> PoseIdentityCorrectionResponse:
    return PoseIdentityTrackingService(session).correct(run_id, payload)


@router.get(
    "/pose-identity-runs/{run_id}/corrections",
    response_model=list[PoseIdentityCorrectionResponse],
)
def list_pose_identity_corrections(
    run_id: str, session: DbSession
) -> list[PoseIdentityCorrectionResponse]:
    return PoseIdentityTrackingService(session).corrections(run_id)


@router.get("/pose-identity-runs/{run_id}/export")
def export_pose_identity_run(
    run_id: str,
    session: DbSession,
    format: Literal["json", "csv"] = "json",
) -> Response:
    service = PoseIdentityTrackingService(session)
    if format == "json":
        return JSONResponse(service.export_json(run_id))
    return Response(
        service.export_csv(run_id),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="reefpose-identities-{run_id}.csv"'},
    )
