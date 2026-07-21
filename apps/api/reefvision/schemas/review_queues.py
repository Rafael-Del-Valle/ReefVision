"""Typed request and response models for review-queue workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from reefvision.domain.enums import ReviewQueueItemState


class ReviewScoreWeights(BaseModel):
    low_mean_confidence: float = Field(default=24.0, ge=0)
    low_min_confidence: float = Field(default=12.0, ge=0)
    pending_proposals: float = Field(default=14.0, ge=0)
    rejection_rate: float = Field(default=8.0, ge=0)
    count_disagreement: float = Field(default=12.0, ge=0)
    unresolved_qc_severity: float = Field(default=18.0, ge=0)
    rare_class_presence: float = Field(default=5.0, ge=0)
    edited_acceptance_rate: float = Field(default=6.0, ge=0)
    unreviewed_state: float = Field(default=10.0, ge=0)
    missing_group_metadata: float = Field(default=4.0, ge=0)
    incomplete_provenance: float = Field(default=5.0, ge=0)
    recent_import: float = Field(default=4.0, ge=0)
    stale_review_state: float = Field(default=6.0, ge=0)


class ReviewQueueCreateRequest(BaseModel):
    source_quality_control_run_id: str | None = None
    signal_weights: ReviewScoreWeights = Field(default_factory=ReviewScoreWeights)
    created_by: str | None = Field(default=None, max_length=100)
    queue_kind: Literal["priority", "active_learning"] = "priority"
    max_items: int = Field(default=100, ge=1, le=500)
    min_priority_score: float = Field(default=0.0, ge=0.0, le=100.0)
    diversity_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    max_items_per_group: int | None = Field(default=None, ge=1, le=500)
    include_reviewed: bool = False


class ReviewScoreComponentResponse(BaseModel):
    signal_id: str
    label: str
    raw_value: float
    normalized_value: float
    weight: float
    contribution: float
    description: str


class ReviewQueueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    dataset_version_id: str | None
    source_quality_control_run_id: str | None
    regenerated_from_queue_id: str | None
    scope_type: str
    status: str
    revision: int = 1
    generation_key: str | None = None
    formula_id: str
    formula_version: str
    configuration_json: dict[str, Any]
    input_checksums_json: dict[str, Any]
    summary_json: dict[str, Any]
    item_count: int
    created_by: str
    created_at: datetime
    completed_at: datetime | None
    error_message: str | None
    promoted_dataset_version_id: str | None = None
    promoted_cycle_id: str | None = None
    promoted_at: datetime | None = None


class ReviewQueueItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    review_queue_id: str
    project_id: str
    dataset_version_id: str | None
    image_id: str
    split: str | None
    review_state: ReviewQueueItemState
    score: float
    rank_position: int
    highest_qc_severity: str | None
    label_class_ids_json: list[str]
    model_ids_json: list[str]
    related_issue_ids_json: list[str]
    signal_values_json: dict[str, Any]
    normalized_signals_json: dict[str, float]
    weights_json: dict[str, float]
    score_breakdown_json: list[ReviewScoreComponentResponse]
    input_checksum: str
    reason_summary: str | None
    selection_reasons_json: list[str] = Field(default_factory=list)
    manual_state: str = "automatic"
    fragment_key: str | None = None
    near_duplicate_key: str | None = None
    skip_reason: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    returned_at: datetime | None


class ReviewQueueItemPageResponse(BaseModel):
    items: list[ReviewQueueItemResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ReviewQueueItemSkipRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
