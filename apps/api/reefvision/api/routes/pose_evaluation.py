"""Scientific pose evaluation API."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.pose_evaluation import (
    PoseEvaluationComparisonCreateRequest,
    PoseEvaluationComparisonListResponse,
    PoseEvaluationCreateRequest,
    PoseEvaluationRunResponse,
)
from reefvision.services.pose_evaluation import PoseEvaluationService
from reefvision.services.pose_evaluation_comparison import PoseEvaluationComparisonService

router = APIRouter(tags=["pose-evaluation"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> PoseEvaluationService:
    return PoseEvaluationService(session, request.app.state.settings)


def comparison_service(request: Request, session: Session) -> PoseEvaluationComparisonService:
    return PoseEvaluationComparisonService(session, request.app.state.settings)


@router.post(
    "/projects/{project_id}/pose-evaluation-comparisons",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_pose_evaluation_comparison(
    project_id: str,
    payload: PoseEvaluationComparisonCreateRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    return comparison_service(request, session).submit(project_id, payload)


@router.get(
    "/projects/{project_id}/pose-evaluation-comparisons",
    response_model=PoseEvaluationComparisonListResponse,
)
def list_pose_evaluation_comparisons(
    project_id: str,
    request: Request,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PoseEvaluationComparisonListResponse:
    return comparison_service(request, session).list_for_project(
        project_id, limit=limit, offset=offset
    )


@router.get("/pose-evaluation-comparisons/{job_id}", response_model=JobResponse)
def get_pose_evaluation_comparison(
    job_id: str,
    request: Request,
    session: DbSession,
) -> JobResponse:
    return comparison_service(request, session).get(job_id)


@router.get("/pose-evaluation-comparisons/{job_id}/export")
def export_pose_evaluation_comparison(
    job_id: str,
    request: Request,
    session: DbSession,
    format: Literal["json", "csv"] = "json",
) -> Response:
    comparisons = comparison_service(request, session)
    if format == "json":
        return JSONResponse(comparisons.export_json(job_id))
    return Response(
        comparisons.export_csv(job_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="reefpose-comparison-{job_id}.csv"'
            )
        },
    )


@router.post(
    "/projects/{project_id}/pose-evaluations",
    response_model=PoseEvaluationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_pose_evaluation(
    project_id: str,
    payload: PoseEvaluationCreateRequest,
    request: Request,
    session: DbSession,
) -> PoseEvaluationRunResponse:
    return service(request, session).create(project_id, payload)


@router.get(
    "/projects/{project_id}/pose-evaluations",
    response_model=list[PoseEvaluationRunResponse],
)
def list_pose_evaluations(
    project_id: str,
    request: Request,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PoseEvaluationRunResponse]:
    return service(request, session).list_for_project(project_id, limit=limit, offset=offset)


@router.get("/pose-evaluations/{run_id}", response_model=PoseEvaluationRunResponse)
def get_pose_evaluation(
    run_id: str,
    request: Request,
    session: DbSession,
) -> PoseEvaluationRunResponse:
    return service(request, session).get(run_id)


@router.get("/pose-evaluations/{run_id}/export")
def export_pose_evaluation(
    run_id: str,
    request: Request,
    session: DbSession,
    format: Literal["json", "csv"] = "json",
) -> Response:
    evaluation = service(request, session)
    if format == "json":
        return JSONResponse(evaluation.export_json(run_id))
    return Response(
        evaluation.export_csv(run_id),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="reefpose-evaluation-{run_id}.csv"'},
    )
