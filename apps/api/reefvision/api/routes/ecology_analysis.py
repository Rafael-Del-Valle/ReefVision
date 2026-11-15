"""Project-scoped history and exports for reviewed ecological analyses."""

from __future__ import annotations

import csv
from io import StringIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.ecology_analysis import (
    AbundanceResult,
    EcologyAnalysisCreate,
    EcologyAnalysisPage,
    EcologyAnalysisRead,
    EcologyAnalysisSnapshot,
)
from reefvision.services.ecology_analysis import EcologyAnalysisService

router = APIRouter(
    prefix="/projects/{project_id}/ecology/verified-analyses",
    tags=["ecological monitoring"],
)
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("", status_code=201, response_model=EcologyAnalysisRead)
def save_verified_ecology_analysis(
    project_id: UUID, payload: EcologyAnalysisCreate, session: DbSession
) -> EcologyAnalysisRead:
    return EcologyAnalysisService(session).save(str(project_id), payload)


@router.get("", response_model=EcologyAnalysisPage)
def list_verified_ecology_analyses(
    project_id: UUID,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> EcologyAnalysisPage:
    return EcologyAnalysisService(session).list(str(project_id), page, page_size)


@router.get("/{analysis_id}", response_model=EcologyAnalysisRead)
def get_verified_ecology_analysis(
    project_id: UUID, analysis_id: UUID, session: DbSession
) -> EcologyAnalysisRead:
    return EcologyAnalysisService(session).get(str(project_id), str(analysis_id))


@router.get("/{analysis_id}/result.json", response_model=EcologyAnalysisSnapshot)
def download_verified_ecology_analysis(
    project_id: UUID, analysis_id: UUID, session: DbSession, response: Response
) -> EcologyAnalysisSnapshot:
    result = get_verified_ecology_analysis(project_id, analysis_id, session)
    response.headers["Content-Disposition"] = f'attachment; filename="ecology-{analysis_id}.json"'
    response.headers["X-ReefVision-Content-SHA256"] = result.content_sha256
    return result.snapshot


def _spreadsheet_text(value: str | None) -> str | None:
    if value is not None and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@router.get("/{analysis_id}/results.csv")
def export_verified_ecology_analysis(
    project_id: UUID, analysis_id: UUID, session: DbSession
) -> Response:
    record = get_verified_ecology_analysis(project_id, analysis_id, session)
    snapshot = record.snapshot
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    identifiers = (str(record.id), record.content_sha256, snapshot.method_version, record.stale)
    base_header = ("analysis_id", "content_sha256", "method_version", "stale")
    if isinstance(snapshot.result, AbundanceResult):
        writer.writerow(
            (
                *base_header,
                "sample_id",
                "image_id",
                "utc_survey_time",
                "experimental_unit_type",
                "experimental_unit_id",
                "raw_count",
                "surveyed_area_m2",
                "count_per_m2",
                "exclusion",
            )
        )
        for row in snapshot.result.visits:
            writer.writerow(
                (
                    *identifiers,
                    _spreadsheet_text(row.sample_id),
                    row.image_id,
                    row.observed_at.isoformat(),
                    row.experimental_unit_type,
                    _spreadsheet_text(row.experimental_unit_id),
                    row.count,
                    row.surveyed_area_m2,
                    row.density_per_m2,
                    None,
                )
            )
        for exclusion in snapshot.result.exclusions:
            writer.writerow(
                (
                    *identifiers,
                    _spreadsheet_text(exclusion.source),
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    _spreadsheet_text(exclusion.reason),
                )
            )
    else:
        writer.writerow(
            (
                *base_header,
                "organism_id",
                "metric",
                "unit",
                "first_utc",
                "last_utc",
                "baseline_observation",
                "final_observation",
                "first_value",
                "last_value",
                "elapsed_days",
                "absolute_change",
                "percent_change",
                "change_per_day",
                "exclusion",
            )
        )
        for change in snapshot.result.changes:
            writer.writerow(
                (
                    *identifiers,
                    _spreadsheet_text(change.organism_id),
                    change.metric_name,
                    _spreadsheet_text(change.unit),
                    change.first_observed_at.isoformat(),
                    change.last_observed_at.isoformat(),
                    change.baseline_source_record_id,
                    change.final_source_record_id,
                    change.initial_value,
                    change.final_value,
                    change.elapsed_days,
                    change.absolute_change,
                    change.percent_change,
                    change.change_per_day,
                    None,
                )
            )
        for exclusion in snapshot.result.exclusions:
            writer.writerow(
                (
                    *identifiers,
                    _spreadsheet_text(exclusion.source),
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    _spreadsheet_text(exclusion.reason),
                )
            )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="ecology-{analysis_id}.csv"'},
    )
