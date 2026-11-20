"""Condition observation, independent decision, and report routes for 3D originals."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.spatial_condition_v14 import (
    ConditionDecision,
    ConditionObservation,
    ConditionReport,
    ConditionRevision,
)
from reefvision.services.spatial_condition_v14 import SpatialConditionService

router = APIRouter(
    prefix="/projects/{project_id}/spatial/assets/{asset_id}/condition-observations",
    tags=["spatial-condition"],
)
DbSession = Annotated[Session, Depends(get_db_session)]


def _service(request: Request, session: Session) -> SpatialConditionService:
    return SpatialConditionService(session, request.app.state.settings)


@router.post("", status_code=status.HTTP_201_CREATED)
def record(
    project_id: UUID,
    asset_id: UUID,
    payload: ConditionObservation,
    request: Request,
    session: DbSession,
) -> ConditionRevision:
    return _service(request, session).observe(str(project_id), str(asset_id), payload)


@router.get("")
def list_observations(
    project_id: UUID,
    asset_id: UUID,
    request: Request,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    newest_first: bool = False,
) -> list[ConditionRevision]:
    return _service(request, session).list(
        str(project_id), str(asset_id), limit=limit, offset=offset, newest_first=newest_first
    )


@router.post("/{revision_id}/decisions", status_code=status.HTTP_201_CREATED)
def decide(
    project_id: UUID,
    asset_id: UUID,
    revision_id: UUID,
    payload: ConditionDecision,
    request: Request,
    session: DbSession,
) -> ConditionRevision:
    return _service(request, session).decide(
        str(project_id), str(asset_id), str(revision_id), payload
    )


@router.get("/{revision_id}")
def get_revision(
    project_id: UUID, asset_id: UUID, revision_id: UUID, request: Request, session: DbSession
) -> ConditionRevision:
    return (
        _service(request, session)
        .report(str(project_id), str(asset_id), str(revision_id))
        .revisions[-1]
    )


@router.get("/{revision_id}/report")
def export_report(
    project_id: UUID,
    asset_id: UUID,
    revision_id: UUID,
    request: Request,
    session: DbSession,
    response: Response,
) -> ConditionReport:
    response.headers["Content-Disposition"] = f'attachment; filename="condition-{revision_id}.json"'
    return _service(request, session).report(str(project_id), str(asset_id), str(revision_id))
