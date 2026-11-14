"""Publication figure creation, inspection, and downloads."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.research_reports import FigureRecord, FigureRequest
from reefvision.services.research_reports import ResearchReportService
from reefvision.storage.research_report_exports import figure_csv, figure_svg

router = APIRouter(prefix="/projects/{project_id}/research-reports", tags=["research reports"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("", status_code=201)
def save_report(
    project_id: UUID,
    options: FigureRequest,
    request: Request,
    session: DbSession,
) -> FigureRecord:
    return ResearchReportService(session, request.app.state.settings).save(str(project_id), options)


@router.get("")
def list_reports(
    project_id: UUID,
    session: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[FigureRecord]:
    return ResearchReportService(session).list(str(project_id), offset, limit)


@router.get("/{report_id}")
def read_report(
    project_id: UUID, report_id: UUID, request: Request, session: DbSession
) -> FigureRecord:
    return ResearchReportService(session, request.app.state.settings).get(
        str(project_id), str(report_id)
    )


@router.get("/{report_id}/figure.svg", response_class=Response)
def report_svg(project_id: UUID, report_id: UUID, request: Request, session: DbSession) -> Response:
    report = read_report(project_id, report_id, request, session)
    return Response(
        figure_svg(report.snapshot),
        media_type="image/svg+xml",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
            "X-ReefVision-Content-SHA256": report.content_sha256,
        },
    )


@router.get("/{report_id}/table.csv", response_class=Response)
def report_csv(project_id: UUID, report_id: UUID, request: Request, session: DbSession) -> Response:
    report = read_report(project_id, report_id, request, session)
    return Response(
        figure_csv(report.snapshot),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="reefvision-research-report.csv"',
            "X-ReefVision-Content-SHA256": report.content_sha256,
        },
    )
