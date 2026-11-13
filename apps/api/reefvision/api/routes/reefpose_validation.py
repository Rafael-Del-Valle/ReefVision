"""Independent scientific validation API."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import Job
from reefvision.jobs.reefpose_validation import JOB_TYPE, completed_report, submit_validation
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.reefpose_validation import (
    FreezeReferenceRequest,
    ReferenceDetail,
    ReferenceSummary,
    ValidationRequest,
)
from reefvision.services.reefpose_validation import ReferenceService
from reefvision.storage.reefpose_validation import validation_csv, validation_summary_csv

router = APIRouter(tags=["reefpose-validation"], prefix="/projects/{project_id}")
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/reefpose-references", response_model=ReferenceDetail, status_code=201)
def freeze_reference(
    project_id: str, payload: FreezeReferenceRequest, session: DbSession
) -> ReferenceDetail:
    return ReferenceDetail.model_validate(ReferenceService(session).freeze(project_id, payload))


@router.get("/reefpose-references", response_model=list[ReferenceSummary])
def list_references(
    project_id: str,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReferenceSummary]:
    return [
        ReferenceSummary.model_validate(row)
        for row in ReferenceService(session).list(project_id, limit, offset)
    ]


@router.get("/reefpose-references/{reference_id}", response_model=ReferenceDetail)
def get_reference(project_id: str, reference_id: str, session: DbSession) -> ReferenceDetail:
    return ReferenceDetail.model_validate(ReferenceService(session).get(project_id, reference_id))


@router.post("/reefpose-validations", response_model=JobResponse, status_code=202)
def create_validation(
    project_id: str,
    payload: ValidationRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    return JobResponse.model_validate(
        submit_validation(session, request.app.state.settings, project_id, payload)
    )


@router.get("/reefpose-validations", response_model=list[JobResponse])
def list_validations(
    project_id: str,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[JobResponse]:
    rows = session.scalars(
        select(Job)
        .where(Job.project_id == project_id, Job.job_type == JOB_TYPE)
        .order_by(Job.created_at.desc(), Job.id)
        .limit(limit)
        .offset(offset)
    )
    return [JobResponse.model_validate(row) for row in rows]


@router.get("/reefpose-validations/{job_id}/export")
def export_validation(
    project_id: str,
    job_id: str,
    session: DbSession,
    format: Literal["json", "csv", "summary"] = "json",
) -> Response:
    report = completed_report(session, project_id, job_id)
    headers = {
        "Content-Disposition": f'attachment; filename="reefpose-validation-{job_id}.{format}"'
    }
    if format != "json":
        content = validation_csv(report) if format == "csv" else validation_summary_csv(report)
        headers["Content-Disposition"] = f'attachment; filename="reefpose-{format}-{job_id}.csv"'
        return Response(content, media_type="text/csv", headers=headers)
    return JSONResponse(report, headers=headers)
