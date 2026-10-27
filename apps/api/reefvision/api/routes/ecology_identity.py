"""Local-first project ecological identity registry endpoints."""

from __future__ import annotations

import csv
from io import StringIO
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.ecology_identity import (
    EcologyAnnotationEvidenceCreate,
    EcologyAnnotationEvidenceRow,
    EcologyCalibrationEvidenceCreate,
    EcologyCalibrationEvidenceRow,
    EcologyIdentityCreate,
    EcologyIdentityRegistryResponse,
    EcologyIdentityRevisionCreate,
    EcologyIdentityRow,
    EcologyImageEvidenceCreate,
    EcologyImageEvidenceRow,
)
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_candidate_measurements_export import (
    render_ecology_measurements_csv,
)
from reefvision.services.ecology_candidate_report_export import render_ecology_series_qc_csv
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.services.ecology_identity_history_export import render_ecology_identity_history_csv
from reefvision.services.ecology_measurement_candidates import EcologyMeasurementCandidateService
from reefvision.services.ecology_population_export import render_ecology_population_csv

router = APIRouter(tags=["ecological monitoring"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/projects/{project_id}/ecology/identity-registry",
    response_model=EcologyIdentityRegistryResponse,
)
def list_identity_registry(project_id: str, session: DbSession) -> EcologyIdentityRegistryResponse:
    return EcologyIdentityService(session).registry(project_id)


@router.get(
    "/projects/{project_id}/ecology/identity-registry/history.csv",
)
def export_ecology_identity_history(project_id: str, session: DbSession) -> Response:
    """Auditable unverified identity revisions, shared with typed workflow artifacts."""
    registry = EcologyIdentityService(session).registry(project_id)
    return Response(
        content=render_ecology_identity_history_csv(registry),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="reefvision-ecology-identity-history.csv"'
        },
    )


@router.get(
    "/projects/{project_id}/ecology/calibrated-measurement-candidates",
    response_model=EcologyMeasurementCandidatesResponse,
)
def list_calibrated_measurement_candidates(
    project_id: str, session: DbSession
) -> EcologyMeasurementCandidatesResponse:
    return EcologyMeasurementCandidateService(session).candidates(project_id)


@router.get(
    "/projects/{project_id}/ecology/calibrated-measurement-candidates/measurements.csv",
)
def export_ecology_source_measurements(project_id: str, session: DbSession) -> Response:
    """Reproducible source-level projected measurements; never verified growth."""
    response = EcologyMeasurementCandidateService(session).candidates(project_id)
    return Response(
        content=render_ecology_measurements_csv(response),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="reefvision-ecology-measurements.csv"'
        },
    )


@router.get(
    "/projects/{project_id}/ecology/calibrated-measurement-candidates/population.csv",
)
def export_ecology_population_summaries(project_id: str, session: DbSession) -> Response:
    """Rechecked, unverified declared-unit and population summary CSV."""
    response = EcologyMeasurementCandidateService(session).candidates(project_id)
    return Response(
        content=render_ecology_population_csv(response),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="reefvision-ecology-population.csv"'
        },
    )


@router.get(
    "/projects/{project_id}/ecology/calibrated-measurement-candidates/report.csv",
)
def export_ecology_candidate_report(project_id: str, session: DbSession) -> Response:
    """Deterministic QC/effort CSV; linked geometry remains unverified."""
    response = EcologyMeasurementCandidateService(session).candidates(project_id)
    report = response.candidate_report
    if report is None:
        raise RuntimeError("Ecological candidate report was not generated")
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "project_id",
            "source_input_sha256",
            "report_sha256",
            "qc_status",
            "series_count",
            "evidence_level",
            "review_gate",
        )
    )
    for qc_status, count in sorted(report.qc_status_counts.items()):
        writer.writerow(
            (
                report.project_id,
                report.source_input_sha256,
                report.report_sha256,
                qc_status,
                count,
                report.evidence_level,
                report.review_gate,
            )
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="reefvision-ecology-qc.csv"'},
    )


@router.get(
    "/projects/{project_id}/ecology/calibrated-measurement-candidates/report-series.csv",
)
def export_ecology_candidate_series_report(project_id: str, session: DbSession) -> Response:
    """Source-linked UTC date-QC decisions; never verified biological growth."""
    response = EcologyMeasurementCandidateService(session).candidates(project_id)
    return Response(
        content=render_ecology_series_qc_csv(response),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="reefvision-ecology-series-qc.csv"'},
    )


@router.post(
    "/projects/{project_id}/ecology/organisms",
    response_model=EcologyIdentityRow,
    status_code=status.HTTP_201_CREATED,
)
def register_organism(
    project_id: str, payload: EcologyIdentityCreate, session: DbSession
) -> EcologyIdentityRow:
    return EcologyIdentityService(session).register(project_id, payload)


@router.post(
    "/projects/{project_id}/ecology/organisms/{organism_key}/image-evidence",
    response_model=EcologyImageEvidenceRow,
    status_code=status.HTTP_201_CREATED,
)
def link_organism_image(
    project_id: str,
    organism_key: str,
    payload: EcologyImageEvidenceCreate,
    session: DbSession,
) -> EcologyImageEvidenceRow:
    return EcologyIdentityService(session).link_image(project_id, organism_key, payload)


@router.post(
    "/projects/{project_id}/ecology/organisms/{organism_key}/annotation-evidence",
    response_model=EcologyAnnotationEvidenceRow,
    status_code=status.HTTP_201_CREATED,
)
def link_organism_annotation(
    project_id: str,
    organism_key: str,
    payload: EcologyAnnotationEvidenceCreate,
    session: DbSession,
) -> EcologyAnnotationEvidenceRow:
    return EcologyIdentityService(session).link_annotation(project_id, organism_key, payload)


@router.post(
    "/projects/{project_id}/ecology/organisms/{organism_key}/calibration-evidence",
    response_model=EcologyCalibrationEvidenceRow,
    status_code=status.HTTP_201_CREATED,
)
def link_organism_calibration(
    project_id: str,
    organism_key: str,
    payload: EcologyCalibrationEvidenceCreate,
    session: DbSession,
) -> EcologyCalibrationEvidenceRow:
    return EcologyIdentityService(session).link_calibration(project_id, organism_key, payload)


@router.post(
    "/projects/{project_id}/ecology/organisms/{organism_key}/revisions",
    response_model=EcologyIdentityRow,
    status_code=status.HTTP_201_CREATED,
)
def revise_organism(
    project_id: str,
    organism_key: str,
    payload: EcologyIdentityRevisionCreate,
    session: DbSession,
) -> EcologyIdentityRow:
    return EcologyIdentityService(session).revise(project_id, organism_key, payload)
