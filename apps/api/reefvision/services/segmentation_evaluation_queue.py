"""Queue isolated segmenter inference on an immutable verified-mask holdout.

Polling advances a waiting parent only after ALL child inference jobs succeed.
No model is activated by this workflow; operator-approved promotion is separate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import DatasetVersion, Job
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.services.segmentation_holdout import SegmentationHoldoutService
from reefvision.services.segmentation_learning_evaluation import (
    SegmentationLearningEvaluationService,
)


class SegmentationEvaluationQueueService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.scoring = SegmentationLearningEvaluationService(session, settings)

    def queue(
        self,
        project_id: str,
        dataset_version_id: str,
        *,
        split: str,
        candidate_model_id: str,
        incumbent_model_id: str | None = None,
        minimum_images: int = 2,
        minimum_masks: int = 2,
        minimum_mask_map50: float = 0.5,
        minimum_gain: float = 0.0,
    ) -> Job:
        """Persist one waiting evaluation plus its isolated queued child jobs."""
        if incumbent_model_id is not None and incumbent_model_id == candidate_model_id:
            raise ValidationError("Candidate and incumbent must be different segmentation models")
        holdout = SegmentationHoldoutService(self.session, self.settings).prepare(
            project_id,
            dataset_version_id,
            split=split,
            minimum_images=minimum_images,
            minimum_masks=minimum_masks,
        )
        version = self.session.get(DatasetVersion, dataset_version_id)
        if version is None:
            raise NotFoundError("Immutable holdout dataset not found")
        candidate = self.scoring._model(
            project_id,
            candidate_model_id,
            dataset_version_id,
            holdout,
            same_dataset_required=True,
        )
        incumbent = (
            self.scoring._model(
                project_id,
                incumbent_model_id,
                dataset_version_id,
                holdout,
                same_dataset_required=False,
            )
            if incumbent_model_id is not None
            else None
        )
        now = datetime.now(UTC)
        images = list(holdout.image_ids)
        record = Job(
            project_id=project_id,
            job_type="segmentation_learning_evaluation",
            status="waiting",
            progress_current=0,
            progress_total=2 if incumbent is not None else 1,
            started_at=now,
            request_json={},
            result_json={
                "promotion_eligible": False,
                "blockers": ["Waiting for isolated held-out segmentation inference"],
            },
        )
        self.session.add(record)
        self.session.flush()

        def child(model_id: str) -> Job:
            return Job(
                project_id=project_id,
                job_type="inference",
                status="queued",
                progress_current=0,
                progress_total=len(images),
                request_json={
                    "model_id": model_id,
                    "model_task": "segment",
                    "image_ids": images,
                    "device": "auto",
                    "confidence_threshold": 0.001,
                    "iou_threshold": self.settings.inference_default_iou,
                    "evaluation_only": True,
                    "segmentation_holdout_parent_job_id": record.id,
                    "segmentation_dataset_version_id": dataset_version_id,
                    "segmentation_manifest_sha256": version.manifest_sha256,
                    "segmentation_split": split,
                },
            )

        candidate_job = child(candidate.id)
        self.session.add(candidate_job)
        incumbent_job = child(incumbent.id) if incumbent is not None else None
        if incumbent_job is not None:
            self.session.add(incumbent_job)
        self.session.flush()
        record.request_json = {
            "task": "segment",
            "dataset_version_id": dataset_version_id,
            "manifest_sha256": version.manifest_sha256,
            "split": split,
            "heldout_image_ids": images,
            "candidate_model_id": candidate.id,
            "candidate_checksum": candidate.sha256,
            "candidate_job_id": candidate_job.id,
            "incumbent_model_id": incumbent.id if incumbent is not None else None,
            "incumbent_checksum": incumbent.sha256 if incumbent is not None else None,
            "incumbent_job_id": incumbent_job.id if incumbent_job is not None else None,
            "minimum_images": minimum_images,
            "minimum_masks": minimum_masks,
            "minimum_mask_map50": minimum_mask_map50,
            "minimum_gain": minimum_gain,
        }
        self.session.commit()
        self.session.refresh(record)
        return record

    def advance(self, project_id: str, evaluation_id: str) -> Job:
        """Idempotently inspect children; persist final metrics on this same parent."""
        record = self.session.get(Job, evaluation_id)
        if (
            record is None
            or record.project_id != project_id
            or record.job_type != "segmentation_learning_evaluation"
        ):
            raise NotFoundError("Project segmentation evaluation queue not found")
        if record.status in {"completed", "failed"}:
            return record
        if record.status != "waiting":
            raise ConflictError("Unexpected segmentation evaluation parent job state")
        request = dict(record.request_json or {})
        if request.get("task") != "segment":
            raise ConflictError("Evaluation queue is missing segmentation task identity")
        child_ids = [request["candidate_job_id"]]
        if request.get("incumbent_job_id") is not None:
            child_ids.append(request["incumbent_job_id"])
        children = [self.session.get(Job, child_id) for child_id in child_ids]
        if any(child is None or child.project_id != project_id for child in children):
            raise ConflictError("Holdout inference job has been removed or reassigned")
        if any(
            child.request_json.get("evaluation_only") is not True
            or child.request_json.get("model_task") != "segment"
            or child.request_json.get("segmentation_holdout_parent_job_id") != record.id
            or child.request_json.get("segmentation_manifest_sha256")
            != request.get("manifest_sha256")
            or child.request_json.get("image_ids") != request.get("heldout_image_ids")
            for child in children
            if child is not None
        ):
            raise ConflictError("Holdout child inference job no longer matches the queued split")
        completed = sum(child.status == "succeeded" for child in children if child is not None)
        record.progress_current = completed
        if any(child.status in {"failed", "cancelled"} for child in children if child is not None):
            record.status = "failed"
            record.error_message = "At least one isolated holdout inference job failed"
            record.result_json = {
                "promotion_eligible": False,
                "blockers": [record.error_message],
            }
            record.completed_at = datetime.now(UTC)
            self.session.commit()
            return record
        if completed != len(children):
            self.session.commit()
            return record

        return self.scoring.record_completed_evaluation(
            project_id,
            request["dataset_version_id"],
            split=request["split"],
            candidate_model_id=request["candidate_model_id"],
            candidate_job_id=request["candidate_job_id"],
            incumbent_model_id=request.get("incumbent_model_id"),
            incumbent_job_id=request.get("incumbent_job_id"),
            minimum_images=request["minimum_images"],
            minimum_masks=request["minimum_masks"],
            minimum_mask_map50=request["minimum_mask_map50"],
            minimum_gain=request["minimum_gain"],
            existing_record=record,
        )
