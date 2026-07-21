"""Typed requests for diversity-aware active-learning queues."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from reefvision.schemas.review_queues import ReviewScoreWeights


class ActiveLearningQueueCreateRequest(BaseModel):
    """Configuration for selecting a compact, diverse annotation batch."""

    source_quality_control_run_id: str | None = None
    signal_weights: ReviewScoreWeights = Field(default_factory=ReviewScoreWeights)
    max_items: int = Field(default=100, ge=1, le=500)
    min_priority_score: float = Field(default=0.0, ge=0.0, le=100.0)
    diversity_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    max_items_per_group: int | None = Field(default=None, ge=1, le=500)
    max_items_per_fragment: int | None = Field(default=None, ge=1, le=500)
    include_reviewed: bool = False
    selection_strategy: Literal[
        "uncertainty",
        "least_confidence",
        "margin",
        "entropy",
        "farthest_point",
        "k_center",
        "kmeans_representative",
        "cluster_balanced",
        "density_aware",
        "pareto_uncertainty_diversity",
    ] = "k_center"
    uncertainty_weight: float = Field(default=0.45, ge=0.0, le=1.0)
    novelty_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    base_priority_weight: float = Field(default=0.1, ge=0.0, le=1.0)
    density_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    embedding_provider_id: str | None = Field(default=None, max_length=100)
    embedding_model_id: str | None = Field(default=None, max_length=300)
    embedding_model_checksum: str | None = Field(default=None, min_length=64, max_length=64)
    embedding_preprocessing_version: str | None = Field(default=None, max_length=100)
    source_model_id: str | None = Field(default=None, max_length=36)
    class_balancing: bool = True
    suppress_exact_duplicates: bool = True
    suppress_near_duplicates: bool = True
    near_duplicate_cosine_similarity: float = Field(default=0.995, ge=-1.0, le=1.0)
    fragment_metadata_key: str = Field(default="fragment_id", min_length=1, max_length=100)
    manual_include_image_ids: list[str] = Field(default_factory=list, max_length=500)
    manual_exclude_image_ids: list[str] = Field(default_factory=list, max_length=500)
    create_cycle: bool = True
    cycle_name: str | None = Field(default=None, max_length=240)
    created_by: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_selection(self) -> ActiveLearningQueueCreateRequest:
        if set(self.manual_include_image_ids) & set(self.manual_exclude_image_ids):
            raise ValueError("An image cannot be both manually included and excluded")
        if len(self.manual_include_image_ids) != len(set(self.manual_include_image_ids)):
            raise ValueError("Manual include image IDs must be unique")
        if len(self.manual_exclude_image_ids) != len(set(self.manual_exclude_image_ids)):
            raise ValueError("Manual exclude image IDs must be unique")
        if bool(self.embedding_provider_id) != bool(self.embedding_model_id):
            raise ValueError("Embedding provider and model must be selected together")
        total_weight = (
            self.uncertainty_weight
            + (self.novelty_weight if self.novelty_weight is not None else self.diversity_weight)
            + self.base_priority_weight
            + self.density_weight
        )
        if total_weight <= 0:
            raise ValueError("At least one active-learning score weight must be positive")
        return self


class ActiveLearningQueuePromotionRequest(BaseModel):
    """Create exactly one immutable dataset snapshot from a completed queue revision."""

    name: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    creator: str | None = Field(default=None, max_length=100)
    parent_version_id: str | None = Field(default=None, max_length=36)
    split_method: Literal["none", "random", "group_random"] = "group_random"
    split_seed: int | None = None
    cycle_id: str | None = Field(default=None, max_length=36)


class ActiveLearningQueuePromotionResponse(BaseModel):
    queue_id: str
    queue_revision: int = Field(ge=1)
    dataset_version_id: str
    cycle_id: str | None
    promoted_at: str
    idempotent_replay: bool = False
