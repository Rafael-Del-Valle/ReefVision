"""Bulk review, model comparison, and file-export schemas for classification."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BulkClassificationReviewRequest(BaseModel):
    prediction_ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["accept", "reject"]
    label_set_id: str | None = Field(default=None, max_length=36)
    label_class_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def validate_accept_options(self) -> BulkClassificationReviewRequest:
        self.prediction_ids = list(dict.fromkeys(self.prediction_ids))
        if self.action == "reject" and (self.label_set_id or self.label_class_id):
            raise ValueError("Label-set and class overrides apply only to accepted predictions")
        return self


class BulkClassificationReviewItem(BaseModel):
    prediction_id: str
    outcome: Literal["accepted", "rejected", "unchanged", "failed"]
    assignment_id: str | None = None
    message: str | None = None


class BulkClassificationReviewResponse(BaseModel):
    project_id: str
    requested_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    items: list[BulkClassificationReviewItem]


class ClassificationModelPredictionComparison(BaseModel):
    prediction_id: str
    model_id: str
    model_name: str
    predicted_label: str
    label_class_id: str | None = None
    confidence: float
    review_status: str
    probabilities: dict[str, float] = Field(default_factory=dict)


class ClassificationTargetComparison(BaseModel):
    target_kind: str
    target_key: str
    image_id: str
    label_set: str
    model_count: int = Field(ge=1)
    agreement: bool
    compared_values: list[str]
    predictions: list[ClassificationModelPredictionComparison]


class ClassificationComparisonResponse(BaseModel):
    project_id: str
    target_count: int = Field(ge=0)
    agreement_count: int = Field(ge=0)
    disagreement_count: int = Field(ge=0)
    minimum_models: int = Field(ge=1)
    targets: list[ClassificationTargetComparison]
