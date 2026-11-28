"""Read, calculate and export comparisons of frozen ReefPose scoring reports."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.scientific_comparison import ComparisonRecord, ComparisonRequest
from reefvision.services.scientific_comparison import (
    create_comparison,
    list_comparisons,
    read_comparison,
)
from reefvision.storage.scientific_comparison import comparison_csv

DbSession = Annotated[Session, Depends(get_db_session)]
router = APIRouter(
    prefix="/projects/{project_id}/scientific-comparisons",
    tags=["scientific comparison"],
)


@router.post("", response_model=ComparisonRecord, status_code=201)
def create(project_id: UUID, payload: ComparisonRequest, session: DbSession) -> ComparisonRecord:
    return create_comparison(session, str(project_id), payload)


@router.get("", response_model=list[ComparisonRecord])
def list_saved(
    project_id: UUID,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ComparisonRecord]:
    return list_comparisons(session, str(project_id), limit, offset)


@router.get("/{comparison_id}", response_model=ComparisonRecord)
def get(project_id: UUID, comparison_id: UUID, session: DbSession) -> ComparisonRecord:
    return read_comparison(session, str(project_id), str(comparison_id))


@router.get("/{comparison_id}/export")
def export(
    project_id: UUID,
    comparison_id: UUID,
    session: DbSession,
    format: Literal["json", "csv"] = "json",
) -> Response:
    record = read_comparison(session, str(project_id), str(comparison_id))
    filename = f"scientific-comparison-{comparison_id}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "csv":
        return Response(comparison_csv(record), media_type="text/csv", headers=headers)
    return JSONResponse(record.model_dump(mode="json"), headers=headers)
