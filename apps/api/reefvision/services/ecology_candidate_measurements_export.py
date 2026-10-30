"""Deterministic, non-verifying export of individual ecological source measurements.

Exporting a source-linked projected measurement does not verify specimen
identity, calibration accuracy, experimental independence, or biological growth.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_candidate_report_export import (
    _csv_identifier,
    render_ecology_series_qc_csv,
)

MEASUREMENT_CSV_SCHEMA_VERSION = "ecology-measurement-export-0002"

_MEASUREMENT_COLUMNS = (
    "export_schema_version",
    "project_id",
    "source_input_sha256",
    "report_sha256",
    "source_fingerprint_rechecked",
    "source_fingerprint_contract",
    "source_registry_history_sha256",
    "source_image_evidence_sha256",
    "source_annotation_evidence_sha256",
    "source_calibration_evidence_sha256",
    "independent_unit_inference_allowed",
    "organism_key",
    "identity_revision",
    "parent_colony_key",
    "experimental_unit_type",
    "experimental_unit_id",
    "image_id",
    "image_sha256",
    "annotation_evidence_id",
    "calibration_evidence_id",
    "annotation_kind",
    "annotation_id",
    "annotation_revision",
    "annotation_sha256",
    "calibration_sha256",
    "metric",
    "value",
    "unit",
    "capture_timestamp_utc",
    "capture_time_status",
    "sampling_date_qc_status",
    "evidence_level",
    "review_gate",
)


def _utc_capture(value: datetime | None, status: str) -> str:
    """Never emit an apparently dated observation with an ambiguous timezone."""
    if value is None:
        if status == "timezone_aware":
            raise ValidationError("Dated ecological source is missing its capture timestamp")
        return ""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError("Ecological source timestamp lacks timezone provenance")
    if status != "timezone_aware":
        raise ValidationError("Ecological source timestamp status conflicts with its value")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def render_ecology_measurements_csv(response: EcologyMeasurementCandidatesResponse) -> str:
    """Export one source-linked row per candidate with independently rechecked QC.

    The existing series report performs the complete source fingerprint,
    derived-metric and denominator reconciliation. Reuse it rather than
    creating a second, weaker scientific acceptance path.
    """
    render_ecology_series_qc_csv(response)
    report = response.candidate_report
    if report is None:
        raise ValidationError("Ecological candidate report is missing")
    qc_by_series = {
        (row.organism_key, row.metric): row.qc_status for row in response.sampling_date_qc
    }
    rows = []
    for candidate in response.candidates:
        capture_utc = _utc_capture(candidate.capture_timestamp_utc, candidate.capture_time_status)
        qc_status = qc_by_series.get((candidate.organism_key, candidate.metric))
        if qc_status is None:
            raise ValidationError("Ecological measurement lacks a source QC decision")
        rows.append((candidate, capture_utc, qc_status))
    rows.sort(
        key=lambda item: (
            item[0].organism_key,
            item[0].metric,
            item[1],
            item[0].image_id,
            item[0].annotation_evidence_id,
            item[0].calibration_evidence_id,
        )
    )

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_MEASUREMENT_COLUMNS)
    for candidate, capture_utc, qc_status in rows:
        writer.writerow(
            (
                MEASUREMENT_CSV_SCHEMA_VERSION,
                _csv_identifier(response.project_id),
                response.input_sha256,
                report.report_sha256,
                str(response.source_fingerprint_contract is not None).lower(),
                response.source_fingerprint_contract or "",
                response.source_registry_history_sha256 or "",
                response.source_image_evidence_sha256 or "",
                response.source_annotation_evidence_sha256 or "",
                response.source_calibration_evidence_sha256 or "",
                "false",
                _csv_identifier(candidate.organism_key),
                candidate.identity_revision,
                _csv_identifier(candidate.parent_colony_key or ""),
                _csv_identifier(candidate.experimental_unit_type or ""),
                _csv_identifier(candidate.experimental_unit_id or ""),
                _csv_identifier(candidate.image_id),
                candidate.image_sha256,
                _csv_identifier(candidate.annotation_evidence_id),
                _csv_identifier(candidate.calibration_evidence_id),
                candidate.annotation_kind,
                _csv_identifier(candidate.annotation_id),
                candidate.annotation_revision,
                candidate.annotation_sha256,
                candidate.calibration_sha256,
                candidate.metric,
                candidate.value,
                _csv_identifier(candidate.unit),
                capture_utc,
                candidate.capture_time_status,
                qc_status,
                candidate.evidence_level,
                candidate.review_gate,
            )
        )
    return output.getvalue()
