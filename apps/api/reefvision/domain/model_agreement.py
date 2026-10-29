"""Descriptive human-model paired counts; never infer independent replication."""

from __future__ import annotations

import math
from collections import defaultdict

from reefvision.domain.ecology_lineage_policy import (
    canonical_declared_unit_type,
    cross_unit_shared_parent_colony_ids,
    ecological_unit_types_equivalent,
    validate_declared_lineage,
)
from reefvision.domain.errors import ValidationError
from reefvision.domain.scientific_input_provenance import scientific_input_provenance
from reefvision.domain.scientific_mean import finite_descriptive_mean
from reefvision.schemas.model_agreement import (
    PairedCountComparisonRequest,
    PairedCountComparisonResponse,
    PairedCountDifference,
    PairedCountUnitSummary,
)


def compare_paired_counts(
    request: PairedCountComparisonRequest,
) -> PairedCountComparisonResponse:
    """Compare same-observation pairs, without claiming project verification."""
    pairs = request.pairs
    metrics = {item.metric_name for item in pairs}
    if len(metrics) != 1:
        raise ValidationError("Compare one metric at a time; mixed metrics cannot be pooled")

    identifiers = [item.observation_id for item in pairs]
    reference_sources = [item.reference_source_record_id for item in pairs]
    model_sources = [item.model_source_record_id for item in pairs]
    if any(
        len(set(values)) != len(values)
        for values in (identifiers, reference_sources, model_sources)
    ):
        raise ValidationError("Paired observations and source record IDs must be unique")
    if set(reference_sources).intersection(model_sources):
        raise ValidationError("Human-reference and model source record IDs must be distinct")

    unit_types = {item.experimental_unit_type for item in pairs if item.experimental_unit_type}
    canonical_type = canonical_declared_unit_type(unit_types)
    if unit_types and canonical_type is None:
        raise ValidationError("Pairs declare conflicting experimental unit types")
    unit_type = request.experimental_unit_type or canonical_type
    if (
        canonical_type is not None
        and unit_type is not None
        and not ecological_unit_types_equivalent(unit_type, canonical_type)
    ):
        raise ValidationError("Request and pairs disagree on experimental unit type")
    if unit_type is None and any(item.experimental_unit_id is not None for item in pairs):
        raise ValidationError("experimental_unit_type is required when unit IDs are supplied")
    if unit_type is not None and any(item.experimental_unit_id is None for item in pairs):
        raise ValidationError("All paired observations require experimental_unit_id")
    memberships: dict[str, str] = {}
    for item in pairs:
        if (
            item.experimental_unit_type is not None
            and unit_type is not None
            and not ecological_unit_types_equivalent(item.experimental_unit_type, unit_type)
        ):
            raise ValidationError("Pair experimental unit type conflicts with the request")
        if unit_type is not None:
            assert item.experimental_unit_id is not None
            existing = memberships.setdefault(item.organism_id, item.experimental_unit_id)
            if existing != item.experimental_unit_id:
                raise ValidationError("An organism cannot change experimental units")

    validate_declared_lineage(pairs, experimental_unit_type=unit_type)

    differences: list[PairedCountDifference] = []
    pair_counts_by_organism: dict[str, int] = defaultdict(int)
    by_unit: dict[str, list[PairedCountDifference]] = defaultdict(list)
    unit_organisms: dict[str, set[str]] = defaultdict(set)
    by_unit_organism: dict[str, dict[str, list[PairedCountDifference]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in sorted(pairs, key=lambda pair: pair.observation_id):
        signed = item.model_count - item.reference_count
        absolute = abs(signed)
        signed_percent = (
            signed / item.reference_count * 100 if item.reference_count > 0 else None
        )
        percent = abs(signed_percent) if signed_percent is not None else None
        if any(not math.isfinite(value) for value in (signed, absolute)):
            raise ValidationError("Paired count difference is not finite")
        if signed_percent is not None and not math.isfinite(signed_percent):
            raise ValidationError("Paired percent deviation is not finite")
        row = PairedCountDifference(
            observation_id=item.observation_id,
            organism_id=item.organism_id,
            reference_source_record_id=item.reference_source_record_id,
            model_source_record_id=item.model_source_record_id,
            reference_count=item.reference_count,
            model_count=item.model_count,
            signed_difference=signed,
            absolute_difference=absolute,
            absolute_percent_deviation=percent,
            signed_percent_deviation=signed_percent,
        )
        differences.append(row)
        pair_counts_by_organism[item.organism_id] += 1
        if unit_type is not None:
            assert item.experimental_unit_id is not None
            by_unit[item.experimental_unit_id].append(row)
            unit_organisms[item.experimental_unit_id].add(item.organism_id)
            by_unit_organism[item.experimental_unit_id][item.organism_id].append(row)

    valid_percent = [
        row.absolute_percent_deviation
        for row in differences
        if row.absolute_percent_deviation is not None
    ]
    valid_signed_percent = [
        row.signed_percent_deviation
        for row in differences
        if row.signed_percent_deviation is not None
    ]
    unit_summaries = []
    percent_contributing_organisms = 0
    for unit_id, rows in sorted(by_unit.items()):
        organism_rows = by_unit_organism[unit_id]
        counts_by_organism = {
            organism: len(organism_rows[organism]) for organism in sorted(organism_rows)
        }
        # Repeated images must not outweigh another organism in the same unit.
        organism_biases = [
            finite_descriptive_mean(row.signed_difference for row in organism_rows[organism])
            for organism in sorted(organism_rows)
        ]
        organism_errors = [
            finite_descriptive_mean(row.absolute_difference for row in organism_rows[organism])
            for organism in sorted(organism_rows)
        ]
        valid_unit_percent = [
            row.absolute_percent_deviation
            for row in rows
            if row.absolute_percent_deviation is not None
        ]
        organism_percents = []
        organism_signed_percents = []
        for organism in sorted(organism_rows):
            eligible = [
                row.absolute_percent_deviation
                for row in organism_rows[organism]
                if row.absolute_percent_deviation is not None
            ]
            signed_eligible = [
                row.signed_percent_deviation
                for row in organism_rows[organism]
                if row.signed_percent_deviation is not None
            ]
            if eligible:
                organism_percents.append(finite_descriptive_mean(eligible))
                organism_signed_percents.append(finite_descriptive_mean(signed_eligible))
        percent_contributing_organisms += len(organism_percents)
        unit_summaries.append(
            PairedCountUnitSummary(
                experimental_unit_id=unit_id,
                paired_observation_count=len(rows),
                organism_count=len(unit_organisms[unit_id]),
                observation_counts_by_organism=counts_by_organism,
                repeated_pair_count_beyond_first_per_organism=(len(rows) - len(counts_by_organism)),
                unequal_pair_counts_within_unit=len(set(counts_by_organism.values())) > 1,
                mean_signed_bias=finite_descriptive_mean(row.signed_difference for row in rows),
                mean_absolute_error=finite_descriptive_mean(
                    row.absolute_difference for row in rows
                ),
                organism_balanced_mean_signed_bias=finite_descriptive_mean(organism_biases),
                organism_balanced_mean_absolute_error=finite_descriptive_mean(organism_errors),
                nonzero_reference_count=len(valid_unit_percent),
                percent_contributing_organism_count=len(organism_percents),
                mean_absolute_percent_deviation=(
                    finite_descriptive_mean(valid_unit_percent) if valid_unit_percent else None
                ),
                organism_balanced_mean_absolute_percent_deviation=(
                    finite_descriptive_mean(organism_percents) if organism_percents else None
                ),
                mean_signed_percent_deviation=(
                    finite_descriptive_mean(
                        row.signed_percent_deviation
                        for row in rows
                        if row.signed_percent_deviation is not None
                    )
                    if valid_unit_percent
                    else None
                ),
                organism_balanced_mean_signed_percent_deviation=(
                    finite_descriptive_mean(organism_signed_percents)
                    if organism_signed_percents
                    else None
                ),
            )
        )
    # Pair-weighted statistics remain available for backwards compatibility.
    # Balanced statistics remain descriptive; caller-declared units are unverified.
    unit_balanced_bias = (
        finite_descriptive_mean(row.mean_signed_bias for row in unit_summaries)
        if unit_summaries
        else None
    )
    unit_balanced_error = (
        finite_descriptive_mean(row.mean_absolute_error for row in unit_summaries)
        if unit_summaries
        else None
    )
    organism_and_unit_bias = (
        finite_descriptive_mean(row.organism_balanced_mean_signed_bias for row in unit_summaries)
        if unit_summaries
        else None
    )
    organism_and_unit_error = (
        finite_descriptive_mean(row.organism_balanced_mean_absolute_error for row in unit_summaries)
        if unit_summaries
        else None
    )
    percent_eligible_units = [
        row for row in unit_summaries if row.mean_absolute_percent_deviation is not None
    ]
    unit_balanced_percent = (
        finite_descriptive_mean(
            row.mean_absolute_percent_deviation
            for row in percent_eligible_units
            if row.mean_absolute_percent_deviation is not None
        )
        if percent_eligible_units
        else None
    )
    organism_and_unit_percent = (
        finite_descriptive_mean(
            row.organism_balanced_mean_absolute_percent_deviation
            for row in percent_eligible_units
            if row.organism_balanced_mean_absolute_percent_deviation is not None
        )
        if percent_eligible_units
        else None
    )
    unit_balanced_signed_percent = (
        finite_descriptive_mean(
            row.mean_signed_percent_deviation
            for row in percent_eligible_units
            if row.mean_signed_percent_deviation is not None
        )
        if percent_eligible_units
        else None
    )
    organism_and_unit_signed_percent = (
        finite_descriptive_mean(
            row.organism_balanced_mean_signed_percent_deviation
            for row in percent_eligible_units
            if row.organism_balanced_mean_signed_percent_deviation is not None
        )
        if percent_eligible_units
        else None
    )
    return PairedCountComparisonResponse(
        reference_kind=request.reference_kind,
        analysis_provenance=scientific_input_provenance(
            algorithm_version="ecology-paired-count-0005",
            records=request.pairs,
            parameters={
                "reference_kind": request.reference_kind,
                "experimental_unit_type": unit_type,
            },
            source_record_ids=(*reference_sources, *model_sources),
        ),
        metric_name=next(iter(metrics)),
        paired_observation_count=len(differences),
        observed_organism_count=len(pair_counts_by_organism),
        observation_counts_by_organism=dict(sorted(pair_counts_by_organism.items())),
        repeated_pair_count_beyond_first_per_organism=(
            len(differences) - len(pair_counts_by_organism)
        ),
        unequal_pair_counts_across_organisms=(len(set(pair_counts_by_organism.values())) > 1),
        nonzero_reference_count=len(valid_percent),
        zero_reference_count=len(differences) - len(valid_percent),
        mean_signed_bias=finite_descriptive_mean(row.signed_difference for row in differences),
        mean_absolute_error=finite_descriptive_mean(row.absolute_difference for row in differences),
        mean_absolute_percent_deviation=(
            finite_descriptive_mean(valid_percent) if valid_percent else None
        ),
        mean_signed_percent_deviation=(
            finite_descriptive_mean(valid_signed_percent) if valid_signed_percent else None
        ),
        paired_differences=differences,
        experimental_unit_type=unit_type,
        declared_independent_unit_count=len(by_unit) if unit_type is not None else None,
        cross_unit_shared_parent_colony_ids=cross_unit_shared_parent_colony_ids(pairs),
        unit_summaries=unit_summaries,
        unit_balanced_mean_signed_bias=unit_balanced_bias,
        unit_balanced_mean_absolute_error=unit_balanced_error,
        organism_and_unit_balanced_mean_signed_bias=organism_and_unit_bias,
        organism_and_unit_balanced_mean_absolute_error=organism_and_unit_error,
        unit_balanced_mean_absolute_percent_deviation=unit_balanced_percent,
        organism_and_unit_balanced_mean_absolute_percent_deviation=organism_and_unit_percent,
        unit_balanced_mean_signed_percent_deviation=unit_balanced_signed_percent,
        organism_and_unit_balanced_mean_signed_percent_deviation=(
            organism_and_unit_signed_percent
        ),
        percent_contributing_independent_unit_count=(
            len(percent_eligible_units) if unit_type is not None else None
        ),
        percent_contributing_organism_count=(
            percent_contributing_organisms if unit_type is not None else None
        ),
        limitations=[
            "Both human reference and model predictions are caller-supplied and unverified.",
            "Paired image, organism and source identities are not authenticated.",
            "Percent deviation excludes zero-reference pairs; its denominator is reported.",
            "Signed percent is 100 * (model - human) / human: positive means overcount.",
            "Unit-balanced percent excludes units without nonzero human references.",
            "Nested percent excludes organisms without nonzero human references.",
            "Signed bias is model minus human reference; no ICC, limits of agreement or p-values.",
            "Images and fragments are not independent replicates; unit means are descriptive.",
            "Repeated pairs per organism are disclosed, not counted as biological replicates.",
            "Unequal image counts can change pair-weighted versus nested unit means.",
            "Pair means weight observations; unit means weight declared units equally.",
            "Nested means average images per organism, organisms per unit, then units.",
            "Sampling dates and technical-replicate identity are not verified.",
            "Experimental-unit identities are not validated against a registered study design.",
            "Parent-colony labels are caller-declared and require independent verification.",
        ],
    )
