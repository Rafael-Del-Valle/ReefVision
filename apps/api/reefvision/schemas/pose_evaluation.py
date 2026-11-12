"""Typed contracts for scientific pose evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

from reefvision.schemas.jobs import JobResponse


class PoseEvaluationCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    evaluation_dataset_id: str = Field(min_length=1, max_length=36)
    device: str = Field(default="auto", min_length=1, max_length=60)
    pck_thresholds: list[FiniteFloat] = Field(default=[0.05, 0.1, 0.2], min_length=1)
    calibration_threshold: FiniteFloat = Field(default=0.1, ge=0, le=1)
    calibration_bins: int = Field(default=10, ge=1, le=1000)
    confidence_thresholds: list[FiniteFloat] = Field(
        default=[0.0, 0.25, 0.5, 0.75, 0.9], min_length=1
    )
    oks_sigmas: dict[str, FiniteFloat] | None = None

    @field_validator("pck_thresholds", "confidence_thresholds")
    @classmethod
    def validate_thresholds(cls, values: list[float]) -> list[float]:
        normalized = [float(value) for value in values]
        if any(value < 0 or value > 1 for value in normalized):
            raise ValueError("Thresholds must be within [0, 1]")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Thresholds must not contain duplicates")
        return normalized

    @field_validator("oks_sigmas")
    @classmethod
    def validate_sigmas(cls, values: dict[str, float] | None) -> dict[str, float] | None:
        if values is not None and any(not key or value <= 0 for key, value in values.items()):
            raise ValueError("OKS sigmas require landmark IDs and positive values")
        return values


class PoseEvaluationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    model_id: str
    evaluation_dataset_id: str
    schema_version: str
    status: str
    configuration_json: dict[str, Any]
    metrics_json: dict[str, Any]
    predictions_json: list[dict[str, Any]]
    provenance_json: dict[str, Any]
    warnings_json: list[str]
    result_sha256: str
    inference_latency_ms: float
    images_per_second: float
    created_at: datetime


class PoseEvaluationComparisonCreateRequest(BaseModel):
    model_ids: list[str] = Field(min_length=1, max_length=12)
    evaluation_dataset_id: str = Field(min_length=1, max_length=36)
    device: str = Field(default="auto", min_length=1, max_length=60)
    pck_thresholds: list[FiniteFloat] = Field(default=[0.05, 0.1, 0.2], min_length=1, max_length=20)
    calibration_threshold: FiniteFloat = Field(default=0.1, ge=0, le=1)
    calibration_bins: int = Field(default=10, ge=1, le=1000)
    confidence_thresholds: list[FiniteFloat] = Field(
        default=[0.0, 0.25, 0.5, 0.75, 0.9], min_length=1, max_length=20
    )
    oks_sigmas: dict[str, FiniteFloat] | None = None

    @field_validator("model_ids")
    @classmethod
    def validate_model_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 36 for value in normalized):
            raise ValueError("Model IDs must be non-empty UUID-sized identifiers")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Comparison model IDs must be unique")
        return normalized

    @field_validator("pck_thresholds", "confidence_thresholds")
    @classmethod
    def validate_thresholds(cls, values: list[float]) -> list[float]:
        normalized = [float(value) for value in values]
        if any(value < 0 or value > 1 for value in normalized):
            raise ValueError("Thresholds must be within [0, 1]")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Thresholds must not contain duplicates")
        return normalized

    @field_validator("oks_sigmas")
    @classmethod
    def validate_sigmas(cls, values: dict[str, float] | None) -> dict[str, float] | None:
        if values is not None and any(not key or value <= 0 for key, value in values.items()):
            raise ValueError("OKS sigmas require landmark IDs and positive values")
        return values


class PoseEvaluationComparisonListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int
