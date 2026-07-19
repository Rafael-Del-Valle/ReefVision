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
from reefvision.schemas.measurement_validation import (
    MeasurementMetric,
    MeasurementValidationMetricSummary,
    MeasurementValidationObservation,
    ProjectMeasurementValidationRequest,
    ProjectMeasurementValidationResponse,
)
from reefvision.services.mask_measurements import MaskMeasurementService


def _pearson_correlation(
    measured_values: list[float],
    reference_values: list[float],
) -> float | None:
    if len(measured_values) < 2 or len(measured_values) != len(reference_values):
        return None
    measured_mean = mean(measured_values)
    reference_mean = mean(reference_values)
    measured_variance = sum((value - measured_mean) ** 2 for value in measured_values)
    reference_variance = sum((value - reference_mean) ** 2 for value in reference_values)
    if measured_variance <= 0 or reference_variance <= 0:
        return None
    covariance = sum(
        (measured - measured_mean) * (reference - reference_mean)
        for measured, reference in zip(
            measured_values,
            reference_values,
            strict=True,
        )
    )
    correlation = covariance / sqrt(measured_variance * reference_variance)
    return max(-1.0, min(1.0, correlation))


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
            raise ValidationError(
                "All validation masks must belong to the selected project"
            )
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
                    value.unit.strip()
                    if value.unit is not None and value.unit.strip()
                    else None
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
                    )
                )

        grouped: dict[
            tuple[MeasurementMetric, str | None],
            list[MeasurementValidationObservation],
        ] = defaultdict(list)
        for observation in observations:
            grouped[(observation.metric, observation.unit)].append(observation)

        summaries: list[MeasurementValidationMetricSummary] = []
        for (metric, unit), rows in sorted(
            grouped.items(),
            key=lambda item: item[0][0],
        ):
            percent_errors = [
                row.percent_error for row in rows if row.percent_error is not None
            ]
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
                1.96 * bias_standard_deviation
                if bias_standard_deviation is not None
                else None
            )
            measured_values = [row.measured_value for row in rows]
            reference_values = [row.reference_value for row in rows]
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
                        bias - confidence_half_width
                        if confidence_half_width is not None
                        else None
                    ),
                    bias_confidence_interval_upper=(
                        bias + confidence_half_width
                        if confidence_half_width is not None
                        else None
                    ),
                    lower_limit_of_agreement=(
                        bias - agreement_half_width
                        if agreement_half_width is not None
                        else None
                    ),
                    upper_limit_of_agreement=(
                        bias + agreement_half_width
                        if agreement_half_width is not None
                        else None
                    ),
                    pearson_correlation=_pearson_correlation(
                        measured_values,
                        reference_values,
                    ),
                    mean_absolute_error=mean(row.absolute_error for row in rows),
                    root_mean_square_error=sqrt(
                        mean(row.signed_error**2 for row in rows)
                    ),
                    mean_absolute_percentage_error=(
                        mean(percent_errors) if percent_errors else None
                    ),
                    maximum_absolute_error=max(row.absolute_error for row in rows),
                    passed_count=sum(1 for row in rows if row.passed),
                    failed_count=sum(1 for row in rows if not row.passed),
                )
            )

        return ProjectMeasurementValidationResponse(
            project_id=project_id,
            mask_count=len({row.mask_annotation_id for row in observations}),
            observation_count=len(observations),
            passed_count=sum(1 for row in observations if row.passed),
            failed_count=sum(1 for row in observations if not row.passed),
            summaries=summaries,
            observations=observations,
            warnings=list(dict.fromkeys(warnings)),
        )
