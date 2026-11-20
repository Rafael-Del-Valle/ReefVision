"""Pair frozen, reviewed ecological growth at two preregistered UTC visits."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, date
from importlib import import_module
from math import isfinite, sqrt
from statistics import mean, stdev
from uuid import UUID

from sqlalchemy.orm import Session

from reefvision.domain.ecology_lineage_policy import classify_ecological_unit_level
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.ecology_analysis import (
    EcologyAnalysisSnapshot,
    GrowthObservation,
    GrowthResult,
    GrowthSelection,
)
from reefvision.schemas.paired_growth_contrast import (
    PairedGrowthContrastReport,
    PairedGrowthContrastRequest,
    PairedGrowthDesign,
    PairedGrowthOrganism,
    PairedGrowthReportBody,
    PairedGrowthRosterIdentity,
    PairedGrowthStatistics,
    PairedGrowthUnit,
)
from reefvision.services.ecology_analysis import EcologyAnalysisService
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.storage.datasets import canonical_json_sha256

METHOD_REFERENCE = "https://www.itl.nist.gov/div898/handbook/prc/section3/prc311.htm"
ASSUMPTIONS = [
    "Follow-up minus baseline on the same organism and compatible calibrated measurement method.",
    "Average within each declared parent colony, then average colonies or unparented organisms "
    "within each unit. Every complete declared unit has equal weight.",
    "The complete-unit estimate applies to units measured at both selected visits. Its "
    "interpretation can be sensitive to missing data.",
    "The paired t interval assumes independent declared units and approximately normally "
    "distributed unit differences. The app does not establish those assumptions.",
    "This is a two-visit contrast of projected geometry. The interval describes between-unit "
    "variation and does not include calibration uncertainty or estimate a causal treatment effect.",
]


def _paired_statistics(
    differences: list[float], *, calculate_t_interval: bool
) -> PairedGrowthStatistics:
    count = len(differences)
    average = mean(differences) if count else None
    result = PairedGrowthStatistics(
        mean_difference=average,
        standard_error=None,
        degrees_of_freedom=None,
        confidence_interval_95=None,
        interval_status="insufficient_complete_units",
    )
    if count < 2 or average is None:
        return result
    result.degrees_of_freedom = count - 1
    try:
        error = stdev(differences) / sqrt(count)
    except OverflowError:
        error = float("inf")
    if not isfinite(error):
        result.interval_status = "precision_unavailable"
        return result
    if error == 0:
        if any(value != differences[0] for value in differences):
            result.interval_status = "precision_unavailable"
        else:
            result.standard_error = 0.0
            result.interval_status = "zero_between_unit_variation"
        return result
    result.standard_error = error
    if not calculate_t_interval:
        result.interval_status = "statistics_runtime_unavailable"
        return result
    try:
        student_t = import_module("scipy.stats").t
    except ImportError:
        result.interval_status = "statistics_runtime_unavailable"
        return result
    half_width = float(student_t.ppf(0.975, count - 1)) * error
    lower, upper = average - half_width, average + half_width
    if not (isfinite(lower) and isfinite(upper) and lower < average < upper):
        result.interval_status = "precision_unavailable"
        return result
    result.confidence_interval_95 = (lower, upper)
    result.interval_status = "available"
    return result


def _organism_pair(
    identity: PairedGrowthRosterIdentity,
    baseline: list[GrowthObservation],
    followup: list[GrowthObservation],
) -> PairedGrowthOrganism:
    first = baseline[0] if len(baseline) == 1 else None
    last = followup[0] if len(followup) == 1 else None
    reason = None
    if len(baseline) > 1 or len(followup) > 1:
        reason = "duplicate_utc_sampling_date"
    elif first is None and last is None:
        reason = "missing_both_visits"
    elif first is None:
        reason = "missing_baseline"
    elif last is None:
        reason = "missing_followup"
    elif first.unit != last.unit:
        reason = "incomparable_units"
    elif first.measurement_method != last.measurement_method:
        reason = "incomparable_calibration_methods"

    difference = None
    if reason is None and first is not None and last is not None:
        difference = last.value - first.value
    return PairedGrowthOrganism(
        organism_id=identity.organism_key,
        identity_revision=identity.revision,
        parent_colony_id=identity.parent_colony_key,
        baseline_source_record_id=first.calibration_evidence_id if first else None,
        followup_source_record_id=last.calibration_evidence_id if last else None,
        baseline_candidate_ids=sorted(row.calibration_evidence_id for row in baseline),
        followup_candidate_ids=sorted(row.calibration_evidence_id for row in followup),
        baseline_value=first.value if first else None,
        followup_value=last.value if last else None,
        unit=first.unit if difference is not None and first else None,
        measurement_method=first.measurement_method if difference is not None and first else None,
        difference=difference,
        reason=reason,
    )


def _unit_pair(unit_id: str, pairs: list[PairedGrowthOrganism]) -> PairedGrowthUnit:
    reason = (
        "incomplete_unit"
        if any(pair.reason is not None for pair in pairs)
        else "incompatible_unit_measurements"
        if len({(pair.unit, pair.measurement_method) for pair in pairs}) != 1
        else None
    )
    difference = None
    if reason is None:
        nested: dict[str, list[float]] = defaultdict(list)
        for pair in pairs:
            if pair.difference is not None:
                nested[pair.parent_colony_id or pair.organism_id].append(pair.difference)
        difference = mean(mean(values) for values in nested.values())
    return PairedGrowthUnit(
        experimental_unit_id=unit_id,
        status="included" if reason is None else "excluded",
        reason=reason,
        difference=difference,
        organisms=pairs,
    )


def paired_growth_contrast(
    session: Session,
    project_id: str,
    analysis_id: str,
    request: PairedGrowthContrastRequest,
) -> PairedGrowthContrastReport:
    analysis = EcologyAnalysisService(session).get(project_id, analysis_id)
    if analysis.content_sha256 != request.source_sha256:
        raise ConflictError("Reviewed growth source digest differs from the selected digest")
    if analysis.stale:
        raise ConflictError(
            "Selected growth evidence has changed; save a freshly reviewed analysis"
        )
    latest = EcologyIdentityService(session)._latest(project_id)
    roster = (
        {
            key: PairedGrowthRosterIdentity.model_validate(latest[key])
            for key in analysis.snapshot.result.sampling_identity_revisions
            if key in latest
        }
        if isinstance(analysis.snapshot.result, GrowthResult)
        else {}
    )
    return build_paired_growth_report(
        analysis.project_id, analysis.id, analysis.snapshot, request, roster
    )


def build_paired_growth_report(
    project_id: UUID,
    analysis_id: UUID,
    snapshot: EcologyAnalysisSnapshot,
    request: PairedGrowthContrastRequest,
    identities: Mapping[str, PairedGrowthRosterIdentity],
    *,
    calculate_t_interval: bool = True,
) -> PairedGrowthContrastReport:
    """Replay the calculation from frozen input evidence, including imported history."""

    selection = snapshot.selection
    result = snapshot.result
    if not isinstance(selection, GrowthSelection) or not selection.sampling_plan:
        raise ValidationError(
            "Paired growth requires a reviewed growth analysis with a sampling plan"
        )
    if not isinstance(result, GrowthResult):
        raise ValidationError("The reviewed result does not contain growth observations")

    dates = {request.baseline_date, request.followup_date}
    if any(not dates.issubset(unit.dates) for unit in selection.sampling_plan):
        raise ValidationError("Both UTC visit dates must be planned for every frozen cohort unit")
    lineage_units: dict[str, str] = {}
    roster = {}
    for unit in selection.sampling_plan:
        for key in unit.organism_keys:
            identity = identities.get(key)
            if identity is None or identity.revision != result.sampling_identity_revisions.get(key):
                raise ConflictError("The reviewed growth roster identity revision changed")
            declared_type = identity.experimental_unit_type
            if (
                identity.experimental_unit_id != unit.experimental_unit_id
                or declared_type is None
                or declared_type.casefold() != request.experimental_unit_type.casefold()
            ):
                raise ValidationError(
                    "The declared experimental unit type must match the frozen roster"
                )
            if (
                classify_ecological_unit_level(declared_type) == "organism"
                and len(unit.organism_keys) != 1
            ):
                raise ValidationError("An organism-level unit cannot contain multiple organisms")
            # A colony and its fragments use the same lineage key, even when the
            # colony is enrolled directly and therefore has no parent of its own.
            lineage = identity.parent_colony_key or identity.organism_key
            if (
                lineage_units.setdefault(lineage, unit.experimental_unit_id)
                != unit.experimental_unit_id
            ):
                raise ValidationError(
                    "A colony lineage spans multiple declared independent units. "
                    "Review the frozen roster before running the paired contrast."
                )
            roster[key] = identity

    observations: dict[tuple[str, date], list[GrowthObservation]] = defaultdict(list)
    for observation in result.observations:
        visit = observation.observed_at.astimezone(UTC).date()
        if visit in dates:
            observations[(observation.organism_key, visit)].append(observation)
    units = [
        _unit_pair(
            unit.experimental_unit_id,
            [
                _organism_pair(
                    roster[key],
                    observations[(key, request.baseline_date)],
                    observations[(key, request.followup_date)],
                )
                for key in sorted(unit.organism_keys)
            ],
        )
        for unit in sorted(selection.sampling_plan, key=lambda item: item.experimental_unit_id)
    ]
    included = [unit for unit in units if unit.difference is not None]
    measurement = {
        (pair.unit, pair.measurement_method) for unit in included for pair in unit.organisms
    }
    if len(measurement) > 1:
        raise ValidationError(
            "Complete units must use the same physical unit and calibration method"
        )
    physical_unit, method = next(iter(measurement), (None, None))
    values = [unit.difference for unit in included if unit.difference is not None]
    statistics = _paired_statistics(values, calculate_t_interval=calculate_t_interval)
    body = PairedGrowthReportBody(
        **statistics.model_dump(),
        analysis_id=analysis_id,
        project_id=project_id,
        source_sha256=request.source_sha256,
        source_method_version=snapshot.method_version,
        source_reviewed_by=snapshot.reviewed_by,
        selected_source_record_ids=sorted(row.calibration_evidence_id for row in selection.sources),
        source_exclusions=result.exclusions,
        design=PairedGrowthDesign.model_validate(
            request.model_dump(mode="json", exclude={"source_sha256"})
        ),
        method_reference=METHOD_REFERENCE,
        assumptions=ASSUMPTIONS,
        metric=selection.metric,
        unit=physical_unit,
        measurement_method=method,
        units=units,
        planned_unit_count=len(units),
        included_unit_count=len(included),
    ).model_dump(mode="json")
    return PairedGrowthContrastReport.model_validate(
        {
            **body,
            "report_sha256": canonical_json_sha256(body),
        }
    )
