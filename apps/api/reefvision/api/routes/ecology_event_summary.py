"""Endpoints for reviewed ecological event summaries."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.ecology_event_summary import (
    EventSummaryCreate,
    EventSummaryPage,
    EventSummaryRead,
)
from reefvision.services.ecology_event_summary import EcologyEventSummaryService, export_event_csv

router = APIRouter(
    prefix="/projects/{project_id}/ecology/event-summaries", tags=["ecological monitoring"]
)
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("", status_code=201)
def create_event_summary(
    project_id: UUID, payload: EventSummaryCreate, session: DbSession
) -> EventSummaryRead:
    return EcologyEventSummaryService(session).save(str(project_id), payload)


@router.get("")
def list_event_summaries(
    project_id: UUID,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EventSummaryPage:
    return EcologyEventSummaryService(session).list(str(project_id), limit, offset)


@router.get("/{summary_id}")
def get_event_summary(project_id: UUID, summary_id: UUID, session: DbSession) -> EventSummaryRead:
    return EcologyEventSummaryService(session).get(str(project_id), str(summary_id))


@router.get("/{summary_id}/results.csv", response_class=Response)
def event_summary_csv(project_id: UUID, summary_id: UUID, session: DbSession) -> Response:
    row = get_event_summary(project_id, summary_id, session)
    return Response(
        export_event_csv(row.snapshot),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="reefvision-event-summary.csv"',
            "X-ReefVision-Content-SHA256": row.content_sha256,
        },
    )
