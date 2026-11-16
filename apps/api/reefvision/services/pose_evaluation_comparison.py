"""Durable asynchronous scientific pose comparison submission."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseLandmarkSchemaRevision,
    PoseModelSchemaBinding,
    PoseTrainingDataset,
    Project,
)
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

    def _schema_identity(self, model: ModelRegistration) -> tuple[str, int, str]:
        metadata = dict(model.metadata_json or {})
        binding = self.session.get(PoseModelSchemaBinding, model.id)
        if binding is not None:
            revision = self.session.scalar(
                select(PoseLandmarkSchemaRevision).where(
                    PoseLandmarkSchemaRevision.schema_id == binding.schema_id,
                    PoseLandmarkSchemaRevision.revision == binding.schema_revision,
                )
            )
            if revision is None:
                raise ValidationError("Pose model schema binding is invalid")
            raw_schema = metadata.get("pose_landmark_schema")
            if isinstance(raw_schema, dict) and (
                str(raw_schema.get("schema_id") or "") != binding.schema_id
                or int(raw_schema.get("schema_revision") or 0) != binding.schema_revision
                or str(raw_schema.get("content_hash") or "") != revision.content_hash
            ):
                raise ValidationError("Pose model schema metadata differs from its binding")
            return binding.schema_id, binding.schema_revision, revision.content_hash
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
        *,
        submission_context: dict[str, str] | None = None,
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
                    "pose_schema_id": dataset.pose_schema_id,
                    "pose_schema_revision": dataset.pose_schema_revision,
                    "pose_schema_content_hash": dataset.pose_schema_content_hash,
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
                "submission_context": submission_context or {},
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
                **(submission_context or {}),
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

    def get(self, job_id: str) -> JobResponse:
        job = self.session.get(Job, job_id)
        if job is None or job.job_type != "pose_evaluation":
            raise NotFoundError("Pose evaluation comparison not found")
        return JobResponse.model_validate(job)

    def export_json(self, job_id: str) -> dict[str, Any]:
        job = self.session.get(Job, job_id)
        if job is None or job.job_type != "pose_evaluation":
            raise NotFoundError("Pose evaluation comparison not found")
        return dict(job.result_json or {})

    def export_csv(self, job_id: str) -> str:
        report = self.export_json(job_id)
        stream = io.StringIO(newline="")
        fieldnames = [
            "row_type",
            "model_id",
            "provider_name",
            "display_name",
            "provider_version",
            "checkpoint_sha256",
            "dataset_manifest_sha256",
            "pose_schema_id",
            "pose_schema_revision",
            "pose_schema_content_hash",
            "configuration_json",
            "provenance_json",
            "warnings_json",
            "landmark_id",
            "metric",
            "value_json",
            "denominator_json",
            "available",
            "reason",
            "evaluation_run_id",
            "result_sha256",
            "report_sha256",
            "inference_latency_ms",
            "images_per_second",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for model in list(report.get("models") or []):
            if not isinstance(model, dict):
                continue
            metrics = dict(model.get("metrics") or {})
            availability_map = dict(model.get("metric_availability") or {})
            provenance = dict(model.get("provenance") or {})
            performance = dict(model.get("performance") or {})
            common = {
                "model_id": model.get("model_id"),
                "display_name": model.get("display_name"),
                "provider_name": model.get("provider_name"),
                "provider_version": model.get("provider_version"),
                "checkpoint_sha256": model.get("checkpoint_sha256"),
                "dataset_manifest_sha256": report.get("dataset_manifest_sha256"),
                "pose_schema_id": provenance.get("pose_schema_id"),
                "pose_schema_revision": provenance.get("pose_schema_revision"),
                "pose_schema_content_hash": provenance.get("pose_schema_content_hash"),
                "configuration_json": json.dumps(report.get("configuration") or {}, sort_keys=True),
                "provenance_json": json.dumps(provenance, sort_keys=True),
                "warnings_json": json.dumps(model.get("warnings") or [], sort_keys=True),
                "evaluation_run_id": model.get("evaluation_run_id"),
                "result_sha256": model.get("result_sha256"),
                "report_sha256": report.get("report_sha256"),
                "inference_latency_ms": performance.get("inference_latency_ms"),
                "images_per_second": performance.get("images_per_second"),
            }
            metric_values = {
                "euclidean_error": {
                    "mean": metrics.get("mean_euclidean_error"),
                    "median": metrics.get("median_euclidean_error"),
                },
                "nme": metrics.get("nme"),
                "pck": metrics.get("pck"),
                "visibility": metrics.get("visibility"),
                "calibration": metrics.get("calibration"),
                "oks": metrics.get("oks"),
                "normalized_error_distribution": metrics.get("normalized_error_distribution"),
            }
            denominators = {
                "visible_reference_count": metrics.get("visible_reference_count"),
                "matched_visible_count": metrics.get("matched_visible_count"),
                "instance_count": metrics.get("instance_count"),
                "oks_instance_count": metrics.get("oks_instance_count"),
            }
            for metric, value in metric_values.items():
                availability = availability_map.get(metric)
                available = (
                    availability.get("available")
                    if isinstance(availability, dict)
                    else value is not None
                )
                reason = availability.get("reason") if isinstance(availability, dict) else None
                writer.writerow(
                    {
                        **common,
                        "row_type": "aggregate",
                        "metric": metric,
                        "value_json": (
                            json.dumps(value, sort_keys=True) if value is not None else ""
                        ),
                        "denominator_json": json.dumps(denominators, sort_keys=True),
                        "available": available,
                        "reason": reason,
                    }
                )
            for landmark_id, values in sorted(dict(metrics.get("per_landmark") or {}).items()):
                writer.writerow(
                    {
                        **common,
                        "row_type": "landmark",
                        "landmark_id": landmark_id,
                        "metric": "metrics",
                        "value_json": json.dumps(values, sort_keys=True, separators=(",", ":")),
                        "available": True,
                    }
                )
            for warning in list(model.get("warnings") or []):
                writer.writerow(
                    {
                        **common,
                        "row_type": "warning",
                        "metric": "scientific_warning",
                        "available": False,
                        "reason": str(warning),
                    }
                )
        for exclusion in list(report.get("exclusions") or []):
            if not isinstance(exclusion, dict):
                continue
            writer.writerow(
                {
                    "row_type": "exclusion",
                    "model_id": exclusion.get("model_id"),
                    "provider_name": exclusion.get("provider_name"),
                    "metric": exclusion.get("code"),
                    "available": False,
                    "reason": exclusion.get("reason"),
                    "report_sha256": report.get("report_sha256"),
                }
            )
        for warning in list(report.get("warnings") or []):
            writer.writerow(
                {
                    "row_type": "warning",
                    "metric": "comparison_warning",
                    "available": False,
                    "reason": str(warning),
                    "warnings_json": json.dumps(report.get("warnings") or [], sort_keys=True),
                    "report_sha256": report.get("report_sha256"),
                }
            )
        return stream.getvalue()
