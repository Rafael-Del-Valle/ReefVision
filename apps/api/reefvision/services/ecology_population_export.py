"""Reproducible unverified ecological unit and population summary CSV.

Only source-linked candidate geometry is exported. These are descriptive,
caller-registered experimental units, never independently verified replicates.
"""

from __future__ import annotations

import csv
import json
from io import StringIO

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_candidate_report_export import (
    _csv_identifier,
    render_ecology_series_qc_csv,
)

_COLUMNS = (
    "export_schema_version",
    "project_id",
    "source_input_sha256",
    "report_sha256",
    "row_type",
    "metric",
    "experimental_unit_type",
    "experimental_unit_id",
    "unit_status",
    "physical_units_json",
    "sampling_windows_utc_json",
    "organism_keys_json",
    "incomplete_organism_keys_json",
    "parent_colony_keys_json",
    "shared_parent_colony_keys_json",
    "units_missing_parent_colony_json",
    "design_review_blockers_json",
    "declared_unit_count",
    "contributing_organism_count",
    "mean_absolute_change",
    "mean_percent_change",
    "sample_sd_unit_absolute_change",
    "sample_sd_unit_percent_change",
    "independent_unit_inference_allowed",
    "evidence_level",
    "review_gate",
)


def _array(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _number(value: float | None) -> float | str:
    return "" if value is None else value


def render_ecology_population_csv(response: EcologyMeasurementCandidatesResponse) -> str:
    """Recheck all source and derived science before emitting unit-balanced results.

    Excluded unit rows remain visible with blank means and zero contributors.
    Population rows include only QC-eligible declared units; no p-values,
    independent-sample assertions, or verified biological growth are emitted.
    """
    if response.source_fingerprint_contract is None:
        raise ValidationError("Ecological population export requires a recheckable source")
    # This shared renderer independently verifies the complete source digest,
    # source-level QC, endpoint arithmetic, unit eligibility and population means.
    render_ecology_series_qc_csv(response)
    report = response.candidate_report
    if report is None:
        raise ValidationError("Ecological candidate report is missing")

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_COLUMNS)
    for row in sorted(
        response.projected_unit_summaries,
        key=lambda item: (
            item.experimental_unit_type or "",
            item.experimental_unit_id or "",
            item.metric,
        ),
    ):
        eligible = row.unit_status == "candidate"
        writer.writerow(
            (
                "ecology-population-export-0001",
                _csv_identifier(response.project_id),
                response.input_sha256,
                report.report_sha256,
                "declared_unit",
                row.metric,
                _csv_identifier(row.experimental_unit_type or ""),
                _csv_identifier(row.experimental_unit_id or ""),
                row.unit_status,
                _array(row.units),
                _array(row.sampling_windows_utc),
                _array(row.organism_keys),
                _array(row.incomplete_organism_keys),
                _array(row.parent_colony_keys),
                _array([]),
                _array([]),
                _array(["independence_not_authenticated"]),
                int(eligible),
                len(row.complete_organism_keys) if eligible else 0,
                _number(row.mean_absolute_change) if eligible else "",
                _number(row.mean_percent_change) if eligible else "",
                "",
                "",
                "false",
                row.evidence_level,
                row.review_gate,
            )
        )

    for row in sorted(
        response.projected_population_summaries,
        key=lambda item: (
            item.experimental_unit_type,
            item.metric,
            item.unit,
            item.sampling_window_utc,
        ),
    ):
        writer.writerow(
            (
                "ecology-population-export-0001",
                _csv_identifier(response.project_id),
                response.input_sha256,
                report.report_sha256,
                "population_stratum",
                row.metric,
                _csv_identifier(row.experimental_unit_type),
                "",
                "eligible_declared_units_only",
                _array([row.unit]),
                _array([row.sampling_window_utc]),
                _array(row.experimental_unit_ids),
                _array([]),
                _array(row.parent_colony_keys),
                _array(row.shared_parent_colony_keys),
                _array(row.units_missing_parent_colony),
                _array(row.design_review_blockers),
                row.declared_unit_count,
                row.contributing_organism_count,
                row.mean_unit_absolute_change,
                row.mean_unit_percent_change,
                _number(row.sample_sd_unit_absolute_change),
                _number(row.sample_sd_unit_percent_change),
                "false",
                row.evidence_level,
                row.review_gate,
            )
        )
    return output.getvalue()
