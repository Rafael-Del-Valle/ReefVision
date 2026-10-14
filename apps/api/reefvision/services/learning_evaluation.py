"""Held-out detector comparison and explicit, reversible model selection."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    Job,
    ModelRegistration,
    PredictionProposal,
    TrainingRun,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.learning_evaluation import DetectionMetrics, ScoredBox, detection_metrics
from reefvision.schemas.learning_evaluation import (
    LearningDeploymentResponse,
    LearningEvaluationRequest,
    LearningEvaluationResponse,
)
from reefvision.storage.learning_evaluation import verify_learning_content


def _now() -> datetime:
    return datetime.now(UTC)


class LearningEvaluationService:
    """Compare registered detectors on one immutable validation/test split."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    @staticmethod
    def _request(data: dict[str, Any]) -> LearningEvaluationRequest:
        return LearningEvaluationRequest.model_validate(
            {name: data[name] for name in LearningEvaluationRequest.model_fields if name in data}
        )

    def _model(self, project_id: str, model_id: str) -> ModelRegistration:
        model = self.session.get(ModelRegistration, model_id)
        if model is None or model.project_id != project_id or model.purpose != "detector":
            raise NotFoundError("Project detector model not found")
        if model.task != "detect":
            raise ValidationError("Learning evaluation currently supports detection models only")
        verify_learning_content(self.settings, model.managed_path, model.sha256)
        return model

    def _validate_lineage(
        self,
        project_id: str,
        model: ModelRegistration,
        dataset_version_id: str,
        heldout_items: list[DatasetVersionItem],
        *,
        require_same_dataset: bool,
    ) -> TrainingRun:
        run_id = (model.metadata_json or {}).get("source_training_run_id")
        if not isinstance(run_id, str):
            raise ValidationError(
                f"Model {model.display_name} has unknown training lineage; "
                "held-out evaluation is unsafe"
            )
        run = self.session.get(TrainingRun, run_id)
        if (
            run is None
            or run.project_id != project_id
            or run.status != "completed"
            or run.task != "detect"
        ):
            raise ValidationError(f"Model {model.display_name} has invalid training lineage")
        if require_same_dataset and run.dataset_version_id != dataset_version_id:
            raise ValidationError(
                "Candidate and held-out evaluation must reference the same "
                "immutable dataset version"
            )
        source_version = self.session.get(DatasetVersion, run.dataset_version_id)
        if source_version is None or source_version.project_id != project_id:
            raise ValidationError(f"Model {model.display_name} has invalid dataset lineage")
        training_items = list(
            self.session.scalars(
                select(DatasetVersionItem).where(
                    DatasetVersionItem.dataset_version_id == source_version.id,
                    DatasetVersionItem.split == "train",
                )
            )
        )
        training_groups = {item.group_key or f"image:{item.image_id}" for item in training_items}
        heldout_groups = {item.group_key or f"image:{item.image_id}" for item in heldout_items}
        overlap = training_groups & heldout_groups
        if overlap:
            raise ValidationError(
                f"Model {model.display_name} trained on {len(overlap)} held-out group(s); "
                "evaluation would leak training data"
            )
        return run

    def _items(
        self, project_id: str, payload: LearningEvaluationRequest
    ) -> list[DatasetVersionItem]:
        version = self.session.get(DatasetVersion, payload.dataset_version_id)
        if version is None or version.project_id != project_id:
            raise NotFoundError("Dataset version not found in this project")
        items = list(
            self.session.scalars(
                select(DatasetVersionItem)
                .where(
                    DatasetVersionItem.dataset_version_id == version.id,
                    DatasetVersionItem.split == payload.split,
                )
                .order_by(DatasetVersionItem.image_id)
            )
        )
        if len(items) < payload.minimum_images:
            raise ValidationError(
                f"Held-out split needs at least {payload.minimum_images} images; found {len(items)}"
            )
        counts: dict[str, int] = {}
        for item in items:
            for annotation in item.annotation_snapshot_json:
                class_id = str(annotation.get("label_class_id") or "")
                counts[class_id] = counts.get(class_id, 0) + 1
        sparse = [
            class_id
            for class_id, count in counts.items()
            if count < payload.minimum_objects_per_class
        ]
        if not counts or sparse:
            raise ValidationError(
                "Every evaluated class needs the configured minimum held-out verified objects"
            )
        # Snapshot creation guarantees group-level split assignment; verify persisted data too.
        all_items = list(
            self.session.scalars(
                select(DatasetVersionItem).where(
                    DatasetVersionItem.dataset_version_id == version.id
                )
            )
        )
        split_by_group: dict[str, str] = {}
        for item in all_items:
            if not item.group_key:
                continue
            previous = split_by_group.setdefault(item.group_key, item.split)
            if previous != item.split:
                raise ValidationError("Dataset snapshot contains train/validation group leakage")
        return items

    def _inference_job(
        self, project_id: str, model: ModelRegistration, image_ids: list[str]
    ) -> Job:
        return Job(
            project_id=project_id,
            job_type="inference",
            status="queued",
            progress_current=0,
            progress_total=len(image_ids),
            request_json={
                "model_id": model.id,
                "image_ids": image_ids,
                "device": "auto",
                "confidence_threshold": 0.001,
                "iou_threshold": self.settings.inference_default_iou,
                "evaluation_only": True,
            },
        )

    def create(
        self, project_id: str, payload: LearningEvaluationRequest
    ) -> LearningEvaluationResponse:
        items = self._items(project_id, payload)
        candidate = self._model(project_id, payload.candidate_model_id)
        self._validate_lineage(
            project_id,
            candidate,
            payload.dataset_version_id,
            items,
            require_same_dataset=True,
        )
        incumbent = None
        if payload.incumbent_model_id:
            incumbent = self._model(project_id, payload.incumbent_model_id)
            self._validate_lineage(
                project_id,
                incumbent,
                payload.dataset_version_id,
                items,
                require_same_dataset=False,
            )
        image_ids = [item.image_id for item in items]
        candidate_job = self._inference_job(project_id, candidate, image_ids)
        incumbent_job = self._inference_job(project_id, incumbent, image_ids) if incumbent else None
        self.session.add(candidate_job)
        if incumbent_job:
            self.session.add(incumbent_job)
        self.session.flush()
        evaluation = Job(
            project_id=project_id,
            job_type="learning_evaluation",
            status="waiting",
            progress_total=2 if incumbent else 1,
            request_json={
                **payload.model_dump(mode="json"),
                "candidate_job_id": candidate_job.id,
                "incumbent_job_id": incumbent_job.id if incumbent_job else None,
                "image_ids": image_ids,
            },
            result_json={"blockers": ["Waiting for held-out inference to finish"]},
        )
        self.session.add(evaluation)
        self.session.commit()
        return self._response(evaluation)

    def _truth(self, evaluation: Job) -> list[ScoredBox]:
        payload = self._request(evaluation.request_json)
        items = self._items(str(evaluation.project_id), payload)
        truth: list[ScoredBox] = []
        for item in items:
            for annotation in item.annotation_snapshot_json:
                truth.append(
                    ScoredBox(
                        item.image_id,
                        str(annotation["label_class_id"]),
                        1.0,
                        (
                            float(annotation["x_min"]),
                            float(annotation["y_min"]),
                            float(annotation["x_max"]),
                            float(annotation["y_max"]),
                        ),
                    )
                )
        return truth

    def _predictions(self, job_id: str) -> list[ScoredBox]:
        proposals = self.session.scalars(
            select(PredictionProposal).where(PredictionProposal.inference_job_id == job_id)
        )
        result: list[ScoredBox] = []
        for proposal in proposals:
            if proposal.label_class_id is None:
                raise ValidationError(
                    "Evaluation predictions must map every detector class to a stable project class"
                )
            result.append(
                ScoredBox(
                    proposal.image_id,
                    proposal.label_class_id,
                    proposal.confidence,
                    (proposal.x_min, proposal.y_min, proposal.x_max, proposal.y_max),
                )
            )
        return result

    def _metric(self, job_id: str, truth: list[ScoredBox], image_count: int) -> DetectionMetrics:
        return detection_metrics(truth, self._predictions(job_id), image_count=image_count)

    def _finalize(self, evaluation: Job) -> None:
        request = self._request(evaluation.request_json)
        candidate_job = self.session.get(Job, evaluation.request_json["candidate_job_id"])
        incumbent_id = evaluation.request_json.get("incumbent_job_id")
        incumbent_job = self.session.get(Job, incumbent_id) if incumbent_id else None
        children = [item for item in (candidate_job, incumbent_job) if item is not None]
        failed = [item for item in children if item.status in {"failed", "cancelled"}]
        if failed:
            evaluation.status = "failed"
            evaluation.error_message = failed[0].error_message or "Held-out inference failed"
            evaluation.completed_at = _now()
            evaluation.result_json = {"blockers": [evaluation.error_message]}
            self.session.commit()
            return
        if not children or any(item.status != "succeeded" for item in children):
            return
        assert candidate_job is not None
        truth = self._truth(evaluation)
        image_count = len(evaluation.request_json["image_ids"])
        candidate = self._metric(str(candidate_job.id), truth, image_count)
        incumbent = (
            self._metric(str(incumbent_job.id), truth, image_count) if incumbent_job else None
        )
        blockers: list[str] = []
        if candidate.map50 < request.minimum_ap50:
            blockers.append(
                f"Candidate AP50 {candidate.map50:.3f} is below {request.minimum_ap50:.3f}"
            )
        if candidate.precision < request.minimum_precision:
            blockers.append(
                f"Candidate precision {candidate.precision:.3f} is below "
                f"{request.minimum_precision:.3f}"
            )
        if candidate.recall < request.minimum_recall:
            blockers.append(
                f"Candidate recall {candidate.recall:.3f} is below {request.minimum_recall:.3f}"
            )
        if incumbent and candidate.map50 < incumbent.map50 + request.minimum_ap50_gain:
            blockers.append("Candidate does not meet the configured AP50 gain over the incumbent")
        if incumbent and candidate.mean_absolute_count_error > incumbent.mean_absolute_count_error:
            blockers.append("Candidate count error is worse than the incumbent")
        evaluation.status = "completed"
        evaluation.progress_current = evaluation.progress_total
        evaluation.completed_at = _now()
        evaluation.result_json = {
            "candidate_metrics": asdict(candidate),
            "incumbent_metrics": asdict(incumbent) if incumbent else None,
            "promotion_eligible": not blockers,
            "blockers": blockers,
        }
        self.session.commit()

    def _response(self, evaluation: Job) -> LearningEvaluationResponse:
        result = dict(evaluation.result_json or {})
        return LearningEvaluationResponse(
            id=evaluation.id,
            status=evaluation.status,
            candidate_job_id=str(evaluation.request_json["candidate_job_id"]),
            incumbent_job_id=evaluation.request_json.get("incumbent_job_id"),
            candidate_metrics=result.get("candidate_metrics"),
            incumbent_metrics=result.get("incumbent_metrics"),
            promotion_eligible=bool(result.get("promotion_eligible")),
            blockers=list(result.get("blockers") or []),
        )

    def get(self, project_id: str, evaluation_id: str) -> LearningEvaluationResponse:
        evaluation = self.session.get(Job, evaluation_id)
        if (
            evaluation is None
            or evaluation.project_id != project_id
            or evaluation.job_type != "learning_evaluation"
        ):
            raise NotFoundError("Learning evaluation not found")
        if evaluation.status == "waiting":
            self._finalize(evaluation)
            self.session.refresh(evaluation)
        return self._response(evaluation)

    def active_model_id(self, project_id: str) -> str | None:
        models = self.session.scalars(
            select(ModelRegistration).where(
                ModelRegistration.project_id == project_id,
                ModelRegistration.purpose == "detector",
            )
        )
        return next(
            (
                model.id
                for model in models
                if (model.metadata_json or {}).get("active_for_predictions")
            ),
            None,
        )

    def promote(self, project_id: str, evaluation_id: str) -> LearningDeploymentResponse:
        evaluation_response = self.get(project_id, evaluation_id)
        if evaluation_response.status != "completed" or not evaluation_response.promotion_eligible:
            raise ConflictError("Only a completed, eligible evaluation can be promoted")
        evaluation = self.session.get(Job, evaluation_id)
        assert evaluation is not None
        candidate_id = str(evaluation.request_json["candidate_model_id"])
        previous_id = self.active_model_id(project_id)
        for model in self.session.scalars(
            select(ModelRegistration).where(
                ModelRegistration.project_id == project_id,
                ModelRegistration.purpose == "detector",
            )
        ):
            metadata = dict(model.metadata_json or {})
            metadata["active_for_predictions"] = model.id == candidate_id
            if model.id == candidate_id:
                metadata["promoted_by_evaluation_id"] = evaluation_id
            model.metadata_json = metadata
        deployment = Job(
            project_id=project_id,
            job_type="learning_deployment",
            status="succeeded",
            progress_current=1,
            progress_total=1,
            request_json={
                "active_model_id": candidate_id,
                "previous_model_id": previous_id,
                "evaluation_id": evaluation_id,
            },
            result_json={"active_model_id": candidate_id},
            started_at=_now(),
            completed_at=_now(),
        )
        self.session.add(deployment)
        self.session.commit()
        return LearningDeploymentResponse(
            id=deployment.id,
            active_model_id=candidate_id,
            previous_model_id=previous_id,
            evaluation_id=evaluation_id,
        )

    def rollback(self, project_id: str, deployment_id: str) -> LearningDeploymentResponse:
        deployment = self.session.get(Job, deployment_id)
        if (
            deployment is None
            or deployment.project_id != project_id
            or deployment.job_type != "learning_deployment"
        ):
            raise NotFoundError("Learning deployment not found")
        if self.active_model_id(project_id) != deployment.request_json.get("active_model_id"):
            raise ConflictError("A later model selection prevents rollback of this deployment")
        previous_id = deployment.request_json.get("previous_model_id")
        for model in self.session.scalars(
            select(ModelRegistration).where(
                ModelRegistration.project_id == project_id,
                ModelRegistration.purpose == "detector",
            )
        ):
            metadata = dict(model.metadata_json or {})
            metadata["active_for_predictions"] = model.id == previous_id
            model.metadata_json = metadata
        rollback = Job(
            project_id=project_id,
            job_type="learning_deployment_rollback",
            status="succeeded",
            progress_current=1,
            progress_total=1,
            request_json={"deployment_id": deployment.id},
            result_json={"active_model_id": previous_id},
            started_at=_now(),
            completed_at=_now(),
        )
        self.session.add(rollback)
        self.session.commit()
        return LearningDeploymentResponse(
            id=rollback.id,
            active_model_id=previous_id,
            previous_model_id=deployment.request_json.get("active_model_id"),
            evaluation_id=deployment.request_json.get("evaluation_id"),
        )
