"""Durable asynchronous scientific pose comparison submission."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, PoseTrainingDataset, Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.pose_evaluation import (
    PoseEvaluationComparisonCreateRequest,
    PoseEvaluationComparisonListResponse,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path

ACTIVE_STATUSES = ("queued", "running", "cancel_requested")
SUPPORTED_PROVIDERS = frozenset({"reefpose", "ultralytics", "sleap_nn"})


class PoseEvaluationComparisonService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    @staticmethod
    def _schema_identity(model: ModelRegistration) -> tuple[str, int, str]:
        metadata = dict(model.metadata_json or {})
        try:
            return (
                str(metadata["source_pose_schema_id"]),
                int(metadata["source_pose_schema_revision"]),
                str(metadata["source_pose_schema_content_hash"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(
                f"Pose model {model.display_name} lacks immutable landmark schema provenance"
            ) from exc

    @staticmethod
    def _check_leakage(model: ModelRegistration, dataset: PoseTrainingDataset) -> None:
        metadata = dict(model.metadata_json or {})
        forbidden_ids = {
            str(value)
            for value in (
                metadata.get("source_pose_training_dataset_id"),
                metadata.get("source_pose_validation_dataset_id"),
            )
            if value
        }
        forbidden_hashes = {
            str(value)
            for value in (
                metadata.get("source_pose_training_dataset_manifest_sha256"),
                metadata.get("source_pose_validation_dataset_manifest_sha256"),
            )
            if value
        }
        if dataset.id in forbidden_ids or dataset.manifest_sha256 in forbidden_hashes:
            raise ValidationError(
                f"Evaluation leakage detected for pose model {model.display_name}"
            )

    def _active_job(self, request_sha256: str) -> Job | None:
        return self.session.scalar(
            select(Job).where(
                Job.job_type == "pose_evaluation",
                Job.deduplication_key == request_sha256,
                Job.status.in_(ACTIVE_STATUSES),
            )
        )

    def submit(
        self,
        project_id: str,
        payload: PoseEvaluationComparisonCreateRequest,
    ) -> JobResponse:
        project = self.session.get(Project, project_id)
        dataset = self.session.get(PoseTrainingDataset, payload.evaluation_dataset_id)
        if project is None:
            raise NotFoundError("Project not found")
        if dataset is None:
            raise NotFoundError("Pose evaluation dataset not found")
        if dataset.project_id != project_id:
            raise ValidationError("Pose evaluation dataset belongs to another project")
        if dataset.status != "complete" or dataset.item_count < 1:
            raise ValidationError("Pose comparison requires a completed immutable dataset")

        models: list[ModelRegistration] = []
        model_identities: list[dict[str, Any]] = []
        dataset_identity = (
            dataset.pose_schema_id,
            dataset.pose_schema_revision,
            dataset.pose_schema_content_hash,
        )
        for model_id in payload.model_ids:
            model = self.session.get(ModelRegistration, model_id)
            if model is None:
                raise NotFoundError("Pose comparison model not found")
            if model.project_id != project_id:
                raise ValidationError("Pose comparison model belongs to another project")
            if model.purpose != "detector" or model.task != "pose":
                raise ValidationError("Pose comparison accepts only registered pose models")
            if model.provider_name not in SUPPORTED_PROVIDERS:
                raise ValidationError(
                    f"Pose comparison provider is unsupported: {model.provider_name}"
                )
            if self._schema_identity(model) != dataset_identity:
                raise ValidationError("Pose model and evaluation dataset schema identities differ")
            self._check_leakage(model, dataset)
            checkpoint_path = resolve_managed_project_path(self.settings, model.managed_path)
            checkpoint_sha, checkpoint_size = hash_model_file(checkpoint_path)
            if checkpoint_sha != model.sha256 or checkpoint_size != model.file_size_bytes:
                raise ValidationError(
                    f"Registered pose checkpoint integrity check failed: {model.display_name}"
                )
            models.append(model)
            model_identities.append(
                {
                    "model_id": model.id,
                    "checkpoint_sha256": checkpoint_sha,
                    "checkpoint_size_bytes": checkpoint_size,
                    "provider_name": model.provider_name,
                    "provider_version": model.provider_version,
                }
            )

        configuration = payload.model_dump(mode="json", exclude={"model_ids"})
        request_sha256 = canonical_json_sha256(
            {
                "schema_version": "pose-evaluation-comparison-request-0001",
                "project_id": project_id,
                "models": sorted(model_identities, key=lambda item: str(item["model_id"])),
                "dataset_id": dataset.id,
                "dataset_manifest_sha256": dataset.manifest_sha256,
                "configuration": configuration,
            }
        )
        active = self._active_job(request_sha256)
        if active is not None:
            return JobResponse.model_validate(active)

        job = Job(
            project_id=project_id,
            job_type="pose_evaluation",
            deduplication_key=request_sha256,
            status="queued",
            progress_current=0,
            progress_total=len(models) * dataset.item_count,
            request_json={
                "schema_version": "pose-evaluation-comparison-0001",
                "request_sha256": request_sha256,
                "model_ids": [model.id for model in models],
                "model_identities": model_identities,
                "evaluation_dataset_id": dataset.id,
                "dataset_manifest_sha256": dataset.manifest_sha256,
                **configuration,
            },
            result_json={"stage": "queued", "evaluation_run_ids": []},
        )
        self.session.add(job)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            active = self._active_job(request_sha256)
            if active is None:
                raise
            return JobResponse.model_validate(active)
        self.session.refresh(job)
        return JobResponse.model_validate(job)

    def list_for_project(
        self,
        project_id: str,
        *,
        limit: int,
        offset: int,
    ) -> PoseEvaluationComparisonListResponse:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        filters = (Job.project_id == project_id, Job.job_type == "pose_evaluation")
        total = int(self.session.scalar(select(func.count()).select_from(Job).where(*filters)) or 0)
        jobs = list(
            self.session.scalars(
                select(Job)
                .where(*filters)
                .order_by(Job.created_at.desc(), Job.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        return PoseEvaluationComparisonListResponse(
            items=[JobResponse.model_validate(job) for job in jobs],
            total=total,
            limit=limit,
            offset=offset,
        )
