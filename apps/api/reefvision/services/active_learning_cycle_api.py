"""Corrected public response adapter for persisted active-learning cycles."""

from __future__ import annotations

from datetime import UTC, datetime

from reefvision.db.models import (
    ActiveLearningCycle,
    ClassificationDatasetSnapshot,
    ModelRegistration,
    TrainingRun,
)
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.active_learning_cycles import (
    ActiveLearningCycleResponse,
    ActiveLearningDatasetRecordRequest,
    ActiveLearningEvaluationRequest,
    ActiveLearningPromotionResponse,
    ActiveLearningTrainingRecordRequest,
    PromotionGate,
    PromotionGateResult,
)
from reefvision.services.active_learning_cycles import ActiveLearningCycleService


def _event(event_type: str, **details: object) -> dict[str, object]:
    return {
        "event_type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        **details,
    }


def _classification_snapshot_id(cycle: ActiveLearningCycle) -> str | None:
    raw = dict(cycle.selection_result_json or {}).get("classification_dataset_snapshot_id")
    return str(raw) if raw else None


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
            classification_dataset_snapshot_id=_classification_snapshot_id(cycle),
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
                PromotionGate.model_validate(item) for item in gate_container.get("gates", [])
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

    def record_dataset(
        self,
        cycle_id: str,
        request: ActiveLearningDatasetRecordRequest,
    ) -> ActiveLearningCycleResponse:
        if request.dataset_version_id:
            return super().record_dataset(cycle_id, request)
        snapshot_id = request.classification_dataset_snapshot_id
        if not snapshot_id:
            raise ValidationError("Classification active learning requires a dataset snapshot")
        cycle = self._cycle(cycle_id)
        self._ensure_open(cycle)
        if cycle.status != "review":
            raise ConflictError("A dataset can only be frozen after review")
        if cycle.reviewed_count < cycle.selected_count:
            raise ConflictError("Complete the selected review batch before freezing a dataset")
        snapshot = self.session.get(ClassificationDatasetSnapshot, snapshot_id)
        if snapshot is None or snapshot.project_id != cycle.project_id:
            raise ValidationError(
                "Classification dataset snapshot must belong to the cycle project"
            )
        if snapshot.status != "complete":
            raise ValidationError(
                "Only complete immutable classification snapshots can be attached"
            )
        cycle.dataset_version_id = None
        cycle.selection_result_json = {
            **dict(cycle.selection_result_json or {}),
            "classification_dataset_snapshot_id": snapshot.id,
            "classification_snapshot_manifest_sha256": snapshot.manifest_sha256,
            "classification_target_kind": snapshot.target_kind,
            "classification_label_set_id": snapshot.label_set_id,
            "classification_cardinality": snapshot.cardinality,
        }
        cycle.status = "dataset_frozen"
        cycle.history_json = [
            *list(cycle.history_json or []),
            _event(
                "classification_dataset_frozen",
                classification_dataset_snapshot_id=snapshot.id,
                snapshot_manifest_sha256=snapshot.manifest_sha256,
            ),
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
        snapshot_id = _classification_snapshot_id(cycle)
        if snapshot_id is None:
            return super().record_training(cycle_id, request)
        self._ensure_open(cycle)
        if cycle.status not in {"dataset_frozen", "training"}:
            raise ConflictError("Training can only be attached after freezing the dataset")
        run = self.session.get(TrainingRun, request.training_run_id)
        if run is None or run.project_id != cycle.project_id:
            raise ValidationError("Training run must belong to the cycle project")
        run_snapshot_id = str(
            dict(run.training_config_json or {}).get("classification_dataset_snapshot_id") or ""
        )
        if run_snapshot_id != snapshot_id:
            raise ValidationError(
                "Classification training run must use the cycle's frozen dataset snapshot"
            )
        if request.candidate_model_id:
            model = self.session.get(ModelRegistration, request.candidate_model_id)
            if model is None or model.project_id != cycle.project_id:
                raise ValidationError("Candidate model must belong to the cycle project")
            if model.id == cycle.source_model_id:
                raise ValidationError(
                    "The resulting model must remain distinct from the cycle source model"
                )
            if dict(model.metadata_json or {}).get("source_training_run_id") != run.id:
                raise ValidationError(
                    "Candidate model must be registered from the attached training run"
                )
            model_snapshot_id = str(
                dict(model.metadata_json or {}).get("classification_dataset_snapshot_id") or ""
            )
            if model_snapshot_id != snapshot_id:
                raise ValidationError(
                    "Candidate classifier lineage does not match the cycle dataset snapshot"
                )
        cycle.training_run_id = run.id
        cycle.candidate_model_id = request.candidate_model_id
        cycle.status = "training" if run.status not in {"completed", "succeeded"} else "evaluation"
        cycle.history_json = [
            *list(cycle.history_json or []),
            _event(
                "classification_training_attached",
                training_run_id=run.id,
                candidate_model_id=request.candidate_model_id,
                classification_dataset_snapshot_id=snapshot_id,
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
        snapshot_id = _classification_snapshot_id(cycle)
        if snapshot_id is None:
            return super().evaluate_and_promote(cycle_id, request)
        baseline_snapshot_id = request.baseline_classification_snapshot_id
        candidate_snapshot_id = request.candidate_classification_snapshot_id
        if not baseline_snapshot_id or not candidate_snapshot_id:
            raise ValidationError(
                "Classifier promotion requires immutable baseline and candidate evaluation "
                "snapshot ids"
            )
        if baseline_snapshot_id != candidate_snapshot_id:
            raise ValidationError(
                "Baseline and candidate classifiers must be evaluated on the same immutable "
                "classification snapshot before promotion"
            )
        evaluation_snapshot = self.session.get(
            ClassificationDatasetSnapshot,
            baseline_snapshot_id,
        )
        if (
            evaluation_snapshot is None
            or evaluation_snapshot.project_id != cycle.project_id
            or evaluation_snapshot.status != "complete"
        ):
            raise ValidationError(
                "Classification promotion evaluation snapshot must be complete and belong to "
                "the cycle project"
            )
        if request.baseline_dataset_version_id or request.candidate_dataset_version_id:
            raise ValidationError(
                "Classification promotion may not mix classification snapshots with detector "
                "dataset-version comparison ids"
            )
        response = super().evaluate_and_promote(cycle_id, request)
        return response.model_copy(
            update={
                "compatibility_warnings": [
                    *response.compatibility_warnings,
                    "Baseline and candidate classifier metrics were declared against the same "
                    "complete immutable classification snapshot.",
                ]
            }
        )
