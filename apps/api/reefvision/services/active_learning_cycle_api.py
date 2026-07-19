"""Corrected public response adapter for persisted active-learning cycles."""

from __future__ import annotations

from reefvision.db.models import ActiveLearningCycle
from reefvision.schemas.active_learning_cycles import (
    ActiveLearningCycleResponse,
    PromotionGate,
    PromotionGateResult,
)
from reefvision.services.active_learning_cycles import ActiveLearningCycleService


class PublicActiveLearningCycleService(ActiveLearningCycleService):
    def _response(self, cycle: ActiveLearningCycle) -> ActiveLearningCycleResponse:
        gate_container = dict(cycle.promotion_gates_json or {})
        result_container = dict(cycle.promotion_result_json or {})
        return ActiveLearningCycleResponse(
            id=cycle.id,
            project_id=cycle.project_id,
            parent_cycle_id=cycle.parent_cycle_id,
            cycle_index=cycle.cycle_index,
            name=cycle.name,
            status=cycle.status,
            selection_strategy=cycle.selection_strategy,
            annotation_budget=cycle.annotation_budget,
            selected_count=cycle.selected_count,
            reviewed_count=cycle.reviewed_count,
            source_model_id=cycle.source_model_id,
            candidate_model_id=cycle.candidate_model_id,
            promoted_model_id=cycle.promoted_model_id,
            dataset_version_id=cycle.dataset_version_id,
            training_run_id=cycle.training_run_id,
            review_queue_id=cycle.review_queue_id,
            selection_config=dict(cycle.selection_config_json or {}),
            selection_result=dict(cycle.selection_result_json or {}),
            baseline_metrics=dict(cycle.baseline_metrics_json or {}),
            candidate_metrics=dict(cycle.candidate_metrics_json or {}),
            promotion_gates=[
                PromotionGate.model_validate(item)
                for item in gate_container.get("gates", [])
            ],
            promotion_results=[
                PromotionGateResult.model_validate(item)
                for item in result_container.get("results", [])
            ],
            stop_conditions=dict(cycle.stop_conditions_json or {}),
            history=list(cycle.history_json or []),
            notes=cycle.notes,
            created_at=cycle.created_at,
            updated_at=cycle.updated_at,
            completed_at=cycle.completed_at,
        )
