"""Persisted active-learning retraining-cycle schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator

CycleStatus = Literal[
    "selection",
    "review",
    "dataset_frozen",
    "training",
    "evaluation",
    "promoted",
    "retained_baseline",
    "stopped",
    "failed",
]
ComparisonOperator = Literal[">", ">=", "<", "<="]


class PromotionGate(BaseModel):
    metric: str = Field(min_length=1, max_length=200)
    operator: ComparisonOperator = ">="
    threshold: FiniteFloat
    relative_to_baseline: bool = False
    required: bool = True


class ActiveLearningCycleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    selection_strategy: str = Field(min_length=1, max_length=80)
    annotation_budget: int = Field(ge=1, le=10_000_000)
    source_model_id: str | None = Field(default=None, max_length=36)
    parent_cycle_id: str | None = Field(default=None, max_length=36)
    selection_config: dict[str, object] = Field(default_factory=dict)
    promotion_gates: list[PromotionGate] = Field(default_factory=list, max_length=1000)
    stop_after_cycles: int | None = Field(default=None, ge=1, le=100_000)
    stop_after_annotations: int | None = Field(default=None, ge=1, le=1_000_000_000)
    plateau_metric: str | None = Field(default=None, max_length=200)
    plateau_minimum_improvement: FiniteFloat | None = Field(default=None, ge=0)
    plateau_patience_cycles: int | None = Field(default=None, ge=1, le=10_000)
    notes: str | None = Field(default=None, max_length=10_000)


class ActiveLearningSelectionRecordRequest(BaseModel):
    review_queue_id: str | None = Field(default=None, max_length=36)
    selected_candidate_ids: list[str] = Field(max_length=1_000_000)
    selection_result: dict[str, object] = Field(default_factory=dict)


class ActiveLearningReviewProgressRequest(BaseModel):
    reviewed_count: int = Field(ge=0)


class ActiveLearningDatasetRecordRequest(BaseModel):
    dataset_version_id: str | None = Field(default=None, max_length=36)
    classification_dataset_snapshot_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def exactly_one_dataset(self) -> ActiveLearningDatasetRecordRequest:
        selected = int(bool(self.dataset_version_id)) + int(
            bool(self.classification_dataset_snapshot_id)
        )
        if selected != 1:
            raise ValueError(
                "Choose exactly one immutable dataset: dataset_version_id or "
                "classification_dataset_snapshot_id"
            )
        return self


class ActiveLearningTrainingRecordRequest(BaseModel):
    training_run_id: str = Field(min_length=1, max_length=36)
    candidate_model_id: str | None = Field(default=None, max_length=36)


class ActiveLearningEvaluationRequest(BaseModel):
    baseline_metrics: dict[str, FiniteFloat] = Field(default_factory=dict)
    candidate_metrics: dict[str, FiniteFloat] = Field(default_factory=dict)
    candidate_model_id: str | None = Field(default=None, max_length=36)
    baseline_dataset_version_id: str | None = Field(default=None, max_length=36)
    candidate_dataset_version_id: str | None = Field(default=None, max_length=36)
    baseline_classification_snapshot_id: str | None = Field(default=None, max_length=36)
    candidate_classification_snapshot_id: str | None = Field(default=None, max_length=36)
    baseline_metric_schema_id: str | None = Field(default=None, max_length=200)
    candidate_metric_schema_id: str | None = Field(default=None, max_length=200)


class PromotionGateResult(BaseModel):
    metric: str
    operator: ComparisonOperator
    threshold: float
    relative_to_baseline: bool
    required: bool
    baseline_value: float | None
    candidate_value: float | None
    comparison_value: float | None
    passed: bool
    message: str


class ActiveLearningCycleResponse(BaseModel):
    id: str
    project_id: str
    parent_cycle_id: str | None
    cycle_index: int = Field(ge=1)
    name: str
    status: CycleStatus
    selection_strategy: str
    annotation_budget: int = Field(ge=1)
    selected_count: int = Field(ge=0)
    reviewed_count: int = Field(ge=0)
    source_model_id: str | None
    candidate_model_id: str | None
    promoted_model_id: str | None
    dataset_version_id: str | None
    classification_dataset_snapshot_id: str | None = None
    training_run_id: str | None
    review_queue_id: str | None
    embedding_provider_id: str | None = None
    embedding_model_id: str | None = None
    embedding_model_checksum: str | None = None
    queue_revision: int | None = None
    accepted_annotation_ids: list[str] = Field(default_factory=list)
    rejected_item_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    selection_config: dict[str, object]
    selection_result: dict[str, object]
    baseline_metrics: dict[str, object]
    candidate_metrics: dict[str, object]
    promotion_gates: list[PromotionGate]
    promotion_results: list[PromotionGateResult]
    stop_conditions: dict[str, object]
    history: list[dict[str, object]]
    notes: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ActiveLearningPromotionResponse(BaseModel):
    cycle: ActiveLearningCycleResponse
    all_required_gates_passed: bool
    promoted: bool
    stopped: bool
    stop_reasons: list[str]
    comparison_compatible: bool = True
    compatibility_warnings: list[str] = Field(default_factory=list)


class ActiveLearningNextCycleRequest(BaseModel):
    name: str | None = Field(default=None, max_length=240)
    annotation_budget: int | None = Field(default=None, ge=1, le=10_000_000)
    selection_strategy: str | None = Field(default=None, max_length=80)


class ActiveLearningCycleListResponse(BaseModel):
    cycles: list[ActiveLearningCycleResponse]


class ActiveLearningCycleStopRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def strip_reason(self) -> ActiveLearningCycleStopRequest:
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("Stop reason cannot be blank")
        return self
