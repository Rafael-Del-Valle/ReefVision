"""Scientific reference-comparison schemas for coral measurements."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

MeasurementMetric = Literal[
    "area_pixels",
    "perimeter_pixels",
    "area_physical",
    "perimeter_physical",
    "total_linear_extension_pixels",
    "total_linear_extension_physical",
    "surface_area_physical",
    "contained_box_count",
]


class MeasurementReferenceValue(BaseModel):
    metric: MeasurementMetric
    reference_value: float = Field(ge=0)
    unit: str | None = Field(default=None, max_length=32)
    tolerance_percent: float | None = Field(default=None, ge=0, le=1000)


class MaskMeasurementReference(BaseModel):
    mask_annotation_id: str = Field(min_length=1, max_length=36)
    values: list[MeasurementReferenceValue] = Field(min_length=1)
    observer_id: str | None = Field(default=None, max_length=120)
    repeat_id: str | None = Field(default=None, max_length=120)
    species: str | None = Field(default=None, max_length=200)
    size_group: str | None = Field(default=None, max_length=120)
    image_resolution_group: str | None = Field(default=None, max_length=120)
    segmentation_method: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_unique_metrics(self) -> MaskMeasurementReference:
        metrics = [value.metric for value in self.values]
        if len(set(metrics)) != len(metrics):
            raise ValueError("Each reference metric may appear only once per mask")
        return self


class ProjectMeasurementValidationRequest(BaseModel):
    references: list[MaskMeasurementReference] = Field(min_length=1)
    default_tolerance_percent: float = Field(default=10.0, ge=0, le=1000)
    bootstrap_iterations: int = Field(default=2000, ge=0, le=100_000)
    confidence_level: float = Field(default=0.95, gt=0, lt=1)
    random_seed: int = 0

    @model_validator(mode="after")
    def require_unique_masks(self) -> ProjectMeasurementValidationRequest:
        mask_ids = [reference.mask_annotation_id for reference in self.references]
        if len(set(mask_ids)) != len(mask_ids):
            raise ValueError("Each mask annotation may appear only once")
        return self


class MeasurementValidationObservation(BaseModel):
    mask_annotation_id: str
    image_id: str
    metric: MeasurementMetric
    measured_value: float
    reference_value: float
    unit: str | None
    signed_error: float
    absolute_error: float
    percent_error: float | None
    tolerance_percent: float
    passed: bool
    observer_id: str | None = None
    repeat_id: str | None = None
    species: str | None = None
    size_group: str | None = None
    image_resolution_group: str | None = None
    segmentation_method: str | None = None


class MeasurementValidationMetricSummary(BaseModel):
    metric: MeasurementMetric
    unit: str | None
    observation_count: int = Field(ge=0)
    mean_measured: float
    mean_reference: float
    mean_bias: float
    standard_deviation_bias: float | None
    bias_confidence_interval_lower: float | None
    bias_confidence_interval_upper: float | None
    lower_limit_of_agreement: float | None
    upper_limit_of_agreement: float | None
    pearson_correlation: float | None = Field(default=None, ge=-1, le=1)
    spearman_correlation: float | None = Field(default=None, ge=-1, le=1)
    concordance_correlation_coefficient: float | None = Field(
        default=None,
        ge=-1,
        le=1,
    )
    intraclass_correlation_coefficient: float | None = Field(
        default=None,
        ge=-1,
        le=1,
    )
    mean_absolute_error: float
    root_mean_square_error: float
    mean_absolute_percentage_error: float | None
    maximum_absolute_error: float
    bootstrap_bias_lower: float | None = None
    bootstrap_bias_upper: float | None = None
    bootstrap_mae_lower: float | None = Field(default=None, ge=0)
    bootstrap_mae_upper: float | None = Field(default=None, ge=0)
    bootstrap_concordance_lower: float | None = Field(default=None, ge=-1, le=1)
    bootstrap_concordance_upper: float | None = Field(default=None, ge=-1, le=1)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


class MeasurementValidationSubgroupSummary(BaseModel):
    metric: MeasurementMetric
    unit: str | None
    group_type: Literal[
        "observer",
        "repeat",
        "species",
        "size_group",
        "image_resolution_group",
        "segmentation_method",
    ]
    group_value: str
    observation_count: int = Field(ge=1)
    mean_bias: float
    mean_absolute_error: float = Field(ge=0)
    root_mean_square_error: float = Field(ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


class ProjectMeasurementValidationResponse(BaseModel):
    project_id: str
    mask_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    summaries: list[MeasurementValidationMetricSummary]
    subgroup_summaries: list[MeasurementValidationSubgroupSummary] = Field(
        default_factory=list
    )
    observations: list[MeasurementValidationObservation]
    warnings: list[str]
