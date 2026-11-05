"""Standalone API for replicate-aware reviewed annotation counts."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.computed_aggregate_metrics import (
    ComputedAggregateDefinitionCreate,
    ComputedAggregateDefinitionPage,
    ComputedAggregateDefinitionResponse,
    ComputedAggregatePreview,
    ComputedAggregateResultPage,
    ComputedAggregateResultResponse,
    ComputedAggregateSelection,
)
from reefvision.services.computed_aggregate_metrics import ComputedAggregateMetricService

router = APIRouter(tags=["computed-aggregate-metrics"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/computed-aggregate-definitions",
    response_model=ComputedAggregateDefinitionResponse,
    status_code=201,
)
def create_definition(
    project_id: UUID, payload: ComputedAggregateDefinitionCreate, session: DbSession
) -> ComputedAggregateDefinitionResponse:
    service = ComputedAggregateMetricService(session)
    row = service.create_definition(str(project_id), payload)
    response = service.definition_response(row)
    session.commit()
    return response


@router.get(
    "/projects/{project_id}/computed-aggregate-definitions",
    response_model=ComputedAggregateDefinitionPage,
)
def list_definitions(
    project_id: UUID,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ComputedAggregateDefinitionPage:
    return ComputedAggregateMetricService(session).list_definitions(
        str(project_id), limit=limit, offset=offset
    )


@router.post(
    "/projects/{project_id}/computed-aggregate-definitions/{definition_id}/preview",
    response_model=ComputedAggregatePreview,
)
def preview(
    project_id: UUID,
    definition_id: UUID,
    payload: ComputedAggregateSelection,
    session: DbSession,
) -> ComputedAggregatePreview:
    return ComputedAggregateMetricService(session).preview(
        str(project_id), str(definition_id), [str(value) for value in payload.image_ids]
    )


@router.post(
    "/projects/{project_id}/computed-aggregate-definitions/{definition_id}/calculate",
    response_model=ComputedAggregateResultResponse,
    status_code=201,
)
def calculate(
    project_id: UUID,
    definition_id: UUID,
    payload: ComputedAggregateSelection,
    session: DbSession,
) -> ComputedAggregateResultResponse:
    service = ComputedAggregateMetricService(session)
    row = service.calculate(
        str(project_id), str(definition_id), [str(value) for value in payload.image_ids]
    )
    response = service.result_response(row)
    session.commit()
    return response


@router.get(
    "/projects/{project_id}/computed-aggregate-results",
    response_model=ComputedAggregateResultPage,
)
def list_results(
    project_id: UUID,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ComputedAggregateResultPage:
    return ComputedAggregateMetricService(session).list_results(
        str(project_id), limit=limit, offset=offset
    )
