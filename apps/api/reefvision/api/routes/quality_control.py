"""Quality-control run and issue endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.quality_control import (
    QualityControlIssueAcknowledgeRequest,
    QualityControlIssueDismissRequest,
    QualityControlIssuePageResponse,
    QualityControlIssueResponse,
    QualityControlRunComparisonResponse,
    QualityControlRunCreateRequest,
    QualityControlRunResponse,
)
from reefvision.services.quality_control import QualityControlService

router = APIRouter(tags=["quality_control"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> QualityControlService:
    settings: Settings = request.app.state.settings
    return QualityControlService(session, settings)


@router.get(
    "/projects/{project_id}/quality-control-runs",
    response_model=list[QualityControlRunResponse],
)
def list_project_quality_control_runs(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[QualityControlRunResponse]:
    return service(request, session).list_runs(project_id)


@router.post(
    "/projects/{project_id}/quality-control-runs",
    response_model=QualityControlRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_quality_control_run(
    project_id: str,
    payload: QualityControlRunCreateRequest,
    request: Request,
    session: DbSession,
) -> QualityControlRunResponse:
    return service(request, session).create_run_for_project(project_id, payload)


@router.get(
    "/dataset-versions/{version_id}/quality-control-runs",
    response_model=list[QualityControlRunResponse],
)
def list_dataset_version_quality_control_runs(
    version_id: str,
    request: Request,
    session: DbSession,
) -> list[QualityControlRunResponse]:
    version = service(request, session)._version(version_id)
    return service(request, session).list_runs(version.project_id, dataset_version_id=version.id)


@router.post(
    "/dataset-versions/{version_id}/quality-control-runs",
    response_model=QualityControlRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_version_quality_control_run(
    version_id: str,
    payload: QualityControlRunCreateRequest,
    request: Request,
    session: DbSession,
) -> QualityControlRunResponse:
    return service(request, session).create_run_for_dataset_version(version_id, payload)


@router.get("/quality-control-runs/{run_id}", response_model=QualityControlRunResponse)
def get_quality_control_run(
    run_id: str,
    request: Request,
    session: DbSession,
) -> QualityControlRunResponse:
    return service(request, session).get_run(run_id)


@router.post("/quality-control-runs/{run_id}/cancel", response_model=QualityControlRunResponse)
def cancel_quality_control_run(
    run_id: str,
    request: Request,
    session: DbSession,
) -> QualityControlRunResponse:
    return service(request, session).cancel_run(run_id)


@router.get(
    "/quality-control-runs/{run_id}/issues",
    response_model=QualityControlIssuePageResponse,
)
def list_quality_control_issues(
    run_id: str,
    request: Request,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    severity: str | None = None,
    rule_id: str | None = None,
    class_id: str | None = None,
    image_id: str | None = None,
    status: str | None = None,
) -> QualityControlIssuePageResponse:
    return service(request, session).list_issues(
        run_id,
        page=page,
        page_size=page_size,
        severity=severity,
        rule_id=rule_id,
        class_id=class_id,
        image_id=image_id,
        status=status,
    )


@router.get(
    "/quality-control-runs/{run_id}/compare",
    response_model=QualityControlRunComparisonResponse,
)
def compare_quality_control_runs(
    run_id: str,
    other_run_id: Annotated[str, Query(min_length=1)],
    request: Request,
    session: DbSession,
) -> QualityControlRunComparisonResponse:
    return service(request, session).compare_runs(run_id, other_run_id)


@router.post(
    "/quality-control-issues/{issue_id}/acknowledge",
    response_model=QualityControlIssueResponse,
)
def acknowledge_quality_control_issue(
    issue_id: str,
    payload: QualityControlIssueAcknowledgeRequest,
    request: Request,
    session: DbSession,
) -> QualityControlIssueResponse:
    return service(request, session).acknowledge_issue(issue_id, payload)


@router.post(
    "/quality-control-issues/{issue_id}/dismiss",
    response_model=QualityControlIssueResponse,
)
def dismiss_quality_control_issue(
    issue_id: str,
    payload: QualityControlIssueDismissRequest,
    request: Request,
    session: DbSession,
) -> QualityControlIssueResponse:
    return service(request, session).dismiss_issue(issue_id, payload)
