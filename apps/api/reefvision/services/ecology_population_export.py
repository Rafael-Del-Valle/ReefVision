"""Reproducible unverified ecological unit and population summary CSV.

Only source-linked candidate geometry is exported. These are descriptive,
caller-registered experimental units, never independently verified replicates.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from io import StringIO
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_candidate_report_export import (
    _csv_identifier,
    render_ecology_series_qc_csv,
)

_EXPORT_SCHEMA_VERSION = "ecology-population-export-0004"

_COLUMNS = (
    "export_schema_version",
    "project_id",
    "source_input_sha256",
    "report_sha256",
    "source_fingerprint_rechecked",
    "source_fingerprint_contract",
    "source_candidate_count",
    "source_image_count",
    "source_organism_count",
    "source_excluded_count",
    "source_declared_experimental_unit_count",
    "source_date_qc_pass_series_count",
    "source_excluded_series_count",
    "source_registry_history_sha256",
    "source_image_evidence_sha256",
    "source_annotation_evidence_sha256",
    "source_calibration_evidence_sha256",
    "row_type",
    "metric",
    "experimental_unit_type",
    "experimental_unit_id",
    "experimental_unit_ids_json",
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


def _array(values: Sequence[str]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _number(value: float | None) -> float | str:
    return "" if value is None else value


def _write_checked_row(writer: Any, values: tuple[object, ...]) -> None:
    """Reject silent CSV column misalignment before emitting a science row."""
    if len(values) != len(_COLUMNS):
        raise ValidationError("Ecological population CSV column count does not match schema")
    if len(set(_COLUMNS)) != len(_COLUMNS):
        raise ValidationError("Ecological population CSV has duplicate column names")
    row = dict(zip(_COLUMNS, values, strict=True))
    if (
        row["source_fingerprint_rechecked"] != "true"
        or row["evidence_level"] != "linked_unverified"
        or row["review_gate"] != "scientist_review_required"
        or row["independent_unit_inference_allowed"] != "false"
    ):
        raise ValidationError(
            "Ecological population CSV cannot claim verified evidence or inference"
        )
    declared = row["declared_unit_count"]
    organisms = row["contributing_organism_count"]
    if (
        not isinstance(declared, int)
        or isinstance(declared, bool)
        or not isinstance(organisms, int)
        or isinstance(organisms, bool)
    ):
        raise ValidationError("Ecological population CSV denominators must be integer counts")
    if row["row_type"] == "declared_unit":
        if declared not in (0, 1) or (declared == 0 and organisms != 0) or organisms < 0:
            raise ValidationError("Ecological population CSV invalid declared-unit denominator")
        # A CSV serializer must not turn one candidate tank into several
        # independent units, or hide an excluded unit behind a candidate label.
        try:
            unit_ids = json.loads(str(row["experimental_unit_ids_json"]))
            blockers = json.loads(str(row["design_review_blockers_json"]))
        except (TypeError, ValueError) as exc:
            raise ValidationError("Ecological population CSV invalid declared-unit roster") from exc
        if (
            not isinstance(unit_ids, list)
            or len(unit_ids) > 1
            or any(not isinstance(key, str) or not key.strip() for key in unit_ids)
            or [_csv_identifier(key) for key in unit_ids]
            != ([row["experimental_unit_id"]] if row["experimental_unit_id"] else [])
        ):
            raise ValidationError("Ecological population CSV invalid declared-unit roster")
        if blockers != ["independence_not_authenticated"]:
            raise ValidationError("Ecological population CSV invalid declared-unit review gate")
        if row["unit_status"] == "candidate":
            if (
                declared != 1
                or not unit_ids
                or organisms < 1
                or row["mean_absolute_change"] == ""
            ):
                raise ValidationError("Ecological population CSV invalid candidate declared-unit")
        elif row["unit_status"] in (
            "missing_unit_declaration",
            "technical_replicate_unit",
            "mixed_units",
            "incomplete_followup",
            "sampling_window_mismatch",
        ):
            if (
                declared != 0
                or organisms != 0
                or row["mean_absolute_change"] != ""
                or row["mean_percent_change"] != ""
            ):
                raise ValidationError("Ecological population CSV invalid excluded declared-unit")
        else:
            raise ValidationError("Ecological population CSV invalid declared-unit status")
    elif row["row_type"] == "population_stratum":
        if declared < 1 or organisms < declared:
            raise ValidationError("Ecological population CSV invalid population denominator")
        # Independently check the serialized scientific review roster.
        # Source recomputation protects artifacts; this boundary also protects
        # against a future CSV serializer manufacturing independent units.
        try:
            unit_ids = json.loads(str(row["experimental_unit_ids_json"]))
            missing = json.loads(str(row["units_missing_parent_colony_json"]))
            blockers = json.loads(str(row["design_review_blockers_json"]))
        except (TypeError, ValueError) as exc:
            raise ValidationError("Ecological population CSV invalid review roster") from exc
        if (
            not isinstance(unit_ids, list)
            or len(unit_ids) != declared
            or any(not isinstance(key, str) or not key.strip() for key in unit_ids)
            or len(set(unit_ids)) != declared
        ):
            raise ValidationError("Ecological population CSV invalid population unit roster")
        if (
            not isinstance(missing, list)
            or any(not isinstance(key, str) or key not in unit_ids for key in missing)
            or len(set(missing)) != len(missing)
        ):
            raise ValidationError("Ecological population CSV invalid missing-parent roster")
        if not isinstance(blockers, list) or any(
            not isinstance(blocker, str) for blocker in blockers
        ):
            raise ValidationError("Ecological population CSV invalid review blockers")
        if ("missing_parent_colony" in blockers) != bool(missing):
            raise ValidationError(
                "Ecological population CSV missing-parent review blocker mismatch"
            )
        if "independence_not_authenticated" not in blockers or (
            "single_declared_unit" in blockers
        ) != (declared == 1):
            raise ValidationError(
                "Ecological population CSV independent-unit review blockers mismatch"
            )
    else:
        raise ValidationError("Ecological population CSV row type is invalid")
    writer.writerow(values)


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
    source_provenance = (
        "true",
        response.source_fingerprint_contract,
        report.candidate_count,
        report.source_image_count,
        report.source_organism_count,
        report.excluded_source_count,
        report.declared_experimental_unit_count,
        report.date_qc_pass_series_count,
        report.excluded_series_count,
        response.source_registry_history_sha256 or "",
        response.source_image_evidence_sha256 or "",
        response.source_annotation_evidence_sha256 or "",
        response.source_calibration_evidence_sha256 or "",
    )
    for row in sorted(
        response.projected_unit_summaries,
        key=lambda item: (
            item.experimental_unit_type or "",
            item.experimental_unit_id or "",
            item.metric,
        ),
    ):
        eligible = row.unit_status == "candidate"
        _write_checked_row(
            writer,
            (
                _EXPORT_SCHEMA_VERSION,
                _csv_identifier(response.project_id),
                response.input_sha256,
                report.report_sha256,
                *source_provenance,
                "declared_unit",
                row.metric,
                _csv_identifier(row.experimental_unit_type or ""),
                _csv_identifier(row.experimental_unit_id or ""),
                _array([row.experimental_unit_id] if row.experimental_unit_id else []),
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
            ),
        )

    for population_row in sorted(
        response.projected_population_summaries,
        key=lambda item: (
            item.experimental_unit_type,
            item.metric,
            item.unit,
            item.sampling_window_utc,
        ),
    ):
        _write_checked_row(
            writer,
            (
                _EXPORT_SCHEMA_VERSION,
                _csv_identifier(response.project_id),
                response.input_sha256,
                report.report_sha256,
                *source_provenance,
                "population_stratum",
                population_row.metric,
                _csv_identifier(population_row.experimental_unit_type or ""),
                "",
                _array(population_row.experimental_unit_ids),
                "eligible_declared_units_only",
                _array([population_row.unit]),
                _array([population_row.sampling_window_utc]),
                _array([]),
                _array([]),
                _array(population_row.parent_colony_keys),
                _array(population_row.shared_parent_colony_keys),
                _array(population_row.units_missing_parent_colony),
                _array(population_row.design_review_blockers),
                population_row.declared_unit_count,
                population_row.contributing_organism_count,
                population_row.mean_unit_absolute_change,
                population_row.mean_unit_percent_change,
                _number(population_row.sample_sd_unit_absolute_change),
                _number(population_row.sample_sd_unit_percent_change),
                "false",
                population_row.evidence_level,
                population_row.review_gate,
            ),
        )
    return output.getvalue()
