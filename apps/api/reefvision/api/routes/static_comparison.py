"""Project-scoped API for static-image count comparisons."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.static_comparison import (
    StaticComparisonRecord,
    StaticComparisonRequest,
    StaticOptions,
    StaticSummary,
)
from reefvision.services.static_comparison import (
    comparison_options,
    list_static_comparisons,
    read_static_comparison,
    submit_static_comparison,
)
from reefvision.storage.scientific_comparison import static_comparison_csv

router = APIRouter(prefix="/projects/{project_id}/static-comparisons", tags=["static comparison"])
DbSession = Annotated[Session, Depends(get_db_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/options", response_model=StaticOptions)
def options(
    project_id: UUID, session: DbSession, limit: Limit = 25, offset: Offset = 0
) -> StaticOptions:
    return comparison_options(session, str(project_id), limit, offset)


@router.post("", response_model=JobResponse, status_code=202)
def submit(
    project_id: UUID,
    payload: StaticComparisonRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    return submit_static_comparison(session, request.app.state.settings, str(project_id), payload)


@router.get("", response_model=list[StaticSummary])
def list_saved(
    project_id: UUID,
    session: DbSession,
    limit: Limit = 25,
    offset: Offset = 0,
    completed_only: bool = False,
) -> list[StaticSummary]:
    return list_static_comparisons(
        session, str(project_id), limit, offset, completed_only=completed_only
    )


@router.get("/{comparison_id}", response_model=StaticComparisonRecord)
def get(
    project_id: UUID,
    comparison_id: UUID,
    request: Request,
    session: DbSession,
) -> StaticComparisonRecord:
    return read_static_comparison(
        session, str(project_id), str(comparison_id), request.app.state.settings
    )


@router.get("/{comparison_id}/export")
def export(
    project_id: UUID,
    comparison_id: UUID,
    request: Request,
    session: DbSession,
    format: Literal["json", "csv"] = "json",
) -> Response:
    record = get(project_id, comparison_id, request, session)
    headers = {
        "Content-Disposition": f'attachment; filename="static-comparison-{comparison_id}.{format}"'
    }
    if format == "csv":
        return Response(static_comparison_csv(record), media_type="text/csv", headers=headers)
    return JSONResponse(record.model_dump(mode="json"), headers=headers)
