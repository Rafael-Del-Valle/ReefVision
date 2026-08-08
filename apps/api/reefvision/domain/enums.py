"""Stable string values shared across ReefVision domains."""

from typing import Literal

AnnotationStatus = Literal["unannotated", "in_progress", "annotated", "reviewed", "excluded"]
AnnotationSourceType = Literal["human", "accepted_prediction", "assist_mask", "imported"]
AnnotationEventType = Literal["created", "updated", "class_changed", "deleted", "restored"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancel_requested", "cancelled"]
JobType = Literal[
    "thumbnail",
    "import",
    "inference",
    "classification_inference",
    "classification_training",
    "export",
    "qc",
    "backup",
    "restore",
    "diagnostics",
    "training",
    "model_install",
    "video_extract",
    "video_tracking",
    "advanced_depth",
]
ModelPurpose = Literal[
    "detector",
    "segmenter",
    "semantic_segmenter",
    "classifier",
    "assist",
    "depth",
]
PredictionReviewStatus = Literal[
    "pending",
    "accepted",
    "rejected",
    "edited_and_accepted",
]
QualityControlSeverity = Literal["error", "warning", "info"]
QualityControlIssueStatus = Literal[
    "open",
    "acknowledged",
    "dismissed",
    "resolved_in_later_run",
    "no_longer_applicable",
]
QualityControlRuleCategory = Literal[
    "annotation_geometry",
    "annotation_semantics",
    "image_integrity",
    "predictions",
    "statistics",
    "dataset_versions",
]
ReviewQueueItemState = Literal["pending", "in_progress", "completed", "skipped"]

ANNOTATION_STATUSES: tuple[AnnotationStatus, ...] = (
    "unannotated",
    "in_progress",
    "annotated",
    "reviewed",
    "excluded",
)
ANNOTATION_SOURCE_TYPES: tuple[AnnotationSourceType, ...] = (
    "human",
    "accepted_prediction",
    "assist_mask",
    "imported",
)
ANNOTATION_EVENT_TYPES: tuple[AnnotationEventType, ...] = (
    "created",
    "updated",
    "class_changed",
    "deleted",
    "restored",
)
MODEL_PURPOSES: tuple[ModelPurpose, ...] = (
    "detector",
    "segmenter",
    "semantic_segmenter",
    "classifier",
    "assist",
    "depth",
)
PREDICTION_REVIEW_STATUSES: tuple[PredictionReviewStatus, ...] = (
    "pending",
    "accepted",
    "rejected",
    "edited_and_accepted",
)
QUALITY_CONTROL_SEVERITIES: tuple[QualityControlSeverity, ...] = ("error", "warning", "info")
QUALITY_CONTROL_ISSUE_STATUSES: tuple[QualityControlIssueStatus, ...] = (
    "open",
    "acknowledged",
    "dismissed",
    "resolved_in_later_run",
    "no_longer_applicable",
)
QUALITY_CONTROL_RULE_CATEGORIES: tuple[QualityControlRuleCategory, ...] = (
    "annotation_geometry",
    "annotation_semantics",
    "image_integrity",
    "predictions",
    "statistics",
    "dataset_versions",
)
REVIEW_QUEUE_ITEM_STATES: tuple[ReviewQueueItemState, ...] = (
    "pending",
    "in_progress",
    "completed",
    "skipped",
)
