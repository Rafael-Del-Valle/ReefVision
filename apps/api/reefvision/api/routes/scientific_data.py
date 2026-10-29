"""Project scientific data; original annotations and calibrations remain canonical."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.scientific_data import (
    ScientificRecordBatch,
    ScientificRecordPage,
    SourceKind,
)
from reefvision.services.scientific_data import ScientificDataService

router = APIRouter(tags=["scientific-data"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/scientific-records",
    response_model=ScientificRecordPage,
    status_code=201,
)
def create_records(
    project_id: UUID, payload: ScientificRecordBatch, session: DbSession
) -> ScientificRecordPage:
    service = ScientificDataService(session)
    rows = service.add_records(str(project_id), payload.records)
    response = ScientificRecordPage(items=[service.response(row) for row in rows], total=len(rows))
    session.commit()
    return response


@router.get("/projects/{project_id}/scientific-records", response_model=ScientificRecordPage)
def list_records(
    project_id: UUID,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    variable: str | None = None,
    source_kind: SourceKind | None = None,
) -> ScientificRecordPage:
    return ScientificDataService(session).list_records(
        str(project_id), limit=limit, offset=offset, variable=variable, source_kind=source_kind
    )
