"""Segmentation-model evaluation request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SegmentationEvaluationRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    image_ids: list[str] = Field(default_factory=list)
    confidence_threshold: float = Field(default=0.25, ge=0, le=1)
    match_iou_threshold: float = Field(default=0.5, ge=0, le=1)
    include_accepted_predictions: bool = True
    include_pending_predictions: bool = True
    boundary_tolerance_pixels: float = Field(default=2, ge=0, le=1000)
    confidence_sweep: list[float] = Field(
        default_factory=lambda: [0.05, 0.1, 0.25, 0.5, 0.75],
        min_length=1,
        max_length=101,
    )
    average_precision_iou_thresholds: list[float] = Field(
        default_factory=lambda: [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95],
        min_length=1,
        max_length=101,
    )
    calibration_bin_count: int = Field(default=10, ge=1, le=100)
    small_object_max_pixels: int = Field(default=1024, ge=1)
    large_object_min_pixels: int = Field(default=9216, ge=2)

    @field_validator("confidence_sweep", "average_precision_iou_thresholds")
    @classmethod
    def validate_thresholds(cls, values: list[float]) -> list[float]:
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("Evaluation thresholds must be between zero and one")
        return sorted(set(values))


class SegmentationInstanceMatch(BaseModel):
    image_id: str
    label_class_id: str | None
    ground_truth_mask_id: str
    prediction_id: str
    intersection_pixels: int = Field(ge=0)
    union_pixels: int = Field(ge=0)
    ground_truth_area_pixels: int = Field(default=0, ge=0)
    prediction_area_pixels: int = Field(default=0, ge=0)
    size_stratum: str = "unknown"
    touches_image_boundary: bool = False
    iou: float = Field(ge=0, le=1)
    dice: float = Field(ge=0, le=1)
    pixel_precision: float = Field(ge=0, le=1)
    pixel_recall: float = Field(ge=0, le=1)
    boundary_precision: float | None = Field(default=None, ge=0, le=1)
    boundary_recall: float | None = Field(default=None, ge=0, le=1)
    boundary_f1: float | None = Field(default=None, ge=0, le=1)
    hausdorff_distance_pixels: float | None = Field(default=None, ge=0)
    average_symmetric_surface_distance_pixels: float | None = Field(default=None, ge=0)


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
    mean_boundary_f1: float | None = Field(default=None, ge=0, le=1)
    mean_hausdorff_distance_pixels: float | None = Field(default=None, ge=0)
    mean_average_symmetric_surface_distance_pixels: float | None = Field(
        default=None,
        ge=0,
    )
    panoptic_quality: float = Field(default=0, ge=0, le=1)
    segmentation_quality: float = Field(default=0, ge=0, le=1)
    recognition_quality: float = Field(default=0, ge=0, le=1)


class SegmentationImageEvaluation(BaseModel):
    image_id: str
    ground_truth_count: int = Field(ge=0)
    prediction_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    mean_iou: float | None = Field(default=None, ge=0, le=1)
    mean_dice: float | None = Field(default=None, ge=0, le=1)
    mean_boundary_f1: float | None = Field(default=None, ge=0, le=1)
    panoptic_quality: float = Field(ge=0, le=1)


class SegmentationThresholdSweepRow(BaseModel):
    confidence_threshold: float = Field(ge=0, le=1)
    true_positive_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)


class SegmentationAveragePrecisionRow(BaseModel):
    iou_threshold: float = Field(ge=0, le=1)
    average_precision: float = Field(ge=0, le=1)


class SegmentationCalibrationBin(BaseModel):
    lower: float = Field(ge=0, le=1)
    upper: float = Field(ge=0, le=1)
    count: int = Field(ge=0)
    mean_confidence: float | None = Field(default=None, ge=0, le=1)
    empirical_match_rate: float | None = Field(default=None, ge=0, le=1)
    calibration_gap: float | None = Field(default=None, ge=0, le=1)


class SegmentationSizeEvaluation(BaseModel):
    size_stratum: str
    ground_truth_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    mean_iou: float | None = Field(default=None, ge=0, le=1)
    mean_boundary_f1: float | None = Field(default=None, ge=0, le=1)


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
    mean_boundary_f1: float | None = Field(default=None, ge=0, le=1)
    mean_hausdorff_distance_pixels: float | None = Field(default=None, ge=0)
    mean_average_symmetric_surface_distance_pixels: float | None = Field(
        default=None,
        ge=0,
    )
    panoptic_quality: float = Field(default=0, ge=0, le=1)
    segmentation_quality: float = Field(default=0, ge=0, le=1)
    recognition_quality: float = Field(default=0, ge=0, le=1)
    expected_calibration_error: float = Field(default=0, ge=0, le=1)
    mean_average_precision: float = Field(default=0, ge=0, le=1)
    confidence_threshold: float = Field(ge=0, le=1)
    match_iou_threshold: float = Field(ge=0, le=1)
    boundary_tolerance_pixels: float = Field(default=2, ge=0)
    per_class: list[SegmentationClassEvaluation]
    per_image: list[SegmentationImageEvaluation] = Field(default_factory=list)
    per_size: list[SegmentationSizeEvaluation] = Field(default_factory=list)
    threshold_sweep: list[SegmentationThresholdSweepRow] = Field(default_factory=list)
    average_precision: list[SegmentationAveragePrecisionRow] = Field(default_factory=list)
    calibration_bins: list[SegmentationCalibrationBin] = Field(default_factory=list)
    matches: list[SegmentationInstanceMatch]
    warnings: list[str]
