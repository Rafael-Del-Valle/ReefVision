"""Immutable pairwise geographic measurement API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.geographic_pairwise import (
    GeographicPairwiseCalculateRequest,
    GeographicPairwiseSavedResponse,
    GeographicPairwiseValidationResponse,
)
from reefvision.services.geographic_pairwise import GeographicPairwiseService

router = APIRouter(tags=["geographic-pairwise"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/geographic-pairwise/calculate",
    response_model=GeographicPairwiseSavedResponse,
    status_code=201,
)
def calculate_geographic_pairwise(
    project_id: UUID,
    payload: GeographicPairwiseCalculateRequest,
    session: DbSession,
) -> GeographicPairwiseSavedResponse:
    return GeographicPairwiseService(session).calculate(str(project_id), payload)


@router.get(
    "/projects/{project_id}/geographic-pairwise/{result_id}",
    response_model=GeographicPairwiseSavedResponse,
)
def get_geographic_pairwise(
    project_id: UUID,
    result_id: UUID,
    session: DbSession,
) -> GeographicPairwiseSavedResponse:
    return GeographicPairwiseService(session).get_result(str(project_id), str(result_id))


@router.get(
    "/projects/{project_id}/geographic-pairwise/{result_id}/validation",
    response_model=GeographicPairwiseValidationResponse,
)
def validate_geographic_pairwise(
    project_id: UUID,
    result_id: UUID,
    session: DbSession,
) -> GeographicPairwiseValidationResponse:
    return GeographicPairwiseService(session).validate_result(str(project_id), str(result_id))


@router.get("/projects/{project_id}/geographic-pairwise/{result_id}/export.csv")
def export_geographic_pairwise_csv(
    project_id: UUID,
    result_id: UUID,
    session: DbSession,
) -> Response:
    payload = GeographicPairwiseService(session).result_csv(str(project_id), str(result_id))
    return Response(
        payload,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="geographic-pairwise-{result_id}.csv"'
        },
    )
