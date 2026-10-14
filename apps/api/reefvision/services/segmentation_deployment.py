"""Explicit audited promotion and rollback for evaluated segmentation models.

Never called automatically by learning, inference, or training. The candidate
must have completed immutable mask evaluation before a human authorizes a
deployment. Segmentation activation never touches detector model metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import DatasetVersion, Job, ModelRegistration, Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.segmentation_promotion_policy import (
    SegmentationCandidateScore,
    candidate_meets_segmentation_guardrails,
)
from reefvision.services.segmentation_holdout import SegmentationHoldoutService
from reefvision.services.segmentation_learning_evaluation import (
    SegmentationLearningEvaluationService,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.learning_evaluation import verify_learning_content


class SegmentationDeploymentService:
    """Per-project, explicit deployment changes with persisted audit jobs."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _lock_project(self, project_id: str) -> None:
        # PostgreSQL takes a row lock; on SQLite flushing this UPDATE acquires
        # the writer lock before reading the active-model selection.
        project = self.session.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        if project is None:
            raise NotFoundError("Project not found")
        project.updated_at = datetime.now(UTC)
        self.session.flush()

    def _models(self, project_id: str) -> list[ModelRegistration]:
        return list(
            self.session.scalars(
                select(ModelRegistration).where(
                    ModelRegistration.project_id == project_id,
                    ModelRegistration.purpose == "segmenter",
                    ModelRegistration.task == "segment",
                )
            )
        )

    @staticmethod
    def _active(models: list[ModelRegistration]) -> ModelRegistration | None:
        active = [
            model
            for model in models
            if (model.metadata_json or {}).get("active_for_predictions") is True
        ]
        if len(active) > 1:
            raise ConflictError(
                "Multiple active segmenters detected; repair state before deployment"
            )
        return active[0] if active else None

    def _evaluation(self, project_id: str, evaluation_id: str) -> Job:
        record = self.session.get(Job, evaluation_id)
        if (
            record is None
            or record.project_id != project_id
            or record.job_type != "segmentation_learning_evaluation"
        ):
            raise NotFoundError("Project segmentation evaluation not found")
        result = record.result_json or {}
        request = record.request_json or {}
        if (
            record.status != "completed"
            or request.get("task") != "segment"
            or result.get("promotion_eligible") is not True
            or result.get("blockers")
            or not isinstance(result.get("candidate_metrics"), dict)
        ):
            raise ConflictError("Only completed eligible instance-mask evaluation can be promoted")
        version_id = request.get("dataset_version_id")
        if not isinstance(version_id, str):
            raise ValidationError("Segmentation evaluation lacks immutable dataset lineage")
        version = self.session.get(DatasetVersion, version_id)
        if (
            version is None
            or version.project_id != project_id
            or version.status != "complete"
            or request.get("manifest_sha256") != version.manifest_sha256
            or canonical_json_sha256(version.manifest_json) != version.manifest_sha256
        ):
            raise ConflictError("Evaluated immutable dataset was changed or removed")
        holdout = SegmentationHoldoutService(self.session, self.settings).prepare(
            project_id, version_id, split=str(request.get("split"))
        )
        if set(request.get("heldout_image_ids") or []) != set(holdout.image_ids):
            raise ConflictError("Evaluated holdout membership has changed")
        candidate_id = request.get("candidate_model_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValidationError("Segmentation evaluation lacks candidate model identity")
        validator = SegmentationLearningEvaluationService(self.session, self.settings)
        candidate = validator._model(
            project_id,
            candidate_id,
            version_id,
            holdout,
            same_dataset_required=True,
        )
        if request.get("candidate_checksum") != candidate.sha256:
            raise ConflictError("Evaluated candidate checkpoint checksum has changed")
        incumbent_id = request.get("incumbent_model_id")
        if incumbent_id is not None:
            if not isinstance(incumbent_id, str):
                raise ValidationError("Invalid incumbent model identity")
            incumbent = validator._model(
                project_id,
                incumbent_id,
                version_id,
                holdout,
                same_dataset_required=False,
            )
            if request.get("incumbent_checksum") != incumbent.sha256:
                raise ConflictError("Evaluated incumbent checkpoint checksum has changed")

        def make_score(model_id: str, metrics: dict[str, Any]) -> SegmentationCandidateScore:
            try:
                return SegmentationCandidateScore(
                    model_id=model_id,
                    project_id=project_id,
                    dataset_version_id=version_id,
                    split_digest=f"{version.manifest_sha256}:{request['split']}",
                    mask_map50=float(metrics["mask_map50"]),
                    mean_absolute_count_error=float(metrics["mean_absolute_count_error"]),
                    evaluated_images=len(holdout.image_ids),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError("Stored segmentation evaluation metrics are invalid") from exc

        previous_metrics = result.get("incumbent_metrics")
        if (incumbent_id is None) != (previous_metrics is None):
            raise ConflictError("Stored incumbent metrics do not match the evaluated model")
        try:
            eligible = candidate_meets_segmentation_guardrails(
                make_score(candidate_id, result["candidate_metrics"]),
                make_score(incumbent_id, previous_metrics)
                if isinstance(incumbent_id, str) and isinstance(previous_metrics, dict)
                else None,
                minimum_mask_map50=float(request["minimum_mask_map50"]),
                minimum_gain=float(request["minimum_gain"]),
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise ValidationError("Stored segmentation eligibility policy is invalid") from exc
        if not eligible:
            raise ConflictError("Stored mask metrics no longer meet promotion guardrails")
        return record

    def promote(
        self,
        project_id: str,
        evaluation_id: str,
        *,
        expected_active_model_id: str | None,
        approved_by: str,
        reason: str,
    ) -> Job:
        """Promote exactly one explicitly approved evaluation or fail closed."""
        if len(approved_by.strip()) < 2 or len(reason.strip()) < 10:
            raise ValidationError("Audited promotion needs operator identity and a reason")
        self._lock_project(project_id)
        evaluation = self._evaluation(project_id, evaluation_id)
        request = evaluation.request_json
        models = self._models(project_id)
        active = self._active(models)
        current_id = active.id if active is not None else None
        if current_id != expected_active_model_id:
            raise ConflictError("Active segmentation model changed; refresh deployment state")
        if request.get("incumbent_model_id") != current_id:
            raise ConflictError("Held-out comparison is not against the currently active segmenter")
        candidate_id = request["candidate_model_id"]
        if candidate_id == current_id:
            raise ConflictError("Candidate segmenter is already active")
        candidate = next((model for model in models if model.id == candidate_id), None)
        if candidate is None or candidate.sha256 != request.get("candidate_checksum"):
            raise ConflictError("Evaluated segmenter checkpoint is no longer registered")
        verify_learning_content(self.settings, candidate.managed_path, candidate.sha256)
        past = self.session.scalars(
            select(Job).where(
                Job.project_id == project_id,
                Job.job_type == "segmentation_learning_deployment",
            )
        )
        if any(row.request_json.get("evaluation_id") == evaluation_id for row in past):
            raise ConflictError("This segmentation evaluation has already been deployed")
        previous_pointer = (
            (active.metadata_json or {}).get("active_segmentation_deployment_id")
            if active is not None
            else None
        )
        now = datetime.now(UTC)
        audit = Job(
            project_id=project_id,
            job_type="segmentation_learning_deployment",
            status="succeeded",
            progress_current=1,
            progress_total=1,
            request_json={
                "task": "segment",
                "evaluation_id": evaluation_id,
                "candidate_model_id": candidate_id,
                "candidate_checksum": candidate.sha256,
                "previous_model_id": current_id,
                "previous_checksum": active.sha256 if active else None,
                "previous_deployment_id": previous_pointer,
                "expected_active_model_id": expected_active_model_id,
                "approved_by": approved_by.strip(),
                "reason": reason.strip(),
                "manifest_sha256": request["manifest_sha256"],
                "dataset_version_id": request["dataset_version_id"],
            },
            result_json={
                "active_model_id": candidate_id,
                "evaluation_metrics_sha256": canonical_json_sha256(evaluation.result_json or {}),
                "promotion_eligible": True,
            },
            started_at=now,
            completed_at=now,
        )
        self.session.add(audit)
        self.session.flush()
        for model in models:
            metadata = dict(model.metadata_json or {})
            metadata["active_for_predictions"] = model.id == candidate_id
            if model.id == candidate_id:
                metadata["promoted_by_segmentation_evaluation_id"] = evaluation_id
                metadata["active_segmentation_deployment_id"] = audit.id
            model.metadata_json = metadata
        self.session.commit()
        return audit

    def rollback(
        self,
        project_id: str,
        deployment_id: str,
        *,
        expected_active_model_id: str,
        approved_by: str,
        reason: str,
    ) -> Job:
        """Restore previous segmenter only if this deployment remains current."""
        if len(approved_by.strip()) < 2 or len(reason.strip()) < 10:
            raise ValidationError("Audited rollback needs operator identity and a reason")
        self._lock_project(project_id)
        deployment = self.session.get(Job, deployment_id)
        if (
            deployment is None
            or deployment.project_id != project_id
            or deployment.job_type != "segmentation_learning_deployment"
            or deployment.status != "succeeded"
        ):
            raise NotFoundError("Audited segmentation deployment not found")
        saved = deployment.request_json
        models = self._models(project_id)
        active = self._active(models)
        if (
            active is None
            or active.id != expected_active_model_id
            or active.id != saved.get("candidate_model_id")
            or active.sha256 != saved.get("candidate_checksum")
            or (active.metadata_json or {}).get("active_segmentation_deployment_id")
            != deployment_id
        ):
            raise ConflictError(
                "Deployment is no longer current; rollback would overwrite newer work"
            )
        verify_learning_content(self.settings, active.managed_path, active.sha256)
        previous_id = saved.get("previous_model_id")
        previous = next((model for model in models if model.id == previous_id), None)
        if previous_id is not None:
            if previous is None or previous.sha256 != saved.get("previous_checksum"):
                raise ConflictError(
                    "Previous segmenter checkpoint no longer matches rollback record"
                )
            verify_learning_content(self.settings, previous.managed_path, previous.sha256)
        now = datetime.now(UTC)
        audit = Job(
            project_id=project_id,
            job_type="segmentation_learning_deployment_rollback",
            status="succeeded",
            progress_current=1,
            progress_total=1,
            request_json={
                "task": "segment",
                "deployment_id": deployment_id,
                "expected_active_model_id": expected_active_model_id,
                "approved_by": approved_by.strip(),
                "reason": reason.strip(),
            },
            result_json={
                "restored_model_id": previous_id,
                "rolled_back_model_id": active.id,
                "previous_deployment_id": saved.get("previous_deployment_id"),
            },
            started_at=now,
            completed_at=now,
        )
        self.session.add(audit)
        for model in models:
            metadata = dict(model.metadata_json or {})
            metadata["active_for_predictions"] = previous_id is not None and model.id == previous_id
            if previous_id is not None and model.id == previous_id:
                old_pointer = saved.get("previous_deployment_id")
                if old_pointer:
                    metadata["active_segmentation_deployment_id"] = old_pointer
                else:
                    metadata.pop("active_segmentation_deployment_id", None)
            elif model.id == active.id:
                metadata.pop("active_segmentation_deployment_id", None)
            model.metadata_json = metadata
        self.session.commit()
        return audit
