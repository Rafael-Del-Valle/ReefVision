"""Reproducible, non-verifying CSV view of persisted ecological date-QC evidence."""

from __future__ import annotations

import csv
import json
from io import StringIO

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_measurement_candidates import EcologyMeasurementCandidatesResponse


_SERIES_COLUMNS = (
    "project_id",
    "source_input_sha256",
    "report_sha256",
    "organism_key",
    "metric",
    "qc_status",
    "candidate_count",
    "units_json",
    "sampling_dates_utc_json",
    "source_image_ids_json",
    "duplicate_sampling_dates_utc_json",
    "missing_timestamp_image_ids_json",
    "reused_image_ids_json",
    "reused_image_sha256_json",
    "conflicting_source_image_ids_json",
    "conflicting_source_image_sha256_json",
    "evidence_level",
    "review_gate",
)


def _json_array(values: list[str]) -> str:
    """Retain unambiguous identifiers, even when IDs contain delimiters."""
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _csv_identifier(value: str) -> str:
    """Prevent spreadsheet formula execution for user-controlled organism IDs."""
    if value and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def render_ecology_series_qc_csv(response: EcologyMeasurementCandidatesResponse) -> str:
    """Export one QC decision per organism/metric, without claiming verified growth.

    Source image lists and UTC dates are JSON arrays inside CSV cells. The
    identical typed QC records are persisted by the Workflow Builder source.
    """
    report = response.candidate_report
    if report is None:
        raise ValidationError("Ecological candidate report is missing")
    if (
        report.project_id != response.project_id
        or report.source_input_sha256 != response.input_sha256
    ):
        raise ValidationError("Ecological candidate report source fingerprint mismatch")
    statuses: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for row in response.sampling_date_qc:
        key = (row.organism_key, row.metric)
        if key in seen:
            raise ValidationError("Duplicate ecological sampling-date QC series")
        seen.add(key)
        statuses[row.qc_status] = statuses.get(row.qc_status, 0) + 1
    if (
        statuses != report.qc_status_counts
        or sum(statuses.values()) != report.date_qc_pass_series_count + report.excluded_series_count
        or statuses.get("date_series_candidate", 0) != report.date_qc_pass_series_count
        or report.candidate_count != response.candidate_count
    ):
        raise ValidationError("Ecological candidate report QC totals do not match source series")

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_SERIES_COLUMNS)
    for row in sorted(response.sampling_date_qc, key=lambda item: (item.organism_key, item.metric)):
        writer.writerow(
            (
                report.project_id,
                report.source_input_sha256,
                report.report_sha256,
                _csv_identifier(row.organism_key),
                row.metric,
                row.qc_status,
                row.candidate_count,
                _json_array(row.units),
                _json_array(row.sampling_dates_utc),
                _json_array(row.source_image_ids),
                _json_array(row.duplicate_sampling_dates_utc),
                _json_array(row.missing_timestamp_image_ids),
                _json_array(row.reused_image_ids),
                _json_array(row.reused_image_sha256),
                _json_array(row.conflicting_source_image_ids),
                _json_array(row.conflicting_source_image_sha256),
                row.evidence_level,
                row.review_gate,
            )
        )
    return output.getvalue()
