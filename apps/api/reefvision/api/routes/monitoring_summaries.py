"""Save, reopen and download comparisons of project-scoped monitoring assessments."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.monitoring_summary import (
    MonitoringSummaryCreate,
    MonitoringSummaryPage,
    MonitoringSummaryRead,
)
from reefvision.services.monitoring_summaries import MonitoringSummaryService
from reefvision.storage.datasets import canonical_json_bytes

router = APIRouter(prefix="/projects/{project_id}/monitoring/summaries", tags=["monitoring"])


def _service(
    request: Request, session: Annotated[Session, Depends(get_db_session)]
) -> MonitoringSummaryService:
    return MonitoringSummaryService(session, request.app.state.settings)


SummaryService = Annotated[MonitoringSummaryService, Depends(_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
def save_summary(
    project_id: UUID, payload: MonitoringSummaryCreate, summaries: SummaryService
) -> MonitoringSummaryRead:
    return summaries.create(str(project_id), payload)


@router.get("")
def list_summaries(
    project_id: UUID,
    summaries: SummaryService,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MonitoringSummaryPage:
    return summaries.list(str(project_id), limit, offset)


@router.get("/{summary_id}")
def get_summary(
    project_id: UUID, summary_id: UUID, summaries: SummaryService
) -> MonitoringSummaryRead:
    return summaries.get(str(project_id), str(summary_id))


@router.get("/{summary_id}/export", response_class=Response)
def export_summary(project_id: UUID, summary_id: UUID, summaries: SummaryService) -> Response:
    result = summaries.get(str(project_id), str(summary_id))
    return Response(
        canonical_json_bytes(result.model_dump(mode="json")),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="monitoring-summary-{summary_id}.json"',
            "X-ReefVision-Content-SHA256": result.content_sha256,
        },
    )
