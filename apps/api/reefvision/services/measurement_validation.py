"""Compare ReefVision coral measurements with manual reference values."""

from __future__ import annotations

from collections import defaultdict
from math import sqrt
from statistics import mean, stdev
from typing import Any

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, MaskAnnotation, Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.agreement_statistics import (
    bootstrap_paired,
    concordance_correlation,
    icc_two_way_absolute_single,
    pearson,
    spearman,
)
from reefvision.ml.agreement_statistics import (
    mean_absolute_error as bootstrap_mae_statistic,
)
from reefvision.ml.agreement_statistics import (
    mean_bias as bootstrap_bias_statistic,
)
from reefvision.schemas.measurement_validation import (
    MeasurementMetric,
    MeasurementValidationMetricSummary,
    MeasurementValidationObservation,
    MeasurementValidationSubgroupSummary,
    ProjectMeasurementValidationRequest,
    ProjectMeasurementValidationResponse,
)
from reefvision.services.mask_measurements import MaskMeasurementService


class MeasurementValidationService:
    """Calculate transparent accuracy statistics against user-supplied references."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.measurements = MaskMeasurementService(session, settings)

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _mask(self, project_id: str, mask_id: str) -> MaskAnnotation:
        mask = self.session.get(MaskAnnotation, mask_id)
        if mask is None or mask.deleted_at is not None:
            raise NotFoundError(f"Mask annotation not found: {mask_id}")
        image = self.session.get(ImageAsset, mask.image_id)
        if image is None or image.project_id != project_id:
            raise ValidationError("All validation masks must belong to the selected project")
        return mask

    @staticmethod
    def _measured_value(payload: Any, metric: MeasurementMetric) -> float | None:
        raw = getattr(payload, metric, None)
        if raw is None:
            return None
        return float(raw)

    @staticmethod
    def _expected_unit(payload: Any, metric: MeasurementMetric) -> str | None:
        if metric.endswith("_physical"):
            return payload.physical_unit
        if metric == "contained_box_count":
            return "count"
        return "pixels"

    @staticmethod
    def _subgroup_summaries(
        observations: list[MeasurementValidationObservation],
    ) -> list[MeasurementValidationSubgroupSummary]:
        grouped: dict[
            tuple[MeasurementMetric, str | None, str, str],
            list[MeasurementValidationObservation],
        ] = defaultdict(list)
        fields = (
            ("observer", "observer_id"),
            ("repeat", "repeat_id"),
            ("species", "species"),
            ("size_group", "size_group"),
            ("image_resolution_group", "image_resolution_group"),
            ("segmentation_method", "segmentation_method"),
        )
        for observation in observations:
            for group_type, field_name in fields:
                value = getattr(observation, field_name)
                if value:
                    grouped[(observation.metric, observation.unit, group_type, value)].append(
                        observation
                    )
        output: list[MeasurementValidationSubgroupSummary] = []
        for (metric, unit, group_type, group_value), rows in sorted(
            grouped.items(),
            key=lambda item: (item[0][0], item[0][2], item[0][3]),
        ):
            output.append(
                MeasurementValidationSubgroupSummary(
                    metric=metric,
                    unit=unit,
                    group_type=group_type,
                    group_value=group_value,
                    observation_count=len(rows),
                    mean_bias=mean(row.signed_error for row in rows),
                    mean_absolute_error=mean(row.absolute_error for row in rows),
                    root_mean_square_error=sqrt(mean(row.signed_error**2 for row in rows)),
                    passed_count=sum(row.passed for row in rows),
                    failed_count=sum(not row.passed for row in rows),
                )
            )
        return output

    def validate(
        self,
        project_id: str,
        request: ProjectMeasurementValidationRequest,
    ) -> ProjectMeasurementValidationResponse:
        self._project(project_id)
        observations: list[MeasurementValidationObservation] = []
        warnings: list[str] = []

        for reference in request.references:
            mask = self._mask(project_id, reference.mask_annotation_id)
            measured = self.measurements.measure(mask.id)
            for value in reference.values:
                measured_value = self._measured_value(measured, value.metric)
                if measured_value is None:
                    warnings.append(
                        f"{mask.id}: {value.metric} is unavailable; check calibration or "
                        "the selected surface-area model"
                    )
                    continue
                expected_unit = self._expected_unit(measured, value.metric)
                supplied_unit = (
                    value.unit.strip() if value.unit is not None and value.unit.strip() else None
                )
                if (
                    supplied_unit
                    and expected_unit
                    and supplied_unit.casefold() != expected_unit.casefold()
                ):
                    warnings.append(
                        f"{mask.id}: reference unit {supplied_unit!r} does not match "
                        f"ReefVision unit {expected_unit!r} for {value.metric}"
                    )
                    continue
                signed_error = measured_value - value.reference_value
                absolute_error = abs(signed_error)
                percent_error = (
                    absolute_error / abs(value.reference_value) * 100.0
                    if value.reference_value != 0
                    else 0.0
                    if absolute_error == 0
                    else None
                )
                tolerance = (
                    value.tolerance_percent
                    if value.tolerance_percent is not None
                    else request.default_tolerance_percent
                )
                observations.append(
                    MeasurementValidationObservation(
                        mask_annotation_id=mask.id,
                        image_id=mask.image_id,
                        metric=value.metric,
                        measured_value=measured_value,
                        reference_value=value.reference_value,
                        unit=expected_unit,
                        signed_error=signed_error,
                        absolute_error=absolute_error,
                        percent_error=percent_error,
                        tolerance_percent=tolerance,
                        passed=percent_error is not None and percent_error <= tolerance,
                        observer_id=reference.observer_id,
                        repeat_id=reference.repeat_id,
                        species=reference.species,
                        size_group=reference.size_group,
                        image_resolution_group=reference.image_resolution_group,
                        segmentation_method=reference.segmentation_method,
                    )
                )

        grouped: dict[
            tuple[MeasurementMetric, str | None],
            list[MeasurementValidationObservation],
        ] = defaultdict(list)
        for observation in observations:
            grouped[(observation.metric, observation.unit)].append(observation)

        summaries: list[MeasurementValidationMetricSummary] = []
        for summary_index, ((metric, unit), rows) in enumerate(
            sorted(grouped.items(), key=lambda item: item[0][0])
        ):
            percent_errors = [row.percent_error for row in rows if row.percent_error is not None]
            bias = mean(row.signed_error for row in rows)
            bias_standard_deviation = (
                stdev(row.signed_error for row in rows) if len(rows) >= 2 else None
            )
            confidence_half_width = (
                1.96 * bias_standard_deviation / sqrt(len(rows))
                if bias_standard_deviation is not None
                else None
            )
            agreement_half_width = (
                1.96 * bias_standard_deviation if bias_standard_deviation is not None else None
            )
            measured_values = [row.measured_value for row in rows]
            reference_values = [row.reference_value for row in rows]
            bootstrap_seed = request.random_seed + summary_index * 104729
            bias_interval = (
                bootstrap_paired(
                    measured_values,
                    reference_values,
                    bootstrap_bias_statistic,
                    iterations=request.bootstrap_iterations,
                    confidence=request.confidence_level,
                    seed=bootstrap_seed,
                )
                if request.bootstrap_iterations
                else None
            )
            mae_interval = (
                bootstrap_paired(
                    measured_values,
                    reference_values,
                    bootstrap_mae_statistic,
                    iterations=request.bootstrap_iterations,
                    confidence=request.confidence_level,
                    seed=bootstrap_seed + 1,
                )
                if request.bootstrap_iterations
                else None
            )
            concordance_interval = (
                bootstrap_paired(
                    measured_values,
                    reference_values,
                    concordance_correlation,
                    iterations=request.bootstrap_iterations,
                    confidence=request.confidence_level,
                    seed=bootstrap_seed + 2,
                )
                if request.bootstrap_iterations
                else None
            )
            summaries.append(
                MeasurementValidationMetricSummary(
                    metric=metric,
                    unit=unit,
                    observation_count=len(rows),
                    mean_measured=mean(measured_values),
                    mean_reference=mean(reference_values),
                    mean_bias=bias,
                    standard_deviation_bias=bias_standard_deviation,
                    bias_confidence_interval_lower=(
                        bias - confidence_half_width if confidence_half_width is not None else None
                    ),
                    bias_confidence_interval_upper=(
                        bias + confidence_half_width if confidence_half_width is not None else None
                    ),
                    lower_limit_of_agreement=(
                        bias - agreement_half_width if agreement_half_width is not None else None
                    ),
                    upper_limit_of_agreement=(
                        bias + agreement_half_width if agreement_half_width is not None else None
                    ),
                    pearson_correlation=pearson(measured_values, reference_values),
                    spearman_correlation=spearman(measured_values, reference_values),
                    concordance_correlation_coefficient=concordance_correlation(
                        measured_values,
                        reference_values,
                    ),
                    intraclass_correlation_coefficient=icc_two_way_absolute_single(
                        measured_values,
                        reference_values,
                    ),
                    mean_absolute_error=mean(row.absolute_error for row in rows),
                    root_mean_square_error=sqrt(mean(row.signed_error**2 for row in rows)),
                    mean_absolute_percentage_error=(
                        mean(percent_errors) if percent_errors else None
                    ),
                    maximum_absolute_error=max(row.absolute_error for row in rows),
                    bootstrap_bias_lower=(
                        bias_interval.lower if bias_interval is not None else None
                    ),
                    bootstrap_bias_upper=(
                        bias_interval.upper if bias_interval is not None else None
                    ),
                    bootstrap_mae_lower=(mae_interval.lower if mae_interval is not None else None),
                    bootstrap_mae_upper=(mae_interval.upper if mae_interval is not None else None),
                    bootstrap_concordance_lower=(
                        concordance_interval.lower if concordance_interval is not None else None
                    ),
                    bootstrap_concordance_upper=(
                        concordance_interval.upper if concordance_interval is not None else None
                    ),
                    passed_count=sum(row.passed for row in rows),
                    failed_count=sum(not row.passed for row in rows),
                )
            )

        return ProjectMeasurementValidationResponse(
            project_id=project_id,
            mask_count=len({row.mask_annotation_id for row in observations}),
            observation_count=len(observations),
            passed_count=sum(row.passed for row in observations),
            failed_count=sum(not row.passed for row in observations),
            summaries=summaries,
            subgroup_summaries=self._subgroup_summaries(observations),
            observations=observations,
            warnings=list(dict.fromkeys(warnings)),
        )
