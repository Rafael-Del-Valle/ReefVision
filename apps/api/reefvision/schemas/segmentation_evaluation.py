"""Segmentation-model evaluation request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SegmentationEvaluationRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    image_ids: list[str] = Field(default_factory=list)
    confidence_threshold: float = Field(default=0.25, ge=0, le=1)
    match_iou_threshold: float = Field(default=0.5, ge=0, le=1)
    include_accepted_predictions: bool = True
    include_pending_predictions: bool = True


class SegmentationInstanceMatch(BaseModel):
    image_id: str
    label_class_id: str | None
    ground_truth_mask_id: str
    prediction_id: str
    intersection_pixels: int = Field(ge=0)
    union_pixels: int = Field(ge=0)
    iou: float = Field(ge=0, le=1)
    dice: float = Field(ge=0, le=1)
    pixel_precision: float = Field(ge=0, le=1)
    pixel_recall: float = Field(ge=0, le=1)


class SegmentationClassEvaluation(BaseModel):
    label_class_id: str | None
    ground_truth_count: int = Field(ge=0)
    prediction_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    instance_precision: float = Field(ge=0, le=1)
    instance_recall: float = Field(ge=0, le=1)
    mean_iou: float | None = Field(default=None, ge=0, le=1)
    mean_dice: float | None = Field(default=None, ge=0, le=1)
    mean_pixel_precision: float | None = Field(default=None, ge=0, le=1)
    mean_pixel_recall: float | None = Field(default=None, ge=0, le=1)


class SegmentationEvaluationResponse(BaseModel):
    project_id: str
    model_id: str
    image_count: int = Field(ge=0)
    ground_truth_count: int = Field(ge=0)
    prediction_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    instance_precision: float = Field(ge=0, le=1)
    instance_recall: float = Field(ge=0, le=1)
    mean_iou: float | None = Field(default=None, ge=0, le=1)
    mean_dice: float | None = Field(default=None, ge=0, le=1)
    confidence_threshold: float = Field(ge=0, le=1)
    match_iou_threshold: float = Field(ge=0, le=1)
    per_class: list[SegmentationClassEvaluation]
    matches: list[SegmentationInstanceMatch]
    warnings: list[str]
