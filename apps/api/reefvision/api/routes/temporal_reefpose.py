"""Native temporal ReefPose dataset, training, refinement, and review routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.temporal_reefpose import (
    TemporalDatasetCreate,
    TemporalDatasetDetail,
    TemporalDatasetRead,
    TemporalFramePage,
    TemporalInputsRead,
    TemporalReviewCreate,
    TemporalReviewRead,
    TemporalRunCreate,
    TemporalRunRead,
)
from reefvision.services.temporal_reefpose import TemporalReefPoseService

router = APIRouter(prefix="/projects/{project_id}/temporal-reefpose", tags=["temporal-reefpose"])
DbSession = Annotated[Session, Depends(get_db_session)]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/inputs", response_model=TemporalInputsRead)
def inputs(
    project_id: UUID, session: DbSession, limit: Limit = 100, offset: Offset = 0
) -> TemporalInputsRead:
    return TemporalReefPoseService(session).inputs(str(project_id), limit, offset)


@router.get("/datasets", response_model=list[TemporalDatasetRead])
def datasets(
    project_id: UUID, session: DbSession, limit: Limit = 100, offset: Offset = 0
) -> list[TemporalDatasetRead]:
    return TemporalReefPoseService(session).datasets(str(project_id), limit, offset)


@router.post("/datasets", response_model=TemporalDatasetRead, status_code=status.HTTP_201_CREATED)
def freeze(
    project_id: UUID, payload: TemporalDatasetCreate, session: DbSession
) -> TemporalDatasetRead:
    service = TemporalReefPoseService(session)
    return service.dataset_summary(service.freeze(str(project_id), payload))


@router.get("/datasets/{dataset_id}", response_model=TemporalDatasetDetail)
def dataset(project_id: UUID, dataset_id: UUID, session: DbSession) -> TemporalDatasetDetail:
    return TemporalReefPoseService(session).dataset_detail(str(project_id), str(dataset_id))


@router.get("/runs", response_model=list[TemporalRunRead])
def runs(
    project_id: UUID, session: DbSession, limit: Limit = 100, offset: Offset = 0
) -> list[TemporalRunRead]:
    return TemporalReefPoseService(session).runs(str(project_id), limit, offset)


@router.post("/runs", response_model=TemporalRunRead, status_code=status.HTTP_202_ACCEPTED)
def submit(project_id: UUID, payload: TemporalRunCreate, session: DbSession) -> TemporalRunRead:
    service = TemporalReefPoseService(session)
    return service.run_summary(service.submit(str(project_id), payload))


@router.get("/runs/{run_id}", response_model=TemporalRunRead)
def run(project_id: UUID, run_id: UUID, session: DbSession) -> TemporalRunRead:
    service = TemporalReefPoseService(session)
    return service.run_summary(service.run(str(project_id), str(run_id)))


@router.get("/runs/{run_id}/frames", response_model=TemporalFramePage)
def frames(
    project_id: UUID,
    run_id: UUID,
    session: DbSession,
    limit: Limit = 100,
    offset: Offset = 0,
) -> TemporalFramePage:
    return TemporalReefPoseService(session).frames(str(project_id), str(run_id), limit, offset)


@router.post(
    "/runs/{run_id}/reviews", response_model=TemporalReviewRead, status_code=status.HTTP_201_CREATED
)
def review(
    project_id: UUID, run_id: UUID, payload: TemporalReviewCreate, session: DbSession
) -> TemporalReviewRead:
    from reefvision.services.temporal_reefpose_review import review_temporal_run

    return review_temporal_run(session, str(project_id), str(run_id), payload)
