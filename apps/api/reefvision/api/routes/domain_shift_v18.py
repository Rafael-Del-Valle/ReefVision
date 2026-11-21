"""Project-scoped analysis and exports for frozen acquisition domains."""

import csv
import io
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import Job
from reefvision.schemas.domain_shift_v18 import DomainShiftDraft
from reefvision.schemas.jobs import JobResponse
from reefvision.services.domain_shift_v18 import (
    JOB_TYPE,
    get_job,
    inspect_source,
    list_sources,
    read_report,
    submit,
)

router = APIRouter(prefix="/projects/{project_id}/domain-shift", tags=["domain shift"])
DbSession = Annotated[Session, Depends(get_db_session)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/sources")
def sources(
    project_id: UUID, session: DbSession, offset: Offset = 0, limit: Limit = 20
) -> list[dict[str, Any]]:
    return list_sources(session, str(project_id), offset, limit)


@router.get("/sources/{comparison_id}")
def source(project_id: UUID, comparison_id: UUID, session: DbSession) -> dict[str, Any]:
    return inspect_source(session, str(project_id), str(comparison_id))


@router.get("")
def history(
    project_id: UUID, session: DbSession, offset: Offset = 0, limit: Limit = 20
) -> list[JobResponse]:
    rows = session.scalars(
        select(Job)
        .where(Job.project_id == str(project_id), Job.job_type == JOB_TYPE)
        .order_by(Job.created_at.desc(), Job.id)
        .offset(offset)
        .limit(limit)
    )
    return [JobResponse.model_validate(row) for row in rows]


@router.post("", status_code=202)
def run(project_id: UUID, draft: DomainShiftDraft, session: DbSession) -> JobResponse:
    return JobResponse.model_validate(submit(session, str(project_id), draft))


@router.get("/{report_id}")
def get(project_id: UUID, report_id: UUID, session: DbSession) -> JobResponse:
    row = get_job(session, str(project_id), str(report_id))
    if row.status == "succeeded":
        read_report(session, str(project_id), str(report_id))
    return JobResponse.model_validate(row)


@router.get("/{report_id}/report")
def json_report(project_id: UUID, report_id: UUID, session: DbSession) -> Response:
    report = read_report(session, str(project_id), str(report_id))
    return Response(
        json.dumps(report, indent=2, allow_nan=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="domain-shift-{report_id}.json"'},
    )


def _csv_text(value: str) -> str:
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


@router.get("/{report_id}/groups.csv")
def csv_report(project_id: UUID, report_id: UUID, session: DbSession) -> Response:
    report = read_report(session, str(project_id), str(report_id))
    rows = report["snapshot"]["summary"]["groups"]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "domain",
            "group_id",
            "status",
            "observations",
            "reason",
            "metric",
            "unit",
            "complete_images",
            "left",
            "right",
            "right_minus_left",
            "report_sha256",
        ]
    )
    for row in rows:
        common = [
            row["domain"],
            _csv_text(row["group_id"]),
            row["status"],
            row["observations"],
            _csv_text(" | ".join(row["exclusions"])),
        ]
        for score in row["metrics"] or [{}]:
            writer.writerow(
                [
                    *common,
                    _csv_text(score.get("name", "")),
                    _csv_text(score.get("unit", "")),
                    score.get("paired_images"),
                    score.get("left"),
                    score.get("right"),
                    score.get("paired_gap"),
                    report["content_sha256"],
                ]
            )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="domain-shift-{report_id}.csv"'},
    )
