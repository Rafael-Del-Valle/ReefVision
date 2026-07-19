"""Classification evaluation, curve, threshold, and calibration schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ClassificationReviewFilter = Literal["pending", "accepted", "rejected"]


class ClassificationEvaluationRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    image_ids: list[str] = Field(default_factory=list)
    review_statuses: list[ClassificationReviewFilter] = Field(default_factory=lambda: ["pending"])
    label_set: str | None = Field(default=None, max_length=100)
    confidence_threshold: float = Field(default=0, ge=0, le=1)
    calibration_bin_count: int = Field(default=10, ge=2, le=100)
    top_k_values: list[int] = Field(default_factory=lambda: [1, 3, 5], max_length=20)
    include_curves: bool = True

    @field_validator("top_k_values")
    @classmethod
    def validate_top_k(cls, values: list[int]) -> list[int]:
        if any(value < 1 or value > 1000 for value in values):
            raise ValueError("Top-k values must be between one and one thousand")
        return sorted(set(values))


class ClassificationConfusionCell(BaseModel):
    actual_label_class_id: str
    predicted_label_class_id: str
    count: int = Field(ge=0)


class ClassificationCurvePoint(BaseModel):
    threshold: float = Field(ge=0, le=1)
    true_positive_rate: float = Field(ge=0, le=1)
    false_positive_rate: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)


class ClassificationClassEvaluation(BaseModel):
    label_class_id: str
    support: int = Field(ge=0)
    predicted_count: int = Field(ge=0)
    true_positive_count: int = Field(ge=0)
    true_negative_count: int = Field(default=0, ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    sensitivity: float = Field(default=0, ge=0, le=1)
    specificity: float = Field(default=0, ge=0, le=1)
    negative_predictive_value: float = Field(default=0, ge=0, le=1)
    balanced_accuracy: float = Field(default=0, ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    roc_auc: float | None = Field(default=None, ge=0, le=1)
    precision_recall_auc: float | None = Field(default=None, ge=0, le=1)
    optimal_f1_threshold: float | None = Field(default=None, ge=0, le=1)
    optimal_f1: float | None = Field(default=None, ge=0, le=1)
    curve: list[ClassificationCurvePoint] = Field(default_factory=list)


class ClassificationCalibrationBin(BaseModel):
    lower_bound: float = Field(ge=0, le=1)
    upper_bound: float = Field(ge=0, le=1)
    sample_count: int = Field(ge=0)
    mean_confidence: float | None = Field(default=None, ge=0, le=1)
    accuracy: float | None = Field(default=None, ge=0, le=1)
    absolute_gap: float | None = Field(default=None, ge=0, le=1)


class ClassificationIsotonicBlock(BaseModel):
    lower_confidence: float = Field(ge=0, le=1)
    upper_confidence: float = Field(ge=0, le=1)
    calibrated_probability: float = Field(ge=0, le=1)
    count: int = Field(ge=1)


class ClassificationTopKAccuracy(BaseModel):
    k: int = Field(ge=1)
    accuracy: float | None = Field(default=None, ge=0, le=1)


class ClassificationEvaluationResponse(BaseModel):
    project_id: str
    model_id: str
    sample_count: int = Field(ge=0)
    correct_count: int = Field(ge=0)
    accuracy: float = Field(ge=0, le=1)
    balanced_accuracy: float = Field(default=0, ge=0, le=1)
    macro_precision: float = Field(ge=0, le=1)
    macro_recall: float = Field(ge=0, le=1)
    macro_f1: float = Field(ge=0, le=1)
    weighted_f1: float = Field(ge=0, le=1)
    matthews_correlation_coefficient: float = Field(default=0, ge=-1, le=1)
    cohen_kappa: float = Field(default=0, ge=-1, le=1)
    mean_confidence: float | None = Field(default=None, ge=0, le=1)
    expected_calibration_error: float | None = Field(default=None, ge=0, le=1)
    top_label_brier_score: float | None = Field(default=None, ge=0, le=1)
    temperature_scale: float | None = Field(default=None, gt=0)
    temperature_scaled_negative_log_likelihood: float | None = Field(default=None, ge=0)
    confidence_threshold: float = Field(ge=0, le=1)
    review_statuses: list[ClassificationReviewFilter]
    top_k_accuracy: list[ClassificationTopKAccuracy] = Field(default_factory=list)
    per_class: list[ClassificationClassEvaluation]
    confusion_matrix: list[ClassificationConfusionCell]
    calibration_bins: list[ClassificationCalibrationBin]
    isotonic_calibration: list[ClassificationIsotonicBlock] = Field(default_factory=list)
    warnings: list[str]
