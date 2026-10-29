"""Deterministic, unverified human-model comparison CSV for scientist review."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from io import StringIO

from pydantic import ValidationError as SchemaValidationError

from reefvision.domain.errors import ValidationError
from reefvision.domain.scientific_mean import finite_descriptive_mean
from reefvision.schemas.model_agreement import PairedCountComparisonResponse
from reefvision.services.ecology_candidate_report_export import _csv_identifier

_EXPORT_VERSION = "ecology-paired-count-csv-0004"
_COLUMNS = (
    "export_schema_version",
    "source_input_sha256",
    "algorithm_version",
    "evidence_level",
    "review_status",
    "independent_inference_allowed",
    "reference_kind",
    "metric_name",
    "row_type",
    "experimental_unit_type",
    "experimental_unit_id",
    "organism_id",
    "observation_id",
    "reference_source_record_id",
    "model_source_record_id",
    "reference_count",
    "model_count",
    "signed_difference",
    "absolute_difference",
    "signed_percent_deviation",
    "absolute_percent_deviation",
    "paired_observation_count",
    "repeated_observation_count",
    "observed_organism_count",
    "nonzero_reference_count",
    "overcount_pair_count",
    "undercount_pair_count",
    "exact_match_pair_count",
    "overcount_organism_count",
    "undercount_organism_count",
    "balanced_organism_count",
    "mean_signed_bias",
    "mean_absolute_error",
    "mean_signed_percent_deviation",
    "mean_absolute_percent_deviation",
    "organism_balanced_mean_signed_bias",
    "organism_balanced_mean_absolute_error",
    "organism_balanced_mean_signed_percent_deviation",
    "organism_balanced_mean_absolute_percent_deviation",
    "unit_balanced_mean_signed_bias",
    "unit_balanced_mean_absolute_error",
    "unit_balanced_mean_signed_percent_deviation",
    "unit_balanced_mean_absolute_percent_deviation",
    "organism_and_unit_balanced_mean_signed_bias",
    "organism_and_unit_balanced_mean_absolute_error",
    "organism_and_unit_balanced_mean_signed_percent_deviation",
    "organism_and_unit_balanced_mean_absolute_percent_deviation",
    "percent_contributing_organism_count",
    "percent_contributing_independent_unit_count",
    "declared_independent_unit_count",
    "shared_parent_colony_ids_json",
    "summary_json",
)


def _optional_number(value: float | int | None) -> float | int | str:
    return "" if value is None else value


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def render_paired_count_csv(comparison: PairedCountComparisonResponse) -> str:
    """Export raw pairs, declared-unit summaries, and one global descriptive row.

    This is not an authenticated measurement or independent-replicate report.
    The typed result is revalidated on read-back, including workflow artifacts.
    """
    if comparison.analysis_provenance.algorithm_version != "ecology-paired-count-0007":
        raise ValidationError("Paired count CSV requires the current validated result contract")
    try:
        checked = PairedCountComparisonResponse.model_validate(comparison.model_dump(mode="json"))
    except SchemaValidationError as exc:
        raise ValidationError("Paired count CSV source artifact failed integrity checks") from exc

    source_ids = [
        source
        for pair in checked.paired_differences
        for source in (pair.reference_source_record_id, pair.model_source_record_id)
    ]
    if sorted(source_ids) != sorted(checked.analysis_provenance.source_record_ids):
        raise ValidationError("Paired count CSV source roster disagrees with provenance")

    unit_by_organism = {
        organism: unit.experimental_unit_id
        for unit in checked.unit_summaries
        for organism in unit.observation_counts_by_organism
    }
    common = {
        "export_schema_version": _EXPORT_VERSION,
        "source_input_sha256": checked.analysis_provenance.canonical_input_sha256,
        "algorithm_version": checked.analysis_provenance.algorithm_version,
        "evidence_level": checked.evidence_level,
        "review_status": checked.review_status,
        "independent_inference_allowed": "false",
        "reference_kind": checked.reference_kind,
        "metric_name": _csv_identifier(checked.metric_name),
        "experimental_unit_type": _csv_identifier(checked.experimental_unit_type or ""),
    }
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_COLUMNS, lineterminator="\n")
    writer.writeheader()

    def write(row_type: str, **values: object) -> None:
        writer.writerow({**common, "row_type": row_type, **values})

    by_organism = defaultdict(list)
    for pair in sorted(checked.paired_differences, key=lambda row: row.observation_id):
        by_organism[pair.organism_id].append(pair)
        write(
            "pair",
            experimental_unit_id=_csv_identifier(unit_by_organism.get(pair.organism_id, "")),
            organism_id=_csv_identifier(pair.organism_id),
            observation_id=_csv_identifier(pair.observation_id),
            reference_source_record_id=_csv_identifier(pair.reference_source_record_id),
            model_source_record_id=_csv_identifier(pair.model_source_record_id),
            reference_count=pair.reference_count,
            model_count=pair.model_count,
            signed_difference=pair.signed_difference,
            absolute_difference=pair.absolute_difference,
            signed_percent_deviation=_optional_number(pair.signed_percent_deviation),
            absolute_percent_deviation=_optional_number(pair.absolute_percent_deviation),
        )

    # One descriptive row per organism: repeated photographs are not replicates.
    # The independently declared experimental unit remains unverified.
    for organism_id, rows in sorted(by_organism.items()):
        eligible_signed = [
            row.signed_percent_deviation for row in rows if row.signed_percent_deviation is not None
        ]
        eligible_absolute = [
            row.absolute_percent_deviation
            for row in rows
            if row.absolute_percent_deviation is not None
        ]
        organism_bias = finite_descriptive_mean(row.signed_difference for row in rows)
        write(
            "organism_descriptive",
            experimental_unit_id=_csv_identifier(unit_by_organism.get(organism_id, "")),
            organism_id=_csv_identifier(organism_id),
            paired_observation_count=len(rows),
            repeated_observation_count=len(rows) - 1,
            observed_organism_count=1,
            nonzero_reference_count=len(eligible_absolute),
            overcount_pair_count=sum(row.signed_difference > 0 for row in rows),
            undercount_pair_count=sum(row.signed_difference < 0 for row in rows),
            exact_match_pair_count=sum(row.signed_difference == 0 for row in rows),
            overcount_organism_count=int(organism_bias > 0),
            undercount_organism_count=int(organism_bias < 0),
            balanced_organism_count=int(organism_bias == 0),
            mean_signed_bias=organism_bias,
            mean_absolute_error=finite_descriptive_mean(row.absolute_difference for row in rows),
            mean_signed_percent_deviation=(
                finite_descriptive_mean(eligible_signed) if eligible_signed else ""
            ),
            mean_absolute_percent_deviation=(
                finite_descriptive_mean(eligible_absolute) if eligible_absolute else ""
            ),
            summary_json=_json(
                {
                    "analysis_level": "organism_descriptive",
                    "observation_ids": [row.observation_id for row in rows],
                    "zero_reference_count": len(rows) - len(eligible_absolute),
                }
            ),
        )

    for unit in sorted(checked.unit_summaries, key=lambda row: row.experimental_unit_id):
        write(
            "declared_unit",
            experimental_unit_id=_csv_identifier(unit.experimental_unit_id),
            paired_observation_count=unit.paired_observation_count,
            observed_organism_count=unit.organism_count,
            nonzero_reference_count=unit.nonzero_reference_count,
            repeated_observation_count=unit.repeated_pair_count_beyond_first_per_organism,
            overcount_pair_count=unit.overcount_pair_count,
            undercount_pair_count=unit.undercount_pair_count,
            exact_match_pair_count=unit.exact_match_pair_count,
            overcount_organism_count=unit.overcount_organism_count,
            undercount_organism_count=unit.undercount_organism_count,
            balanced_organism_count=unit.balanced_organism_count,
            mean_signed_bias=unit.mean_signed_bias,
            mean_absolute_error=unit.mean_absolute_error,
            mean_signed_percent_deviation=_optional_number(unit.mean_signed_percent_deviation),
            mean_absolute_percent_deviation=_optional_number(unit.mean_absolute_percent_deviation),
            organism_balanced_mean_signed_bias=unit.organism_balanced_mean_signed_bias,
            organism_balanced_mean_absolute_error=unit.organism_balanced_mean_absolute_error,
            organism_balanced_mean_signed_percent_deviation=_optional_number(
                unit.organism_balanced_mean_signed_percent_deviation
            ),
            organism_balanced_mean_absolute_percent_deviation=_optional_number(
                unit.organism_balanced_mean_absolute_percent_deviation
            ),
            percent_contributing_organism_count=unit.percent_contributing_organism_count,
            summary_json=_json(unit.model_dump(mode="json")),
        )

    write(
        "overall",
        paired_observation_count=checked.paired_observation_count,
        observed_organism_count=checked.observed_organism_count,
        nonzero_reference_count=checked.nonzero_reference_count,
        repeated_observation_count=checked.repeated_pair_count_beyond_first_per_organism,
        overcount_pair_count=checked.overcount_pair_count,
        undercount_pair_count=checked.undercount_pair_count,
        exact_match_pair_count=checked.exact_match_pair_count,
        overcount_organism_count=checked.overcount_organism_count,
        undercount_organism_count=checked.undercount_organism_count,
        balanced_organism_count=checked.balanced_organism_count,
        mean_signed_bias=checked.mean_signed_bias,
        mean_absolute_error=checked.mean_absolute_error,
        mean_signed_percent_deviation=_optional_number(checked.mean_signed_percent_deviation),
        mean_absolute_percent_deviation=_optional_number(checked.mean_absolute_percent_deviation),
        unit_balanced_mean_signed_bias=_optional_number(checked.unit_balanced_mean_signed_bias),
        unit_balanced_mean_absolute_error=_optional_number(
            checked.unit_balanced_mean_absolute_error
        ),
        unit_balanced_mean_signed_percent_deviation=_optional_number(
            checked.unit_balanced_mean_signed_percent_deviation
        ),
        unit_balanced_mean_absolute_percent_deviation=_optional_number(
            checked.unit_balanced_mean_absolute_percent_deviation
        ),
        organism_and_unit_balanced_mean_signed_bias=_optional_number(
            checked.organism_and_unit_balanced_mean_signed_bias
        ),
        organism_and_unit_balanced_mean_absolute_error=_optional_number(
            checked.organism_and_unit_balanced_mean_absolute_error
        ),
        organism_and_unit_balanced_mean_signed_percent_deviation=_optional_number(
            checked.organism_and_unit_balanced_mean_signed_percent_deviation
        ),
        organism_and_unit_balanced_mean_absolute_percent_deviation=_optional_number(
            checked.organism_and_unit_balanced_mean_absolute_percent_deviation
        ),
        percent_contributing_organism_count=_optional_number(
            checked.percent_contributing_organism_count
        ),
        percent_contributing_independent_unit_count=_optional_number(
            checked.percent_contributing_independent_unit_count
        ),
        declared_independent_unit_count=_optional_number(checked.declared_independent_unit_count),
        shared_parent_colony_ids_json=_json(checked.cross_unit_shared_parent_colony_ids),
        summary_json=_json(checked.model_dump(mode="json", exclude={"paired_differences"})),
    )
    return output.getvalue()
