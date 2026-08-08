"""Background classification training and automatic model registration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import ClassificationDataset, Job, ModelRegistration, Project
from reefvision.ml.classification import classification_provider_for_name
from reefvision.storage.models import copy_model_file
from reefvision.storage.projects import resolve_managed_project_path


def _fail(factory: sessionmaker[Session], job_id: str, message: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = datetime.now(UTC)
        session.commit()


def _class_map(dataset: ClassificationDataset) -> dict[str, object]:
    classes: dict[str, dict[str, object]] = {}
    folders = dataset.manifest_json.get("class_folders", {})
    if isinstance(folders, dict):
        for folder, metadata in folders.items():
            if isinstance(metadata, dict):
                classes[str(folder)] = {
                    "label_class_id": str(metadata.get("label_class_id", "")),
                    "class_index": int(metadata.get("class_index", 0)),
                    "class_name": str(metadata.get("class_name", folder)),
                }
    return {"label_set": dataset.label_set, "provider_classes": classes}


def process_classification_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "classification_training" or job.status != "queued":
            return False
        request = dict(job.request_json)
        dataset = session.get(
            ClassificationDataset,
            str(request.get("classification_dataset_id", "")),
        )
        if dataset is None:
            job.status = "failed"
            job.error_message = "Classification dataset not found"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        project = session.get(Project, dataset.project_id)
        if project is None:
            job.status = "failed"
            job.error_message = "Classification project not found"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        session.commit()
        dataset_path = dataset.output_path
        dataset_manifest_sha256 = dataset.manifest_sha256
        project_storage_root = project.storage_root
        project_id = project.id
        class_map = _class_map(dataset)

    try:
        provider = classification_provider_for_name("ultralytics")
        dataset_root = resolve_managed_project_path(settings, dataset_path)
        run_relative = f"{project_storage_root}/classification/runs/{job_id}"
        run_root = resolve_managed_project_path(settings, run_relative)
        result = provider.train(
            dataset_root,
            run_root,
            architecture=str(request.get("architecture", "yolo11n-cls.pt")),
            epochs=max(1, int(request.get("epochs", 50))),
            image_size=max(32, int(request.get("image_size", 224))),
            batch=max(1, int(request.get("batch", 16))),
            device=str(request.get("device", "auto")),
        )
        model_id = str(uuid4())
        managed_relative = f"{project_storage_root}/models/{model_id}.pt"
        managed_path = resolve_managed_project_path(settings, managed_relative)
        checksum, size = copy_model_file(result.checkpoint_path, managed_path)
        run_name = str(request.get("run_name", "classification")).strip() or "classification"
        display_name = f"{run_name}-{job_id[:8]}"

        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                managed_path.unlink(missing_ok=True)
                raise RuntimeError("Classification training job disappeared")
            registration = ModelRegistration(
                id=model_id,
                project_id=project_id,
                purpose="classifier",
                display_name=display_name,
                source_filename=result.checkpoint_path.name,
                managed_path=managed_relative,
                sha256=checksum,
                file_size_bytes=size,
                framework="ultralytics",
                task="classify",
                provider_name=provider.provider_id,
                provider_version=result.provider_version,
                class_map_json=class_map,
                input_size_json={
                    "width": int(request.get("image_size", 224)),
                    "height": int(request.get("image_size", 224)),
                },
                metadata_json={
                    "classification_dataset_id": str(request["classification_dataset_id"]),
                    "dataset_manifest_sha256": dataset_manifest_sha256,
                    "training_metrics": result.metrics,
                    "architecture": str(request.get("architecture", "yolo11n-cls.pt")),
                },
                notes="Automatically registered from ReefVision classification training",
            )
            session.add(registration)
            job.status = "succeeded"
            job.progress_current = max(1, int(request.get("epochs", 50)))
            job.progress_total = max(1, int(request.get("epochs", 50)))
            job.result_json = {
                "model_id": model_id,
                "checkpoint_path": managed_relative,
                "run_path": run_relative,
                "metrics": result.metrics,
                "provider_version": result.provider_version,
            }
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        _fail(factory, job_id, str(exc))
        return False
