"""Descriptive human-model paired counts; never infer independent replication."""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import fmean

from reefvision.domain.errors import ValidationError
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

    unit_types = {
        item.experimental_unit_type for item in pairs if item.experimental_unit_type
    }
    if len(unit_types) > 1:
        raise ValidationError("Pairs declare conflicting experimental unit types")
    unit_type = request.experimental_unit_type or next(iter(unit_types), None)
    if unit_types and unit_type not in unit_types:
        raise ValidationError("Request and pairs disagree on experimental unit type")
    if unit_type is None and any(
        item.experimental_unit_id is not None for item in pairs
    ):
        raise ValidationError(
            "experimental_unit_type is required when unit IDs are supplied"
        )
    if unit_type is not None and any(
        item.experimental_unit_id is None for item in pairs
    ):
        raise ValidationError("All paired observations require experimental_unit_id")
    memberships: dict[str, str] = {}
    for item in pairs:
        if (
            item.experimental_unit_type is not None
            and item.experimental_unit_type != unit_type
        ):
            raise ValidationError("Pair experimental unit type conflicts with the request")
        if unit_type is not None:
            assert item.experimental_unit_id is not None
            existing = memberships.setdefault(item.organism_id, item.experimental_unit_id)
            if existing != item.experimental_unit_id:
                raise ValidationError("An organism cannot change experimental units")

    differences: list[PairedCountDifference] = []
    by_unit: dict[str, list[PairedCountDifference]] = defaultdict(list)
    unit_organisms: dict[str, set[str]] = defaultdict(set)
    for item in sorted(pairs, key=lambda pair: pair.observation_id):
        signed = item.model_count - item.reference_count
        absolute = abs(signed)
        percent = (
            absolute / item.reference_count * 100 if item.reference_count > 0 else None
        )
        if any(not math.isfinite(value) for value in (signed, absolute)):
            raise ValidationError("Paired count difference is not finite")
        if percent is not None and not math.isfinite(percent):
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
        )
        differences.append(row)
        if unit_type is not None:
            assert item.experimental_unit_id is not None
            by_unit[item.experimental_unit_id].append(row)
            unit_organisms[item.experimental_unit_id].add(item.organism_id)

    valid_percent = [
        row.absolute_percent_deviation
        for row in differences
        if row.absolute_percent_deviation is not None
    ]
    unit_summaries = [
        PairedCountUnitSummary(
            experimental_unit_id=unit_id,
            paired_observation_count=len(rows),
            organism_count=len(unit_organisms[unit_id]),
            mean_signed_bias=fmean(row.signed_difference for row in rows),
            mean_absolute_error=fmean(row.absolute_difference for row in rows),
        )
        for unit_id, rows in sorted(by_unit.items())
    ]
    return PairedCountComparisonResponse(
        reference_kind=request.reference_kind,
        metric_name=next(iter(metrics)),
        paired_observation_count=len(differences),
        nonzero_reference_count=len(valid_percent),
        zero_reference_count=len(differences) - len(valid_percent),
        mean_signed_bias=fmean(row.signed_difference for row in differences),
        mean_absolute_error=fmean(row.absolute_difference for row in differences),
        mean_absolute_percent_deviation=fmean(valid_percent) if valid_percent else None,
        paired_differences=differences,
        experimental_unit_type=unit_type,
        declared_independent_unit_count=len(by_unit) if unit_type is not None else None,
        unit_summaries=unit_summaries,
        limitations=[
            "Both human reference and model predictions are caller-supplied and unverified.",
            "Paired image, organism and source identities are not authenticated.",
            "Percent deviation excludes zero-reference pairs; its denominator is reported.",
            "Signed bias is model minus human reference; no ICC, limits of agreement or p-values.",
            "Images and fragments are not independent replicates; unit means are descriptive.",
            "Experimental-unit identities are not validated against a registered study design.",
        ],
    )
