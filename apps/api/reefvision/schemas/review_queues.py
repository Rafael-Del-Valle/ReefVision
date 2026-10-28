"""Typed request and response models for review-queue workflows."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from reefvision.domain.enums import ReviewQueueItemState


class ReviewScoreWeights(BaseModel):
    # NaN/Inf cannot be scientifically interpreted as priority weights.
    model_config = ConfigDict(allow_inf_nan=False)

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

    @model_validator(mode="after")
    def require_finite_positive_total_weight(self) -> Self:
        # Individual finite weights can still overflow when summed; an
        # all-zero vector also has no meaningful priority normalization.
        total_weight = sum(self.model_dump().values())
        if not isfinite(total_weight) or total_weight <= 0:
            raise ValueError("Review score weights require a finite, positive total")
        return self


class ReviewQueueCreateRequest(BaseModel):
    source_quality_control_run_id: str | None = None
    signal_weights: ReviewScoreWeights = Field(default_factory=ReviewScoreWeights)
    review_below_confidence: float | None = Field(default=None, ge=0, le=1)
    created_by: str | None = Field(default=None, max_length=100)


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


class ReviewQueueItemActorRequest(BaseModel):
    """Optional self-reported local reviewer label; never an authenticated identity."""

    actor: str = Field(default="local_user", min_length=1, max_length=100)

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        actor = value.strip()
        if not actor:
            raise ValueError("Reviewer label cannot be blank")
        return actor


class ReviewQueueItemSkipRequest(ReviewQueueItemActorRequest):
    reason: str = Field(min_length=1, max_length=500)


class ReviewQueueBulkRequest(BaseModel):
    """Explicit local-operator action; cannot verify biological observations."""

    item_ids: list[str] = Field(min_length=1, max_length=100)
    action: Literal["start", "skip", "return", "complete"]
    reason: str | None = Field(default=None, max_length=500)
    # Self-reported local label, not authenticated account identity.
    actor: str = Field(default="local_user", min_length=1, max_length=100)
    review_confirmed: StrictBool = False
    # Optional stable ID: repeat an uncertain request without reapplying it
    # after another researcher changes the queue state.
    client_request_id: UUID | None = None

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        actor = value.strip()
        if not actor:
            raise ValueError("Bulk triage actor label cannot be blank")
        return actor

    @model_validator(mode="after")
    def require_manual_review_confirmation(self) -> Self:
        if self.action == "complete" and not self.review_confirmed:
            raise ValueError("Bulk completion requires explicit manual-review confirmation")
        if self.action != "complete" and self.review_confirmed:
            raise ValueError("Review confirmation is only accepted for bulk completion")
        return self


class ReviewQueueBulkResponse(BaseModel):
    queue_id: str
    action: Literal["start", "skip", "return", "complete"]
    changed_count: int
    items: list[ReviewQueueItemResponse]
    requires_researcher_review: bool = True
