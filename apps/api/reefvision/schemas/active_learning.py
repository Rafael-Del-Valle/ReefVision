"""Typed requests for diversity-aware active-learning queues."""

from __future__ import annotations

from pydantic import BaseModel, Field

from reefvision.schemas.review_queues import ReviewScoreWeights


class ActiveLearningQueueCreateRequest(BaseModel):
    """Configuration for selecting a compact, diverse annotation batch."""

    source_quality_control_run_id: str | None = None
    signal_weights: ReviewScoreWeights = Field(default_factory=ReviewScoreWeights)
    max_items: int = Field(default=100, ge=1, le=500)
    min_priority_score: float = Field(default=0.0, ge=0.0, le=100.0)
    diversity_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    max_items_per_group: int | None = Field(default=None, ge=1, le=500)
    include_reviewed: bool = False
    created_by: str | None = Field(default=None, max_length=100)
