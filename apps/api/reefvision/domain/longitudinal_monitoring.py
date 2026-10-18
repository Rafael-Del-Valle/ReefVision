"""Conservative first/final repeated-organism comparisons (ReefVision 1.2)."""

from __future__ import annotations

import math
from collections import defaultdict

from reefvision.domain.errors import ValidationError
from reefvision.schemas.longitudinal_monitoring import (
    LongitudinalAnalysisRequest,
    LongitudinalAnalysisResponse,
    LongitudinalChange,
    MonitoringObservation,
)


def analyze_longitudinal(
    request: LongitudinalAnalysisRequest,
) -> LongitudinalAnalysisResponse:
    """Compare endpoints without treating images or fragments as independent replicates.

    This is an exploratory calculator for caller-supplied measurements, NOT a read of
    verified ReefVision annotations. It does not estimate survival or significance.
    """
    grouped: dict[tuple[str, str], list[MonitoringObservation]] = defaultdict(list)
    used_sources: set[str] = set()
    for obs in request.observations:
        if obs.source_record_id in used_sources:
            raise ValidationError("Each source_record_id must identify one unique observation")
        used_sources.add(obs.source_record_id)
        grouped[(obs.organism_id, obs.metric_name)].append(obs)

    changes: list[LongitudinalChange] = []
    incomplete = 0
    for (organism_id, metric_name), observations in sorted(grouped.items()):
        units = {obs.unit for obs in observations}
        if len(units) != 1:
            raise ValidationError(
                f"Repeated measurements for {organism_id!r}/{metric_name!r} "
                "mix units; normalize explicitly before comparison"
            )
        ordered = sorted(observations, key=lambda item: item.observed_at)
        if len({item.observed_at for item in ordered}) != len(ordered):
            raise ValidationError(
                f"Ambiguous simultaneous measurements for {organism_id!r}/{metric_name!r}"
            )
        if len(ordered) < 2:
            incomplete += 1
            continue
        first, last = ordered[0], ordered[-1]
        elapsed_days = (last.observed_at - first.observed_at).total_seconds() / 86400.0
        if elapsed_days <= 0:
            raise ValidationError("Repeated measurements must span positive elapsed time")
        difference = last.value - first.value
        percent = difference / first.value * 100 if first.value > 0 else None
        rate = difference / elapsed_days
        if any(not math.isfinite(value) for value in (difference, rate)):
            raise ValidationError("Computed change is not finite")
        if percent is not None and not math.isfinite(percent):
            raise ValidationError("Computed percentage change is not finite")
        changes.append(
            LongitudinalChange(
                organism_id=organism_id,
                metric_name=metric_name,
                unit=first.unit,
                first_observed_at=first.observed_at,
                last_observed_at=last.observed_at,
                baseline_source_record_id=first.source_record_id,
                final_source_record_id=last.source_record_id,
                initial_value=first.value,
                final_value=last.value,
                absolute_change=difference,
                percent_change=percent,
                elapsed_days=elapsed_days,
                change_per_day=rate,
                observation_count=len(ordered),
            )
        )
    return LongitudinalAnalysisResponse(
        observation_count=len(request.observations),
        evaluated_series_count=len(changes),
        incomplete_series_count=incomplete,
        changes=changes,
        limitations=[
            "Caller-supplied observations are not verified against project data or calibration.",
            "Changes compare the first and last sampling dates; no statistical significance is inferred.",
            "Organisms are the reporting unit; observations are not pooled as independent replicates.",
        ],
    )
