"""Training report generation and download routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.training_reports import (
    TrainingReportCreateRequest,
    TrainingReportResponse,
)
from reefvision.services.training_reports import TrainingReportService

router = APIRouter(tags=["training-reports"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> TrainingReportService:
    settings: Settings = request.app.state.settings
    return TrainingReportService(session, settings)


@router.post(
    "/training-runs/{run_id}/reports",
    response_model=TrainingReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_training_report(
    run_id: str,
    payload: TrainingReportCreateRequest,
    request: Request,
    session: DbSession,
) -> TrainingReportResponse:
    return service(request, session).create(run_id, payload)


@router.get(
    "/training-runs/{run_id}/reports/{report_id}/download",
    response_class=FileResponse,
)
def download_training_report(
    run_id: str,
    report_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    path = service(request, session).report_path(run_id, report_id)
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        filename=f"reefvision-training-report-{run_id}.html",
    )
