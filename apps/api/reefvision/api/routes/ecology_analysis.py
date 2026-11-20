"""Project-scoped history and exports for reviewed ecological analyses."""

from __future__ import annotations

import csv
import json
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
from reefvision.schemas.paired_growth_contrast import (
    PairedGrowthContrastReport,
    PairedGrowthContrastRequest,
)
from reefvision.services.ecology_analysis import EcologyAnalysisService
from reefvision.services.paired_growth_contrast import paired_growth_contrast

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


@router.get(
    "/{analysis_id}/result.json",
    response_model=EcologyAnalysisSnapshot,
    response_model_exclude_unset=True,
)
def download_verified_ecology_analysis(
    project_id: UUID, analysis_id: UUID, session: DbSession, response: Response
) -> EcologyAnalysisSnapshot:
    result = get_verified_ecology_analysis(project_id, analysis_id, session)
    response.headers["Content-Disposition"] = f'attachment; filename="ecology-{analysis_id}.json"'
    response.headers["X-ReefVision-Content-SHA256"] = result.content_sha256
    return result.snapshot


@router.post("/{analysis_id}/paired-contrast", response_model=PairedGrowthContrastReport)
def calculate_paired_growth_contrast(
    project_id: UUID,
    analysis_id: UUID,
    payload: PairedGrowthContrastRequest,
    session: DbSession,
) -> PairedGrowthContrastReport:
    return paired_growth_contrast(session, str(project_id), str(analysis_id), payload)


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
        scheduled = bool(snapshot.result.planned_sampling_effort)
        schedule_columns = (
            (
                "row_type",
                "experimental_unit_id",
                "sampling_date",
                "observed_organisms",
                "missing_observations",
            )
            if scheduled
            else ()
        )
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
                *schedule_columns,
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
                    *(("organism_change", None, None, None, None) if scheduled else ()),
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
                    *(("exclusion", None, None, None, None) if scheduled else ()),
                )
            )
        for visit in snapshot.result.planned_sampling_date_coverage:
            writer.writerow(
                (
                    *identifiers,
                    None,
                    visit.metric_name,
                    *(None,) * 12,
                    "scheduled_date",
                    _spreadsheet_text(visit.experimental_unit_id),
                    visit.sampling_date,
                    json.dumps(visit.observed_organism_ids, ensure_ascii=False),
                    json.dumps(visit.missing_organism_ids, ensure_ascii=False),
                )
            )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="ecology-{analysis_id}.csv"'},
    )
