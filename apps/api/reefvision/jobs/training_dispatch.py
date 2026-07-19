"""Task-aware training worker dispatch."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, TrainingRun
from reefvision.jobs.advanced_ultralytics_training import (
    _execute_tuning,
    _execute_validation,
)
from reefvision.jobs.classification_training import process_classification_training_job
from reefvision.jobs.segmentation_training import process_segmentation_training_job
from reefvision.jobs.semantic_training import process_semantic_training_job
from reefvision.jobs.training import _append_log, process_training_job
from reefvision.ml.classification import CLASSIFICATION_TASK
from reefvision.ml.semantic_segmentation import SEMANTIC_SEGMENTATION_TASK
from reefvision.ml.ultralytics_tuning import normalize_tuning_config
from reefvision.storage.projects import resolve_managed_project_path


def _restore_tuning_provenance(
    factory: sessionmaker[Session],
    run_id: str,
    requested_tuning: dict[str, Any],
    tuning_artifact: object,
) -> None:
    if requested_tuning["mode"] == "disabled":
        return
    with factory() as session:
        run = session.get(TrainingRun, run_id)
        if run is None:
            return
        run.tuning_config_json = requested_tuning
        manifest = dict(run.artifact_manifest_json or {})
        if tuning_artifact is not None:
            manifest["tuning"] = tuning_artifact
        run.artifact_manifest_json = manifest
        session.commit()


def _process_ultralytics_training(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
    run_id: str,
    task: str,
) -> bool:
    with factory() as session:
        run = session.get(TrainingRun, run_id)
        if run is None:
            return False
        requested_tuning = normalize_tuning_config(
            getattr(run, "tuning_config_json", None)
        )

    tuning_artifact = None
    if requested_tuning["mode"] != "disabled":
        _execute_tuning(settings, factory, job_id, run_id)
        with factory() as session:
            run = session.get(TrainingRun, run_id)
            if run is None:
                return False
            manifest = dict(getattr(run, "artifact_manifest_json", None) or {})
            tuning_artifact = manifest.get("tuning")
            # The stable task workers deliberately reject unexecuted tuning. Mark it
            # disabled only for their final-training pass, then restore it in finally.
            run.tuning_config_json = {
                "mode": "disabled",
                "executed": True,
                "requested_configuration": requested_tuning,
            }
            session.commit()

    try:
        succeeded = (
            process_segmentation_training_job(settings, factory, job_id)
            if task == "segment"
            else process_training_job(settings, factory, job_id)
        )
    finally:
        _restore_tuning_provenance(
            factory,
            run_id,
            requested_tuning,
            tuning_artifact,
        )
    if not succeeded:
        return False

    try:
        _execute_validation(settings, factory, run_id)
    except Exception as exc:
        with factory() as session:
            run = session.get(TrainingRun, run_id)
            if run is not None:
                run.warnings_json = [
                    *list(getattr(run, "warnings_json", None) or []),
                    f"Post-training class-wise validation failed: {exc}",
                ]
                logs_path = getattr(run, "logs_path", None)
                if logs_path:
                    _append_log(
                        resolve_managed_project_path(settings, logs_path),
                        f"[{datetime.now(UTC).isoformat()}] validation warning: {exc}",
                    )
                session.commit()
    return True


def process_task_aware_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    """Route queued training jobs to task-specific execution."""

    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "training" or job.status != "queued":
            return False
        run_id = str(job.request_json.get("training_run_id", ""))
        run = session.get(TrainingRun, run_id)
        if run is None:
            return process_training_job(settings, factory, job_id)
        task = run.task

    if task in {"detect", "segment"}:
        return _process_ultralytics_training(settings, factory, job_id, run_id, task)
    if task == SEMANTIC_SEGMENTATION_TASK:
        return process_semantic_training_job(settings, factory, job_id)
    if task == CLASSIFICATION_TASK:
        return process_classification_training_job(settings, factory, job_id)
    return process_training_job(settings, factory, job_id)
