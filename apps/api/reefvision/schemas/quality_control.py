"""Typed request and response models for quality-control workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reefvision.domain.enums import (
    QUALITY_CONTROL_RULE_CATEGORIES,
    QualityControlIssueStatus,
    QualityControlRuleCategory,
    QualityControlSeverity,
)


class QualityControlThresholdConfig(BaseModel):
    small_box_min_width_px: float = Field(default=6.0, ge=0)
    small_box_min_height_px: float = Field(default=6.0, ge=0)
    near_duplicate_iou_threshold: float = Field(default=0.9, ge=0, le=1)
    same_class_overlap_iou_threshold: float = Field(default=0.75, ge=0, le=1)
    different_class_overlap_iou_threshold: float = Field(default=0.8, ge=0, le=1)
    boundary_touch_margin_px: float = Field(default=0.0, ge=0)
    annotation_count_mad_multiplier: float = Field(default=3.5, ge=0)
    class_imbalance_majority_ratio: float = Field(default=0.85, ge=0, le=1)
    suspicious_bulk_acceptance_min_count: int = Field(default=12, ge=2)
    suspicious_bulk_acceptance_window_minutes: int = Field(default=10, ge=1, le=1_440)
    overlap_spatial_cell_px: int = Field(default=128, ge=8, le=4_096)


class QualityControlRunCreateRequest(BaseModel):
    rule_categories: list[QualityControlRuleCategory] = Field(
        default_factory=lambda: list(QUALITY_CONTROL_RULE_CATEGORIES)
    )
    selected_rule_ids: list[str] = Field(default_factory=list)
    thresholds: QualityControlThresholdConfig = Field(default_factory=QualityControlThresholdConfig)
    created_by: str | None = Field(default=None, max_length=100)


class QualityControlRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    dataset_version_id: str | None
    job_id: str | None
    scope_type: str
    status: str
    rule_categories_json: list[str]
    selected_rule_ids_json: list[str]
    thresholds_json: dict[str, Any]
    configuration_json: dict[str, Any]
    input_checksums_json: dict[str, Any]
    summary_json: dict[str, Any]
    issue_count: int
    created_by: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    error_message: str | None


class QualityControlIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    quality_control_run_id: str
    project_id: str
    dataset_version_id: str | None
    image_id: str | None
    rule_id: str
    rule_version: str
    severity: QualityControlSeverity
    status: QualityControlIssueStatus
    fingerprint: str
    title: str
    explanation: str
    annotation_ids_json: list[str]
    prediction_ids_json: list[str]
    class_ids_json: list[str]
    measured_values_json: dict[str, Any]
    thresholds_json: dict[str, Any]
    resolution_metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    dismissed_at: datetime | None
    dismissed_by: str | None
    dismissed_reason: str | None
    resolution_run_id: str | None


class QualityControlIssuePageResponse(BaseModel):
    items: list[QualityControlIssueResponse]
    total: int
    page: int
    page_size: int
    pages: int


class QualityControlIssueDismissRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    actor: str | None = Field(default=None, max_length=100)


class QualityControlIssueAcknowledgeRequest(BaseModel):
    actor: str | None = Field(default=None, max_length=100)


class QualityControlRunComparisonIssue(BaseModel):
    fingerprint: str
    rule_id: str
    severity: QualityControlSeverity
    title: str
    image_id: str | None


class QualityControlRunComparisonResponse(BaseModel):
    base_run_id: str
    compare_run_id: str
    added_count: int
    resolved_count: int
    unchanged_count: int
    added: list[QualityControlRunComparisonIssue]
    resolved: list[QualityControlRunComparisonIssue]
