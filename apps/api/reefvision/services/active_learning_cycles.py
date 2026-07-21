"""Persisted active-learning cycle state, promotion gates, and stop conditions."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ActiveLearningCycle,
    DatasetVersion,
    ModelRegistration,
    Project,
    ReviewQueue,
    TrainingRun,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.active_learning_cycles import (
    ActiveLearningCycleCreateRequest,
    ActiveLearningCycleResponse,
    ActiveLearningDatasetRecordRequest,
    ActiveLearningEvaluationRequest,
    ActiveLearningNextCycleRequest,
    ActiveLearningPromotionResponse,
    ActiveLearningReviewProgressRequest,
    ActiveLearningSelectionRecordRequest,
    ActiveLearningTrainingRecordRequest,
    PromotionGate,
    PromotionGateResult,
)

_TERMINAL = {"promoted", "retained_baseline", "stopped", "failed"}


def _event(event_type: str, **details: object) -> dict[str, object]:
    return {
        "event_type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        **details,
    }


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return value > threshold
    if operator == ">=":
        return value >= threshold
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    raise ValidationError("Unsupported promotion-gate operator")


class ActiveLearningCycleService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _cycle(self, cycle_id: str) -> ActiveLearningCycle:
        cycle = self.session.get(ActiveLearningCycle, cycle_id)
        if cycle is None:
            raise NotFoundError("Active-learning cycle not found")
        return cycle

    @staticmethod
    def _ensure_open(cycle: ActiveLearningCycle) -> None:
        if cycle.status in _TERMINAL:
            raise ConflictError("Completed active-learning cycles are immutable")

    @staticmethod
    def _metric_map(values: dict[str, Any]) -> dict[str, float]:
        return {
            str(key): float(value)
            for key, value in values.items()
            if isinstance(value, (int, float))
        }

    def _response(self, cycle: ActiveLearningCycle) -> ActiveLearningCycleResponse:
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
            embedding_provider_id=cycle.embedding_provider_id,
            embedding_model_id=cycle.embedding_model_id,
            embedding_model_checksum=cycle.embedding_model_checksum,
            queue_revision=cycle.queue_revision,
            accepted_annotation_ids=list(cycle.accepted_annotation_ids_json or []),
            rejected_item_ids=list(cycle.rejected_item_ids_json or []),
            warnings=list(cycle.warnings_json or []),
            selection_config=dict(cycle.selection_config_json or {}),
            selection_result=dict(cycle.selection_result_json or {}),
            baseline_metrics=dict(cycle.baseline_metrics_json or {}),
            candidate_metrics=dict(cycle.candidate_metrics_json or {}),
            promotion_gates=[
                PromotionGate.model_validate(item)
                for item in dict(cycle.promotion_gates_json or {}).get("gates", [])
            ],
            promotion_results=[
                PromotionGateResult.model_validate(item)
                for item in dict(cycle.promotion_result_json or {}).get("results", [])
            ],
            stop_conditions=dict(cycle.stop_conditions_json or {}),
            history=list(cycle.history_json or []),
            notes=cycle.notes,
            created_at=cycle.created_at,
            updated_at=cycle.updated_at,
            completed_at=cycle.completed_at,
        )

    def list(self, project_id: str) -> list[ActiveLearningCycleResponse]:
        self._project(project_id)
        cycles = self.session.scalars(
            select(ActiveLearningCycle)
            .where(ActiveLearningCycle.project_id == project_id)
            .order_by(ActiveLearningCycle.cycle_index, ActiveLearningCycle.id)
        )
        return [self._response(cycle) for cycle in cycles]

    def get(self, cycle_id: str) -> ActiveLearningCycleResponse:
        return self._response(self._cycle(cycle_id))

    def create(
        self,
        project_id: str,
        request: ActiveLearningCycleCreateRequest,
    ) -> ActiveLearningCycleResponse:
        self._project(project_id)
        parent = None
        if request.parent_cycle_id:
            parent = self._cycle(request.parent_cycle_id)
            if parent.project_id != project_id:
                raise ValidationError("Parent cycle must belong to the selected project")
        if request.source_model_id:
            model = self.session.get(ModelRegistration, request.source_model_id)
            if model is None or model.project_id != project_id:
                raise ValidationError("Source model must belong to the selected project")
        maximum_index = self.session.scalar(
            select(func.max(ActiveLearningCycle.cycle_index)).where(
                ActiveLearningCycle.project_id == project_id
            )
        )
        cycle_index = int(maximum_index or 0) + 1
        stop_conditions = {
            "stop_after_cycles": request.stop_after_cycles,
            "stop_after_annotations": request.stop_after_annotations,
            "plateau_metric": request.plateau_metric,
            "plateau_minimum_improvement": request.plateau_minimum_improvement,
            "plateau_patience_cycles": request.plateau_patience_cycles,
        }
        cycle = ActiveLearningCycle(
            project_id=project_id,
            parent_cycle_id=parent.id if parent else None,
            cycle_index=cycle_index,
            name=request.name.strip(),
            status="selection",
            selection_strategy=request.selection_strategy,
            annotation_budget=request.annotation_budget,
            source_model_id=request.source_model_id,
            selection_config_json=dict(request.selection_config),
            selection_result_json={},
            baseline_metrics_json={},
            candidate_metrics_json={},
            promotion_gates_json={
                "gates": [gate.model_dump(mode="json") for gate in request.promotion_gates]
            },
            promotion_result_json={},
            stop_conditions_json=stop_conditions,
            history_json=[
                _event(
                    "cycle_created",
                    cycle_index=cycle_index,
                    parent_cycle_id=parent.id if parent else None,
                )
            ],
            notes=request.notes,
        )
        self.session.add(cycle)
        self.session.commit()
        self.session.refresh(cycle)
        return self._response(cycle)

    def record_selection(
        self,
        cycle_id: str,
        request: ActiveLearningSelectionRecordRequest,
    ) -> ActiveLearningCycleResponse:
        cycle = self._cycle(cycle_id)
        self._ensure_open(cycle)
        if cycle.status != "selection":
            raise ConflictError("Selection can only be recorded during the selection stage")
        selected = list(dict.fromkeys(request.selected_candidate_ids))
        if len(selected) > cycle.annotation_budget:
            raise ValidationError("Selection exceeds the active-learning annotation budget")
        if request.review_queue_id:
            queue = self.session.get(ReviewQueue, request.review_queue_id)
            if queue is None or queue.project_id != cycle.project_id:
                raise ValidationError("Review queue must belong to the cycle project")
        cycle.review_queue_id = request.review_queue_id
        cycle.selected_count = len(selected)
        cycle.selection_result_json = {
            **dict(request.selection_result),
            "selected_candidate_ids": selected,
        }
        cycle.status = "review"
        cycle.history_json = [
            *list(cycle.history_json or []),
            _event(
                "selection_recorded",
                selected_count=len(selected),
                review_queue_id=request.review_queue_id,
            ),
        ]
        self.session.commit()
        self.session.refresh(cycle)
        return self._response(cycle)

    def record_review_progress(
        self,
        cycle_id: str,
        request: ActiveLearningReviewProgressRequest,
    ) -> ActiveLearningCycleResponse:
        cycle = self._cycle(cycle_id)
        self._ensure_open(cycle)
        if cycle.status != "review":
            raise ConflictError("Review progress can only be updated during review")
        if request.reviewed_count > cycle.selected_count:
            raise ValidationError("Reviewed count cannot exceed selected count")
        if request.reviewed_count < cycle.reviewed_count:
            raise ValidationError("Reviewed count cannot move backwards")
        cycle.reviewed_count = request.reviewed_count
        cycle.history_json = [
            *list(cycle.history_json or []),
            _event("review_progress", reviewed_count=request.reviewed_count),
        ]
        self.session.commit()
        self.session.refresh(cycle)
        return self._response(cycle)

    def record_dataset(
        self,
        cycle_id: str,
        request: ActiveLearningDatasetRecordRequest,
    ) -> ActiveLearningCycleResponse:
        cycle = self._cycle(cycle_id)
        self._ensure_open(cycle)
        if cycle.status != "review":
            raise ConflictError("A dataset can only be frozen after review")
        if cycle.reviewed_count < cycle.selected_count:
            raise ConflictError("Complete the selected review batch before freezing a dataset")
        version = self.session.get(DatasetVersion, request.dataset_version_id)
        if version is None or version.project_id != cycle.project_id:
            raise ValidationError("Dataset version must belong to the cycle project")
        if version.status != "complete":
            raise ValidationError("Only complete immutable dataset versions can be attached")
        cycle.dataset_version_id = version.id
        cycle.status = "dataset_frozen"
        cycle.history_json = [
            *list(cycle.history_json or []),
            _event("dataset_frozen", dataset_version_id=version.id),
        ]
        self.session.commit()
        self.session.refresh(cycle)
        return self._response(cycle)

    def record_training(
        self,
        cycle_id: str,
        request: ActiveLearningTrainingRecordRequest,
    ) -> ActiveLearningCycleResponse:
        cycle = self._cycle(cycle_id)
        self._ensure_open(cycle)
        if cycle.status not in {"dataset_frozen", "training"}:
            raise ConflictError("Training can only be attached after freezing the dataset")
        run = self.session.get(TrainingRun, request.training_run_id)
        if run is None or run.project_id != cycle.project_id:
            raise ValidationError("Training run must belong to the cycle project")
        if cycle.dataset_version_id and run.dataset_version_id != cycle.dataset_version_id:
            raise ValidationError("Training run must use the cycle's frozen dataset version")
        if request.candidate_model_id:
            model = self.session.get(ModelRegistration, request.candidate_model_id)
            if model is None or model.project_id != cycle.project_id:
                raise ValidationError("Candidate model must belong to the cycle project")
            if model.id == cycle.source_model_id:
                raise ValidationError(
                    "The resulting model must remain distinct from the cycle source model"
                )
            if model.metadata_json.get("source_training_run_id") != run.id:
                raise ValidationError(
                    "Candidate model must be registered from the attached training run"
                )
        cycle.training_run_id = run.id
        cycle.candidate_model_id = request.candidate_model_id
        cycle.status = "training" if run.status not in {"completed", "succeeded"} else "evaluation"
        cycle.history_json = [
            *list(cycle.history_json or []),
            _event(
                "training_attached",
                training_run_id=run.id,
                candidate_model_id=request.candidate_model_id,
                run_status=run.status,
            ),
        ]
        self.session.commit()
        self.session.refresh(cycle)
        return self._response(cycle)

    def evaluate_and_promote(
        self,
        cycle_id: str,
        request: ActiveLearningEvaluationRequest,
    ) -> ActiveLearningPromotionResponse:
        cycle = self._cycle(cycle_id)
        self._ensure_open(cycle)
        if cycle.status not in {"training", "evaluation"}:
            raise ConflictError("Candidate evaluation requires an attached training run")
        candidate_model_id = request.candidate_model_id or cycle.candidate_model_id
        if candidate_model_id:
            model = self.session.get(ModelRegistration, candidate_model_id)
            if model is None or model.project_id != cycle.project_id:
                raise ValidationError("Candidate model must belong to the cycle project")
            if model.id == cycle.source_model_id:
                raise ValidationError(
                    "The resulting model must remain distinct from the cycle source model"
                )
            if (
                cycle.training_run_id
                and model.metadata_json.get("source_training_run_id") != cycle.training_run_id
            ):
                raise ValidationError(
                    "Candidate model must be registered from the cycle training run"
                )
        baseline = self._metric_map(request.baseline_metrics)
        candidate = self._metric_map(request.candidate_metrics)
        compatibility_warnings: list[str] = []
        comparison_compatible = True
        if (
            request.baseline_dataset_version_id
            and request.candidate_dataset_version_id
            and request.baseline_dataset_version_id != request.candidate_dataset_version_id
        ):
            comparison_compatible = False
            compatibility_warnings.append(
                "Baseline and candidate evaluations use different immutable dataset versions."
            )
        elif bool(request.baseline_dataset_version_id) != bool(
            request.candidate_dataset_version_id
        ):
            compatibility_warnings.append(
                "Dataset compatibility is not fully specified for both evaluations."
            )
        if (
            request.baseline_metric_schema_id
            and request.candidate_metric_schema_id
            and request.baseline_metric_schema_id != request.candidate_metric_schema_id
        ):
            comparison_compatible = False
            compatibility_warnings.append(
                "Baseline and candidate evaluations use incompatible metric schemas."
            )
        elif bool(request.baseline_metric_schema_id) != bool(request.candidate_metric_schema_id):
            compatibility_warnings.append(
                "Metric-schema compatibility is not fully specified for both evaluations."
            )
        baseline_keys = set(baseline)
        candidate_keys = set(candidate)
        if baseline_keys and candidate_keys and not baseline_keys.intersection(candidate_keys):
            comparison_compatible = False
            compatibility_warnings.append(
                "Baseline and candidate evaluations contain no shared metric names."
            )
        elif baseline_keys != candidate_keys:
            compatibility_warnings.append(
                "Metric sets differ; only shared, explicitly gated metrics are comparable."
            )
        gates = [
            PromotionGate.model_validate(item)
            for item in dict(cycle.promotion_gates_json or {}).get("gates", [])
        ]
        results: list[PromotionGateResult] = []
        for gate in gates:
            baseline_value = baseline.get(gate.metric)
            candidate_value = candidate.get(gate.metric)
            comparison_value = None
            if candidate_value is not None:
                comparison_value = (
                    candidate_value - baseline_value
                    if gate.relative_to_baseline and baseline_value is not None
                    else candidate_value
                )
            passed = comparison_value is not None and _compare(
                comparison_value, gate.operator, float(gate.threshold)
            )
            results.append(
                PromotionGateResult(
                    metric=gate.metric,
                    operator=gate.operator,
                    threshold=float(gate.threshold),
                    relative_to_baseline=gate.relative_to_baseline,
                    required=gate.required,
                    baseline_value=baseline_value,
                    candidate_value=candidate_value,
                    comparison_value=comparison_value,
                    passed=passed,
                    message=(
                        "Promotion gate passed."
                        if passed
                        else "Metric was missing or did not meet the configured threshold."
                    ),
                )
            )
        all_required_passed = comparison_compatible and all(
            item.passed for item in results if item.required
        )
        promoted = all_required_passed and candidate_model_id is not None
        cycle.baseline_metrics_json = baseline
        cycle.candidate_metrics_json = candidate
        cycle.promotion_result_json = {
            "results": [item.model_dump(mode="json") for item in results],
            "all_required_gates_passed": all_required_passed,
            "promoted": promoted,
            "comparison_compatible": comparison_compatible,
            "compatibility_warnings": compatibility_warnings,
            "baseline_dataset_version_id": request.baseline_dataset_version_id,
            "candidate_dataset_version_id": request.candidate_dataset_version_id,
            "baseline_metric_schema_id": request.baseline_metric_schema_id,
            "candidate_metric_schema_id": request.candidate_metric_schema_id,
        }
        cycle.warnings_json = list(
            dict.fromkeys([*list(cycle.warnings_json or []), *compatibility_warnings])
        )
        cycle.candidate_model_id = candidate_model_id
        cycle.promoted_model_id = candidate_model_id if promoted else None
        cycle.status = "promoted" if promoted else "retained_baseline"
        cycle.completed_at = datetime.now(UTC)
        stop_reasons = self._stop_reasons(cycle)
        stopped = bool(stop_reasons)
        cycle.history_json = [
            *list(cycle.history_json or []),
            _event(
                "candidate_evaluated",
                promoted=promoted,
                all_required_gates_passed=all_required_passed,
                comparison_compatible=comparison_compatible,
                compatibility_warnings=compatibility_warnings,
                stop_reasons=stop_reasons,
            ),
        ]
        self.session.commit()
        self.session.refresh(cycle)
        return ActiveLearningPromotionResponse(
            cycle=self._response(cycle),
            all_required_gates_passed=all_required_passed,
            promoted=promoted,
            stopped=stopped,
            stop_reasons=stop_reasons,
            comparison_compatible=comparison_compatible,
            compatibility_warnings=compatibility_warnings,
        )

    def _stop_reasons(
        self,
        cycle: ActiveLearningCycle,
    ) -> builtins.list[str]:
        conditions = dict(cycle.stop_conditions_json or {})
        reasons: builtins.list[str] = []
        stop_after_cycles = conditions.get("stop_after_cycles")
        if isinstance(stop_after_cycles, int) and cycle.cycle_index >= stop_after_cycles:
            reasons.append("maximum cycle count reached")
        stop_after_annotations = conditions.get("stop_after_annotations")
        if isinstance(stop_after_annotations, int):
            reviewed_total = int(
                self.session.scalar(
                    select(func.sum(ActiveLearningCycle.reviewed_count)).where(
                        ActiveLearningCycle.project_id == cycle.project_id
                    )
                )
                or 0
            )
            if reviewed_total >= stop_after_annotations:
                reasons.append("annotation budget reached")
        metric = conditions.get("plateau_metric")
        minimum = conditions.get("plateau_minimum_improvement")
        patience = conditions.get("plateau_patience_cycles")
        if (
            isinstance(metric, str)
            and isinstance(minimum, (int, float))
            and isinstance(patience, int)
        ):
            cycles = list(
                self.session.scalars(
                    select(ActiveLearningCycle)
                    .where(
                        ActiveLearningCycle.project_id == cycle.project_id,
                        ActiveLearningCycle.cycle_index <= cycle.cycle_index,
                    )
                    .order_by(ActiveLearningCycle.cycle_index.desc())
                    .limit(patience)
                )
            )
            improvements = []
            for item in cycles:
                baseline = self._metric_map(item.baseline_metrics_json)
                candidate = self._metric_map(item.candidate_metrics_json)
                if metric in baseline and metric in candidate:
                    improvements.append(candidate[metric] - baseline[metric])
            if len(improvements) >= patience and all(
                improvement < float(minimum) for improvement in improvements
            ):
                reasons.append(f"{metric} improvement plateaued")
        return reasons

    def create_next(
        self,
        cycle_id: str,
        request: ActiveLearningNextCycleRequest,
    ) -> ActiveLearningCycleResponse:
        cycle = self._cycle(cycle_id)
        if cycle.status not in {"promoted", "retained_baseline"}:
            raise ConflictError("Complete candidate evaluation before creating the next cycle")
        stop_reasons = self._stop_reasons(cycle)
        if stop_reasons:
            raise ConflictError(
                "Configured stop condition prevents another cycle: " + "; ".join(stop_reasons)
            )
        conditions = dict(cycle.stop_conditions_json or {})
        return self.create(
            cycle.project_id,
            ActiveLearningCycleCreateRequest(
                name=request.name or f"{cycle.name} - cycle {cycle.cycle_index + 1}",
                selection_strategy=request.selection_strategy or cycle.selection_strategy,
                annotation_budget=request.annotation_budget or cycle.annotation_budget,
                source_model_id=cycle.promoted_model_id or cycle.source_model_id,
                parent_cycle_id=cycle.id,
                selection_config=dict(cycle.selection_config_json or {}),
                promotion_gates=[
                    PromotionGate.model_validate(item)
                    for item in dict(cycle.promotion_gates_json or {}).get("gates", [])
                ],
                stop_after_cycles=conditions.get("stop_after_cycles"),
                stop_after_annotations=conditions.get("stop_after_annotations"),
                plateau_metric=conditions.get("plateau_metric"),
                plateau_minimum_improvement=conditions.get("plateau_minimum_improvement"),
                plateau_patience_cycles=conditions.get("plateau_patience_cycles"),
                notes=cycle.notes,
            ),
        )

    def stop(self, cycle_id: str, reason: str) -> ActiveLearningCycleResponse:
        cycle = self._cycle(cycle_id)
        self._ensure_open(cycle)
        cycle.status = "stopped"
        cycle.completed_at = datetime.now(UTC)
        cycle.history_json = [
            *list(cycle.history_json or []),
            _event("cycle_stopped", reason=reason.strip()),
        ]
        self.session.commit()
        self.session.refresh(cycle)
        return self._response(cycle)
