"""Workflow-native classification dataset materialization and model training."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import ClassificationDataset, DatasetVersion, Job, ModelRegistration
from reefvision.domain.errors import ValidationError
from reefvision.jobs.classification_training import process_classification_training_job
from reefvision.schemas.classification import (
    ClassificationDatasetCreateRequest,
    ClassificationTrainingCreateRequest,
)
from reefvision.services.classification_datasets import ClassificationDatasetService
from reefvision.storage.projects import resolve_managed_project_path

ClassificationTrainingProcessor = Callable[[Settings, sessionmaker[Session], str], bool]


def materialize_workflow_classification_dataset(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    dataset_payload: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Materialize a normal immutable ReefVision classification dataset for a workflow."""

    if dataset_payload.get("project_id") != project_id:
        raise ValidationError("Classification Dataset received a version from another project")
    version_id = str(dataset_payload.get("dataset_version_id") or "")
    version = session.get(DatasetVersion, version_id)
    if version is None or version.project_id != project_id or version.status != "complete":
        raise ValidationError("Classification Dataset requires a complete dataset version")
    advertised_manifest = str(dataset_payload.get("manifest_sha256") or "")
    if advertised_manifest and advertised_manifest != version.manifest_sha256:
        raise ValidationError("Classification dataset source manifest no longer matches")

    request = ClassificationDatasetCreateRequest(
        dataset_version_id=version.id,
        mode=str(parameters.get("mode") or "image"),
        label_set=str(parameters.get("label_set") or "default"),
        minimum_crop_pixels=int(parameters.get("minimum_crop_pixels", 16)),
    )
    result = ClassificationDatasetService(session, settings).create_dataset(project_id, request)
    output_path = resolve_managed_project_path(settings, result.output_path)
    archive_path = resolve_managed_project_path(settings, result.archive_path)
    if not output_path.is_dir() or not archive_path.is_file():
        raise ValidationError("Classification dataset materialization is incomplete")
    return {
        "schema_version": "workflow-classification-dataset-0001",
        "project_id": project_id,
        "classification_dataset_id": result.id,
        "dataset_version_id": result.dataset_version_id,
        "dataset_manifest_sha256": version.manifest_sha256,
        "classification_manifest_sha256": result.manifest_sha256,
        "mode": result.mode,
        "label_set": result.label_set,
        "sample_count": result.sample_count,
        "output_path": result.output_path,
        "archive_path": result.archive_path,
        "created_by_workflow": True,
    }


def train_workflow_classifier(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    dataset_payload: dict[str, Any],
    parameters: dict[str, Any],
    processor: ClassificationTrainingProcessor = process_classification_training_job,
) -> dict[str, Any]:
    """Run the production classification trainer inline and return its registered model."""

    if dataset_payload.get("project_id") != project_id:
        raise ValidationError("Classification Training received a dataset from another project")
    dataset_id = str(dataset_payload.get("classification_dataset_id") or "")
    dataset = session.get(ClassificationDataset, dataset_id)
    if dataset is None or dataset.project_id != project_id or dataset.status != "complete":
        raise ValidationError("Classification Training requires a complete classification dataset")
    advertised_sha = str(dataset_payload.get("classification_manifest_sha256") or "")
    if advertised_sha and advertised_sha != dataset.manifest_sha256:
        raise ValidationError("Classification dataset manifest changed before training")
    dataset_root = resolve_managed_project_path(settings, dataset.output_path)
    if not dataset_root.is_dir():
        raise ValidationError("Classification training dataset directory is missing")

    request = ClassificationTrainingCreateRequest(
        classification_dataset_id=dataset.id,
        architecture=str(parameters.get("architecture") or "yolo11n-cls.pt"),
        run_name=str(parameters.get("run_name") or "classification"),
        epochs=int(parameters.get("epochs", 50)),
        image_size=int(parameters.get("image_size", 224)),
        batch=int(parameters.get("batch", 16)),
        device=str(parameters.get("device") or "auto"),
    )
    job = Job(
        project_id=project_id,
        job_type="classification_training",
        status="queued",
        progress_current=0,
        progress_total=request.epochs,
        request_json={**request.model_dump(mode="json"), "created_by_workflow": True},
        result_json={"stage": "queued", "created_by_workflow": True},
    )
    session.add(job)
    session.commit()
    job_id = job.id

    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    processed = processor(settings, factory, job_id)
    session.expire_all()
    completed = session.get(Job, job_id)
    if not processed or completed is None or completed.status != "succeeded":
        detail = completed.error_message if completed is not None else "job disappeared"
        raise ValidationError(f"Classification training child job failed: {detail}")
    model_id = str((completed.result_json or {}).get("model_id") or "")
    model = session.get(ModelRegistration, model_id)
    if (
        model is None
        or model.project_id != project_id
        or model.purpose != "classifier"
        or model.task != "classify"
    ):
        raise ValidationError("Classification training did not register a usable classifier")

    return {
        "schema_version": "workflow-model-reference-0001",
        "project_id": project_id,
        "model_id": model.id,
        "model_sha256": model.sha256,
        "purpose": model.purpose,
        "task": model.task,
        "provider_name": model.provider_name,
        "provider_version": model.provider_version,
        "framework": model.framework,
        "classification_dataset_id": dataset.id,
        "classification_manifest_sha256": dataset.manifest_sha256,
        "dataset_version_id": dataset.dataset_version_id,
        "classification_training_job_id": completed.id,
        "metrics": dict((completed.result_json or {}).get("metrics") or {}),
        "architecture": request.architecture,
        "run_name": request.run_name,
        "epochs": request.epochs,
        "image_size": request.image_size,
        "batch": request.batch,
        "device": request.device,
        "registered_from_workflow": True,
    }
