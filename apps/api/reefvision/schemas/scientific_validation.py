"""Frozen scientific measurement acceptance and reliability schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class ScientificReferenceObservation(BaseModel):
    specimen_id: str = Field(min_length=1, max_length=200)
    metric: str = Field(min_length=1, max_length=120)
    reference_value: float
    unit: str = Field(min_length=1, max_length=80)
    mask_annotation_id: str | None = Field(default=None, max_length=36)
    predicted_value: float | None = None
    observer_id: str = Field(default="reference", min_length=1, max_length=120)
    session_id: str = Field(default="session-1", min_length=1, max_length=120)
    replicate_id: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScientificMetricThreshold(BaseModel):
    maximum_mae: float | None = Field(default=None, ge=0)
    maximum_rmse: float | None = Field(default=None, ge=0)
    maximum_absolute_bias: float | None = Field(default=None, ge=0)
    maximum_relative_mae_percent: float | None = Field(default=None, ge=0)
    minimum_pearson_r: float | None = Field(default=None, ge=-1, le=1)
    minimum_icc: float | None = Field(default=None, ge=-1, le=1)
    minimum_sample_count: int = Field(default=3, ge=1, le=1_000_000)


class ScientificValidationRequest(BaseModel):
    dataset_name: str = Field(min_length=1, max_length=300)
    dataset_version: str = Field(min_length=1, max_length=120)
    observations: list[ScientificReferenceObservation] = Field(
        min_length=1,
        max_length=1_000_000,
    )
    thresholds: dict[str, ScientificMetricThreshold]
    calibration_metadata: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=20_000)
    persist_report: bool = True

    @model_validator(mode="after")
    def require_thresholds_for_every_metric(self) -> ScientificValidationRequest:
        metrics = {item.metric for item in self.observations}
        missing = sorted(metrics - set(self.thresholds))
        if missing:
            raise ValueError("Every metric requires an acceptance threshold: " + ", ".join(missing))
        return self


class ScientificObservationResult(BaseModel):
    specimen_id: str
    metric: str
    unit: str
    observer_id: str
    session_id: str
    mask_annotation_id: str | None
    measurement_id: str | None
    measurement_revision: int | None
    reference_value: float
    predicted_value: float
    error: float
    absolute_error: float
    relative_error_percent: float | None


class ScientificMetricResult(BaseModel):
    metric: str
    unit: str
    sample_count: int
    mean_reference: float
    mean_predicted: float
    bias: float
    mae: float
    rmse: float
    relative_mae_percent: float | None
    pearson_r: float | None
    icc_absolute_agreement: float | None
    interobserver_icc: float | None
    intraobserver_icc_mean: float | None
    threshold: ScientificMetricThreshold
    passed: bool
    failures: list[str]
    warnings: list[str]


class ScientificValidationResponse(BaseModel):
    project_id: str
    report_id: str
    report_version: str
    dataset_name: str
    dataset_version: str
    frozen_dataset_checksum: str
    report_checksum: str
    created_at: str
    passed: bool
    metric_results: list[ScientificMetricResult]
    observations: list[ScientificObservationResult]
    warnings: list[str]
    blockers: list[str]
    artifact_id: str | None
    json_path: str | None
    csv_path: str | None
    html_path: str | None
