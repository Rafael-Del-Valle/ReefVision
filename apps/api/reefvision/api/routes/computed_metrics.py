"""Standalone computed scientific metric API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.computed_metrics import (
    ComputedMetricCalculateRequest,
    ComputedMetricDefinitionCreate,
    ComputedMetricDefinitionPage,
    ComputedMetricDefinitionResponse,
    ComputedMetricResultPage,
    ComputedMetricResultResponse,
)
from reefvision.services.computed_metrics import ComputedMetricService

router = APIRouter(tags=["computed-metrics"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/computed-metric-definitions",
    response_model=ComputedMetricDefinitionResponse,
    status_code=201,
)
def create_definition(
    project_id: UUID, payload: ComputedMetricDefinitionCreate, session: DbSession
) -> ComputedMetricDefinitionResponse:
    service = ComputedMetricService(session)
    row = service.create_definition(str(project_id), payload)
    response = service.definition_response(row)
    session.commit()
    return response


@router.get(
    "/projects/{project_id}/computed-metric-definitions",
    response_model=ComputedMetricDefinitionPage,
)
def list_definitions(
    project_id: UUID,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ComputedMetricDefinitionPage:
    return ComputedMetricService(session).list_definitions(
        str(project_id), limit=limit, offset=offset
    )


@router.post(
    "/projects/{project_id}/computed-metric-definitions/{definition_id}/calculate",
    response_model=ComputedMetricResultResponse,
    status_code=201,
)
def calculate(
    project_id: UUID,
    definition_id: UUID,
    payload: ComputedMetricCalculateRequest,
    session: DbSession,
) -> ComputedMetricResultResponse:
    service = ComputedMetricService(session)
    row = service.calculate(
        str(project_id),
        str(definition_id),
        {key: str(value) for key, value in payload.inputs.items()},
    )
    response = service.result_response(row)
    session.commit()
    return response


@router.get(
    "/projects/{project_id}/computed-metric-results",
    response_model=ComputedMetricResultPage,
)
def list_results(
    project_id: UUID,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ComputedMetricResultPage:
    return ComputedMetricService(session).list_results(str(project_id), limit=limit, offset=offset)


@router.get("/projects/{project_id}/computed-metric-results.csv")
def export_results(project_id: UUID, session: DbSession) -> Response:
    content = ComputedMetricService(session).export_csv(str(project_id))
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="computed-metrics.csv"'},
    )
