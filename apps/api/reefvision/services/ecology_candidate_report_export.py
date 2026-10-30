"""Reproducible, non-verifying CSV view of persisted ecological date-QC evidence."""

from __future__ import annotations

import csv
import json
from io import StringIO

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_measurement_candidates import (
    count_declared_ecological_units,
    summarize_projected_endpoint_changes,
    summarize_projected_population_summaries,
    summarize_projected_unit_summaries,
    summarize_projected_visit_coverage,
    summarize_sampling_date_qc,
)
from reefvision.storage.datasets import canonical_json_sha256

_SERIES_COLUMNS = (
    "project_id",
    "source_input_sha256",
    "report_sha256",
    "source_fingerprint_rechecked",
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
    "projected_endpoint_status",
    "baseline_image_id",
    "final_image_id",
    "absolute_change",
    "percent_change",
    "elapsed_days",
    "projected_absolute_change_per_day",
    "projected_endpoint_json",
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
    # model_copy(update=...) bypasses Pydantic validators. Check the source
    # geometry contract again before exporting re-signed in-memory artifacts.
    for candidate in response.candidates:
        try:
            candidate.consistent_geometry_dimension()
        except ValueError as exc:
            raise ValidationError("Ecological source geometry dimension mismatch") from exc

    # Reject a forged top-level candidate count before aggregate report checks,
    # so the failure is specific and independent of the stored QC histogram.
    if response.candidate_count != len(response.candidates):
        raise ValidationError("Ecological candidate count does not match source records")
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

    # The status histogram alone cannot detect a forged per-series source ID,
    # timestamp or QC decision. Reconcile every row with the actual candidate
    # records, including cross-organism image-replay checks, before exporting.
    expected_qc = {
        (row.organism_key, row.metric): row.model_dump(mode="json")
        for row in summarize_sampling_date_qc(response.candidates)
    }
    actual_qc = {
        (row.organism_key, row.metric): row.model_dump(mode="json")
        for row in response.sampling_date_qc
    }
    if actual_qc != expected_qc:
        raise ValidationError(
            "Ecological sampling-date QC evidence does not match source candidates"
        )

    # Recalculate endpoint arithmetic from source-linked candidates. Re-signing
    # an artifact must never authorize fabricated projected growth values.
    expected_endpoints = {
        (item.organism_key, item.metric): item.model_dump(mode="json")
        for item in summarize_projected_endpoint_changes(
            response.candidates, response.sampling_date_qc
        )
    }
    endpoint_rows = {
        (item.organism_key, item.metric): item for item in response.projected_endpoint_changes
    }
    actual_endpoints = {key: item.model_dump(mode="json") for key, item in endpoint_rows.items()}
    if len(endpoint_rows) != len(response.projected_endpoint_changes):
        raise ValidationError("Duplicate ecological projected endpoint evidence")
    if response.source_fingerprint_contract is not None:
        if actual_endpoints != expected_endpoints:
            raise ValidationError("Projected endpoint evidence does not match source candidates")
    else:
        # Older artifacts may lack endpoint records or daily-slope fields.
        # Preserve missing historical data rather than manufacturing values.
        optional_slopes = {
            "projected_absolute_change_per_day",
            "projected_baseline_percent_change_per_day",
        }
        for key, values in actual_endpoints.items():
            expected = expected_endpoints.get(key)
            if expected is None or any(
                value != expected.get(field)
                for field, value in values.items()
                if not (field in optional_slopes and value is None)
            ):
                raise ValidationError("Legacy projected endpoint evidence is inconsistent")

    # A valid checksum alone does not establish scientific integrity: an
    # imported/saved artifact can be altered and then re-signed. Recompute
    # every derived sampling-effort and unit-balanced aggregate from the
    # underlying linked candidates before allowing a reproducible CSV export.
    # Historical artifacts without this fingerprint contract remain readable
    # but are explicitly marked as not rechecked in the exported CSV.
    if response.source_fingerprint_contract is not None:
        expected_visits = summarize_projected_visit_coverage(response.candidates)
        expected_units = summarize_projected_unit_summaries(
            response.candidates,
            summarize_projected_endpoint_changes(response.candidates, response.sampling_date_qc),
        )
        expected_population = summarize_projected_population_summaries(expected_units)
        for label, actual_rows, expected_rows in (
            ("visit coverage", response.projected_visit_coverage, expected_visits),
            ("unit summaries", response.projected_unit_summaries, expected_units),
            ("population summaries", response.projected_population_summaries, expected_population),
        ):
            if [row.model_dump(mode="json") for row in actual_rows] != [
                row.model_dump(mode="json") for row in expected_rows
            ]:
                raise ValidationError(
                    f"Projected {label} evidence does not match source candidates"
                )

    # A report digest is meaningful only when the complete report is checked
    # against the candidate/series denominators that produced it. This is an
    # internal consistency check, not proof of scientist review or ownership.
    source_image_count = len({row.image_id for row in response.candidates})
    source_organism_count = len({row.organism_key for row in response.candidates})
    declared_unit_count = count_declared_ecological_units(
        response.candidates,
        canonicalize=response.source_fingerprint_contract == "ecology-measurement-candidates-0021",
    )
    if (
        report.source_image_count != source_image_count
        or report.source_organism_count != source_organism_count
        or report.declared_experimental_unit_count != declared_unit_count
        or report.excluded_source_count != len(response.exclusions)
    ):
        raise ValidationError("Ecological candidate report denominators do not match sources")
    report_values = {
        "algorithm_version": "ecology-candidate-report-0001",
        "project_id": response.project_id,
        "source_input_sha256": response.input_sha256,
        "candidate_count": len(response.candidates),
        "source_image_count": source_image_count,
        "source_organism_count": source_organism_count,
        "declared_experimental_unit_count": declared_unit_count,
        "date_qc_pass_series_count": report.date_qc_pass_series_count,
        "excluded_series_count": report.excluded_series_count,
        "excluded_source_count": len(response.exclusions),
        "qc_status_counts": dict(sorted(statuses.items())),
    }
    if report.report_sha256 != canonical_json_sha256(report_values):
        raise ValidationError(
            "Ecological candidate report fingerprint does not match source totals"
        )

    # Recompute the complete source digest for newly persisted artifacts.
    # Older Workflow Builder artifacts lack the two registry evidence hashes:
    # they remain readable but must be visibly marked as not rechecked.
    source_fingerprint_rechecked = response.source_fingerprint_contract is not None
    if source_fingerprint_rechecked:
        source_values = {
            "algorithm_version": response.source_fingerprint_contract,
            "project_id": response.project_id,
            "registry_history_sha256": response.source_registry_history_sha256,
            "registry_image_evidence_sha256": response.source_image_evidence_sha256,
            "registry_annotation_evidence_sha256": response.source_annotation_evidence_sha256,
            "registry_calibration_evidence_sha256": response.source_calibration_evidence_sha256,
            "candidates": [row.model_dump(mode="json") for row in response.candidates],
            # The producer hashes QC series in organism/metric order. Export
            # is order-independent for those same unique typed QC decisions;
            # never relax validation of the records or their contents.
            "sampling_date_qc": [
                row.model_dump(mode="json")
                for row in sorted(
                    response.sampling_date_qc,
                    key=lambda item: (item.organism_key, item.metric),
                )
            ],
            "projected_visit_coverage": [
                row.model_dump(mode="json") for row in response.projected_visit_coverage
            ],
            "projected_endpoint_changes": [
                row.model_dump(mode="json") for row in response.projected_endpoint_changes
            ],
            "projected_unit_summaries": [
                row.model_dump(mode="json") for row in response.projected_unit_summaries
            ],
            "projected_population_summaries": [
                row.model_dump(mode="json") for row in response.projected_population_summaries
            ],
            "exclusions": [row.model_dump(mode="json") for row in response.exclusions],
        }
        if canonical_json_sha256(source_values) != response.input_sha256:
            raise ValidationError("Ecological source input fingerprint does not match evidence")
    elif (
        response.source_image_evidence_sha256 is not None
        or response.source_annotation_evidence_sha256 is not None
    ):
        raise ValidationError("Ecological source fingerprint contract is missing")

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_SERIES_COLUMNS)
    for row in sorted(response.sampling_date_qc, key=lambda item: (item.organism_key, item.metric)):
        endpoint = endpoint_rows.get((row.organism_key, row.metric))
        writer.writerow(
            (
                report.project_id,
                report.source_input_sha256,
                report.report_sha256,
                str(source_fingerprint_rechecked).lower(),
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
                (
                    "projected_unverified"
                    if endpoint is not None
                    else (
                        "legacy_unavailable"
                        if row.qc_status == "date_series_candidate"
                        else "excluded_by_date_qc"
                    )
                ),
                _csv_identifier(endpoint.baseline_image_id) if endpoint is not None else "",
                _csv_identifier(endpoint.final_image_id) if endpoint is not None else "",
                endpoint.absolute_change if endpoint is not None else "",
                endpoint.percent_change if endpoint is not None else "",
                endpoint.elapsed_days if endpoint is not None else "",
                (
                    endpoint.projected_absolute_change_per_day
                    if endpoint is not None
                    and endpoint.projected_absolute_change_per_day is not None
                    else ""
                ),
                (
                    json.dumps(
                        endpoint.model_dump(mode="json"),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    if endpoint is not None
                    else ""
                ),
            )
        )
    return output.getvalue()
