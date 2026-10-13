"""Persist immutable, read-only segmentation candidate evaluation evidence.

This service accepts only completed, segregated segmentation inference jobs,
verified held-out mask snapshots, and matching training lineage. It NEVER
promotes a model. Deployment requires a separate audited task-specific action.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

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
from reefvision.domain.segmentation_holdout import SegmentationHoldout
from reefvision.domain.segmentation_promotion_policy import (
    SegmentationCandidateScore,
    candidate_meets_segmentation_guardrails,
)
from reefvision.services.segmentation_holdout import SegmentationHoldoutService
from reefvision.services.segmentation_scoring import (
    ScoredSegmentationHoldout,
    score_segmentation_holdout,
)
from reefvision.storage.learning_evaluation import verify_learning_content
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.segmentation_metric_masks import MAX_MASK_PNG_BYTES


class SegmentationLearningEvaluationService:
    """Evaluate one or two registered segmenters without activating either."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _model(
        self,
        project_id: str,
        model_id: str,
        dataset_version_id: str,
        holdout: SegmentationHoldout,
        *,
        same_dataset_required: bool,
    ) -> ModelRegistration:
        model = self.session.get(ModelRegistration, model_id)
        if (
            model is None
            or model.project_id != project_id
            or model.purpose != "segmenter"
            or model.task != "segment"
        ):
            raise NotFoundError("Registered project segmentation model not found")
        verify_learning_content(self.settings, model.managed_path, model.sha256)
        run_id = (model.metadata_json or {}).get("source_training_run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValidationError("Segmentation model is missing verified training lineage")
        run = self.session.get(TrainingRun, run_id)
        if (
            run is None
            or run.project_id != project_id
            or run.status != "completed"
            or run.task != "segment"
            or not run.dataset_version_id
        ):
            raise ValidationError("Registered segmenter lacks a completed segment training run")
        if same_dataset_required and run.dataset_version_id != dataset_version_id:
            raise ValidationError("Candidate must use the held-out immutable dataset version")
        source = self.session.get(DatasetVersion, run.dataset_version_id)
        if (
            source is None
            or source.project_id != project_id
            or source.status != "complete"
            or run.dataset_manifest_sha256 != source.manifest_sha256
        ):
            raise ValidationError("Segmenter training dataset lineage is missing or changed")
        trained = self.session.scalars(
            select(DatasetVersionItem).where(
                DatasetVersionItem.dataset_version_id == source.id,
                DatasetVersionItem.split == "train",
            )
        )
        training_groups = {item.group_key or f"image:{item.image_id}" for item in trained}
        if training_groups.intersection(holdout.group_ids):
            raise ValidationError("Segmentation candidate trained on held-out image groups")
        return model

    def _job(
        self,
        project_id: str,
        model_id: str,
        inference_job_id: str,
        holdout: SegmentationHoldout,
    ) -> Job:
        job = self.session.get(Job, inference_job_id)
        if job is None or job.project_id != project_id or job.job_type != "inference":
            raise NotFoundError("Project segmentation inference job not found")
        request = job.request_json or {}
        images = request.get("image_ids")
        if (
            job.status != "succeeded"
            or request.get("model_id") != model_id
            or request.get("model_task") != "segment"
            or request.get("evaluation_only") is not True
            or not isinstance(images, list)
            or len(images) != len(holdout.image_ids)
            or set(images) != set(holdout.image_ids)
            or job.progress_total != len(images)
            or job.progress_current != job.progress_total
        ):
            raise ConflictError("Only completed isolated holdout segmentation jobs can be scored")
        return job

    def _managed_raster_bytes(self, relative_path: str) -> bytes:
        try:
            path = resolve_managed_project_path(self.settings, relative_path)
            if not path.is_file() or path.stat().st_size > MAX_MASK_PNG_BYTES:
                raise ValidationError("Evaluation raster content is absent or too large")
            return path.read_bytes()
        except OSError as exc:
            raise ValidationError("Evaluation raster content cannot be read") from exc

    def _score_model(
        self,
        project_id: str,
        dataset_version: DatasetVersion,
        holdout: SegmentationHoldout,
        snapshot_items: list[DatasetVersionItem],
        known_class_ids: set[str],
        model_id: str,
        inference_job_id: str,
        *,
        require_same_dataset: bool,
    ) -> ScoredSegmentationHoldout:
        model = self._model(
            project_id,
            model_id,
            dataset_version.id,
            holdout,
            same_dataset_required=require_same_dataset,
        )
        job = self._job(project_id, model.id, inference_job_id, holdout)
        proposals = list(
            self.session.scalars(
                select(PredictionProposal).where(PredictionProposal.inference_job_id == job.id)
            )
        )
        if any(item.project_id != project_id for item in proposals):
            raise ValidationError("Evaluation inference contains cross-project proposals")
        try:
            return score_segmentation_holdout(
                holdout=holdout,
                snapshot_items=snapshot_items,
                proposals=proposals,
                dataset_version_id=dataset_version.id,
                manifest_sha256=dataset_version.manifest_sha256,
                inference_job_id=job.id,
                candidate_model_id=model.id,
                checkpoint_sha256=model.sha256,
                known_class_ids=known_class_ids,
                inference_succeeded=True,
                read_managed_raster=self._managed_raster_bytes,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def record_completed_evaluation(
        self,
        project_id: str,
        dataset_version_id: str,
        *,
        split: str,
        candidate_model_id: str,
        candidate_job_id: str,
        incumbent_model_id: str | None = None,
        incumbent_job_id: str | None = None,
        minimum_images: int = 1,
        minimum_masks: int = 1,
        minimum_mask_map50: float = 0.5,
        minimum_gain: float = 0.0,
        existing_record: Job | None = None,
    ) -> Job:
        """Store a completed holdout comparison; never implicitly promote."""
        if bool(incumbent_model_id) != bool(incumbent_job_id):
            raise ValidationError("Incumbent segmentation model and job must be supplied together")
        if existing_record is not None:
            original = existing_record.request_json or {}
            if (
                existing_record.project_id != project_id
                or existing_record.job_type != "segmentation_learning_evaluation"
                or existing_record.status != "waiting"
                or original.get("task") != "segment"
                or original.get("dataset_version_id") != dataset_version_id
                or original.get("split") != split
                or original.get("candidate_model_id") != candidate_model_id
                or original.get("candidate_job_id") != candidate_job_id
                or original.get("incumbent_model_id") != incumbent_model_id
                or original.get("incumbent_job_id") != incumbent_job_id
                or original.get("minimum_images") != minimum_images
                or original.get("minimum_masks") != minimum_masks
                or original.get("minimum_mask_map50") != minimum_mask_map50
                or original.get("minimum_gain") != minimum_gain
            ):
                raise ConflictError("Queued segmentation evaluation request has changed")

        holdout = SegmentationHoldoutService(self.session, self.settings).prepare(
            project_id,
            dataset_version_id,
            split=split,
            minimum_images=minimum_images,
            minimum_masks=minimum_masks,
        )
        version = self.session.get(DatasetVersion, dataset_version_id)
        assert version is not None
        snapshot_items = list(
            self.session.scalars(
                select(DatasetVersionItem).where(
                    DatasetVersionItem.dataset_version_id == dataset_version_id,
                    DatasetVersionItem.split == split,
                )
            )
        )
        class_ids = {
            entry["id"]
            for entry in version.class_map_json
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
        candidate = self._score_model(
            project_id,
            version,
            holdout,
            snapshot_items,
            class_ids,
            candidate_model_id,
            candidate_job_id,
            require_same_dataset=True,
        )
        incumbent = (
            self._score_model(
                project_id,
                version,
                holdout,
                snapshot_items,
                class_ids,
                incumbent_model_id,
                incumbent_job_id,
                require_same_dataset=False,
            )
            if incumbent_model_id is not None and incumbent_job_id is not None
            else None
        )
        split_digest = f"{version.manifest_sha256}:{split}"

        def policy_score(result: ScoredSegmentationHoldout) -> SegmentationCandidateScore:
            return SegmentationCandidateScore(
                model_id=result.model_id,
                project_id=project_id,
                dataset_version_id=dataset_version_id,
                split_digest=split_digest,
                mask_map50=result.metrics.mask_map50,
                mean_absolute_count_error=result.metrics.mean_absolute_count_error,
                evaluated_images=len(holdout.image_ids),
            )

        try:
            eligible = candidate_meets_segmentation_guardrails(
                policy_score(candidate),
                policy_score(incumbent) if incumbent is not None else None,
                minimum_mask_map50=minimum_mask_map50,
                minimum_gain=minimum_gain,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        blockers: list[str] = []
        if not eligible:
            blockers.append("Candidate does not meet the held-out mask AP50 or count-error policy")
        now = datetime.now(UTC)
        record = existing_record or Job(
            project_id=project_id,
            job_type="segmentation_learning_evaluation",
        )
        record.status = "completed"
        record.progress_current = 2 if incumbent is not None else 1
        record.progress_total = record.progress_current
        record.started_at = record.started_at or now
        record.completed_at = now
        record.request_json = {
            "task": "segment",
            "dataset_version_id": dataset_version_id,
            "manifest_sha256": version.manifest_sha256,
            "split": split,
            "heldout_image_ids": list(holdout.image_ids),
            "candidate_model_id": candidate.model_id,
            "candidate_job_id": candidate.job_id,
            "candidate_checksum": candidate.checkpoint_sha256,
            "incumbent_model_id": incumbent.model_id if incumbent else None,
            "incumbent_job_id": incumbent.job_id if incumbent else None,
            "incumbent_checksum": incumbent.checkpoint_sha256 if incumbent else None,
            "minimum_images": minimum_images,
            "minimum_masks": minimum_masks,
            "minimum_mask_map50": minimum_mask_map50,
            "minimum_gain": minimum_gain,
        }
        record.result_json = {
            "candidate_metrics": asdict(candidate.metrics),
            "incumbent_metrics": asdict(incumbent.metrics) if incumbent else None,
            "promotion_eligible": eligible,
            "blockers": blockers,
            "scientific_method": "source-pixel instance mask AP50, not detector box AP",
        }
        self.session.add(record)
        self.session.commit()
        return record
