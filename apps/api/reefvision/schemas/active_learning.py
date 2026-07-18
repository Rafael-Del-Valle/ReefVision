"""Typed active-learning round contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ActiveLearningStrategy = Literal["hybrid", "uncertainty", "rare_class", "quality"]


class ActiveLearningRoundCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    dataset_version_id: str | None = Field(default=None, max_length=36)
    strategy: ActiveLearningStrategy = "hybrid"
    requested_size: int = Field(default=50, ge=1, le=5000)
    model_ids: list[str] = Field(default_factory=list, max_length=20)
    created_by: str | None = Field(default=None, max_length=100)


class ActiveLearningRoundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    dataset_version_id: str | None
    review_queue_id: str
    name: str
    strategy: str
    status: str
    requested_size: int
    selected_count: int
    model_ids_json: list[str]
    strategy_config_json: dict[str, Any]
    selection_manifest_json: dict[str, Any]
    selection_sha256: str
    feedback_summary_json: dict[str, Any]
    created_by: str
    created_at: datetime
    completed_at: datetime | None


class ActiveLearningFeedbackResponse(BaseModel):
    round_id: str
    status: str
    selected_count: int
    pending_count: int
    in_progress_count: int
    completed_count: int
    skipped_count: int
    completion_fraction: float
    prediction_review_counts: dict[str, int]
