"""Project workspace for paired detector, mask and video model comparisons."""

import csv
from io import StringIO
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import Job, Project
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.paired_models_v15 import (
    ComparisonJobResponse,
    ComparisonRequest,
    ComparisonSource,
    ComparisonSummary,
    ComparisonTask,
)
from reefvision.services import paired_models_v15 as comparison

router = APIRouter(
    prefix="/projects/{project_id}/paired-model-comparisons", tags=["model comparison"]
)
Db = Annotated[Session, Depends(get_db_session)]


@router.get("/sources")
def sources(project_id: UUID, task: ComparisonTask, session: Db) -> list[ComparisonSource]:
    return comparison.list_sources(session, str(project_id), task)


@router.post("", response_model=ComparisonJobResponse, status_code=202)
def submit(project_id: UUID, payload: ComparisonRequest, req: Request, session: Db) -> Job:
    return comparison.submit(session, req.app.state.settings, str(project_id), payload)


@router.get("")
def history(
    project_id: UUID,
    session: Db,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    completed_only: bool = False,
) -> list[ComparisonSummary]:
    if session.get(Project, str(project_id)) is None:
        raise NotFoundError("Project not found")
    query = select(
        Job.id,
        Job.status,
        Job.created_at,
        Job.error_message,
        Job.request_json["task"].as_string().label("task"),
        Job.result_json["content_sha256"].as_string().label("content_sha256"),
    ).where(Job.project_id == str(project_id), Job.job_type == comparison.JOB_TYPE)
    if completed_only:
        query = query.where(Job.status == "succeeded")
    rows = session.execute(
        query.order_by(Job.created_at.desc(), Job.id).offset(offset).limit(limit)
    ).mappings()
    return [ComparisonSummary.model_validate(row) for row in rows]


@router.get("/{comparison_id}", response_model=ComparisonJobResponse)
def current(project_id: UUID, comparison_id: UUID, session: Db) -> Job:
    return comparison.get_job(session, str(project_id), str(comparison_id))


@router.get("/{comparison_id}/export")
def export(
    project_id: UUID, comparison_id: UUID, session: Db, format: Literal["json", "csv"] = "json"
) -> Response:
    report = comparison.read_report(session, str(project_id), str(comparison_id))
    headers = {
        "Content-Disposition": f'attachment; filename="paired-models-{comparison_id}.{format}"'
    }
    if format == "json":
        return JSONResponse(report, headers=headers)
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(
        (
            "group",
            "media_kind",
            "media_id",
            "frame",
            "seconds",
            "metric",
            "unit",
            "left",
            "right",
            "exclusion",
            "report_sha256",
        )
    )
    for group in report["snapshot"]["evidence"]["groups"]:
        for obs in group["observations"]:
            for metric in obs["metrics"] or [{}]:
                writer.writerow(
                    (
                        group["group_id"],
                        obs["media_kind"],
                        obs["media_id"],
                        obs.get("frame"),
                        obs.get("seconds"),
                        metric.get("name"),
                        metric.get("unit"),
                        metric.get("left"),
                        metric.get("right"),
                        obs.get("exclusion"),
                        report["content_sha256"],
                    )
                )
    return Response(buffer.getvalue(), media_type="text/csv", headers=headers)
