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

    @model_validator(mode="after")
    def require_unique_metrics(self) -> MaskMeasurementReference:
        metrics = [value.metric for value in self.values]
        if len(set(metrics)) != len(metrics):
            raise ValueError("Each reference metric may appear only once per mask")
        return self


class ProjectMeasurementValidationRequest(BaseModel):
    references: list[MaskMeasurementReference] = Field(min_length=1)
    default_tolerance_percent: float = Field(default=10.0, ge=0, le=1000)

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


class MeasurementValidationMetricSummary(BaseModel):
    metric: MeasurementMetric
    unit: str | None
    observation_count: int = Field(ge=0)
    mean_measured: float
    mean_reference: float
    mean_bias: float
    mean_absolute_error: float
    root_mean_square_error: float
    mean_absolute_percentage_error: float | None
    maximum_absolute_error: float
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


class ProjectMeasurementValidationResponse(BaseModel):
    project_id: str
    mask_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    summaries: list[MeasurementValidationMetricSummary]
    observations: list[MeasurementValidationObservation]
    warnings: list[str]
