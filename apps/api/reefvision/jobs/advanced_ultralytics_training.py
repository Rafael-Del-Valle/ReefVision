"""Advanced Ultralytics tuning and post-training validation orchestration."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    ExperimentRecord,
    ImageAsset,
    Job,
    Project,
    TrainingRun,
)
from reefvision.jobs.segmentation_training import process_segmentation_training_job
from reefvision.jobs.training import (
    _append_log,
    _relative_to_data_dir,
    _resolve_model_source,
    process_training_job,
)
from reefvision.ml.dependencies import configure_provider_runtime, require_provider_ready
from reefvision.ml.providers import resolve_torch_device
from reefvision.ml.ultralytics_metrics import run_ultralytics_validation
from reefvision.ml.ultralytics_tuning import normalize_tuning_config, run_ultralytics_tuning
from reefvision.storage.datasets import write_yolo_detection_export
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.segmentation_exports import write_yolo_segmentation_export


ULTRALYTICS_TASKS = {"detect", "segment"}
PROTECTED_TRAINING_KEYS = {
    "data",
    "device",
    "project",
    "name",
    "exist_ok",
    "save",
    "plots",
    "iterations",
}


def _managed_value(settings: Settings, value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _managed_value(settings, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_managed_value(settings, item) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute():
            try:
                return path.resolve().relative_to(settings.resolved_data_dir).as_posix()
            except ValueError:
                return value
    return value


def _fail(factory: sessionmaker[Session], job_id: str, run_id: str, message: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        run = session.get(TrainingRun, run_id)
        now = datetime.now(UTC)
        if job is not None:
            job.status = "failed"
            job.error_message = message
            job.completed_at = now
        if run is not None:
            run.status = "failed"
            run.stage = "failed"
            run.error_message = message
            run.completed_at = now
        session.commit()


def _dataset_records(
    settings: Settings,
    session: Session,
    run: TrainingRun,
) -> tuple[Project, DatasetVersion, list[DatasetVersionItem], dict[str, Path]]:
    if run.dataset_version_id is None:
        raise RuntimeError("Training run is missing its dataset version")
    project = session.get(Project, run.project_id)
    version = session.get(DatasetVersion, run.dataset_version_id)
    if project is None or version is None:
        raise RuntimeError("Training run references a missing project or dataset version")
    items = list(
        session.scalars(
            select(DatasetVersionItem)
            .where(DatasetVersionItem.dataset_version_id == version.id)
            .order_by(
                DatasetVersionItem.split,
                DatasetVersionItem.original_filename,
                DatasetVersionItem.image_id,
            )
        )
    )
    images = list(
        session.scalars(
            select(ImageAsset).where(ImageAsset.id.in_([item.image_id for item in items]))
        )
    )
    image_paths = {
        image.id: resolve_managed_project_path(settings, image.managed_path)
        for image in images
    }
    missing = [image_id for image_id, path in image_paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Managed source images are missing for tuning: " + ", ".join(missing[:5])
        )
    return project, version, items, image_paths


def _execute_tuning(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
    run_id: str,
) -> None:
    with factory() as session:
        run = session.get(TrainingRun, run_id)
        job = session.get(Job, job_id)
        if run is None or job is None:
            raise RuntimeError("Training run or job is missing")
        config = normalize_tuning_config(run.tuning_config_json)
        if config["mode"] == "disabled":
            return
        if run.task not in ULTRALYTICS_TASKS:
            raise RuntimeError("Ultralytics tuning currently supports detection and segmentation")
        require_provider_ready(run.provider_id, settings)
        project, version, items, image_paths = _dataset_records(settings, session, run)
        base_relative = f"{project.storage_root}/training/{run.id}/tuning"
        dataset_relative = f"{base_relative}/dataset"
        manifest_relative = f"{base_relative}/dataset-manifest.json"
        archive_relative = f"{base_relative}/dataset.zip"
        dataset_root = resolve_managed_project_path(settings, dataset_relative)
        shutil.rmtree(dataset_root, ignore_errors=True)
        resolve_managed_project_path(settings, archive_relative).unlink(missing_ok=True)
        if run.task == "segment":
            export_result = write_yolo_segmentation_export(
                settings,
                export_id=f"{run.id}-tuning",
                version=version,
                items=items,
                image_paths=image_paths,
                output_path=dataset_relative,
                manifest_path=manifest_relative,
                archive_path=archive_relative,
            )
        else:
            export_result = write_yolo_detection_export(
                settings,
                export_id=f"{run.id}-tuning",
                version=version,
                items=items,
                image_paths=image_paths,
                output_path=dataset_relative,
                manifest_path=manifest_relative,
                archive_path=archive_relative,
            )
        checkpoint_source = _resolve_model_source(settings, session, run)
        configure_provider_runtime(settings)
        device = resolve_torch_device(run.device)
        base_args = dict(run.training_config_json)
        base_args.pop("epochs", None)
        base_args.pop("patience", None)
        base_args.update(
            {
                "data": str(dataset_root / "data.yaml"),
                "device": device,
                "amp": run.precision == "amp",
                "verbose": False,
            }
        )
        if run.random_seed is not None:
            base_args["seed"] = run.random_seed
        run.status = "tuning"
        run.stage = "tuning"
        job.status = "running"
        job.started_at = job.started_at or datetime.now(UTC)
        job.result_json = {
            "stage": "tuning",
            "iterations": config["iterations"],
            "epochs_per_trial": config["epochs_per_trial"],
        }
        session.commit()

    output_root = resolve_managed_project_path(settings, f"{base_relative}/ultralytics")
    tuning_summary = run_ultralytics_tuning(
        checkpoint_source=checkpoint_source,
        base_train_args=base_args,
        tuning_config=config,
        output_root=output_root,
    )

    with factory() as session:
        run = session.get(TrainingRun, run_id)
        job = session.get(Job, job_id)
        if run is None or job is None:
            raise RuntimeError("Training run or job disappeared after tuning")
        applied_parameters = {
            key: value
            for key, value in dict(tuning_summary.get("best_parameters", {})).items()
            if key not in PROTECTED_TRAINING_KEYS
        }
        base_training_config = dict(run.training_config_json)
        if bool(config.get("train_best", True)):
            run.training_config_json = {**base_training_config, **applied_parameters}
        artifact_manifest = dict(run.artifact_manifest_json or {})
        artifact_manifest["tuning"] = _managed_value(
            settings,
            {
                **tuning_summary,
                "dataset_output_path": dataset_relative,
                "dataset_manifest_path": manifest_relative,
                "dataset_archive_path": archive_relative,
                "dataset_export_result": export_result,
                "base_training_config": base_training_config,
                "applied_best_parameters": applied_parameters,
            },
        )
        run.artifact_manifest_json = artifact_manifest
        run.status = "queued"
        run.stage = "queued_after_tuning"
        job.status = "queued"
        job.result_json = {
            "stage": "queued_after_tuning",
            "best_fitness": tuning_summary.get("best_fitness"),
            "applied_best_parameters": applied_parameters,
        }
        session.commit()


def _execute_validation(
    settings: Settings,
    factory: sessionmaker[Session],
    run_id: str,
) -> None:
    with factory() as session:
        run = session.get(TrainingRun, run_id)
        if run is None or run.result_checkpoint_path is None:
            return
        project = session.get(Project, run.project_id)
        if project is None:
            return
        artifact_manifest = dict(run.artifact_manifest_json or {})
        dataset_output = artifact_manifest.get("dataset_output_path")
        if not isinstance(dataset_output, str):
            return
        checkpoint = resolve_managed_project_path(settings, run.result_checkpoint_path)
        data_yaml = resolve_managed_project_path(settings, dataset_output) / "data.yaml"
        if not checkpoint.is_file() or not data_yaml.is_file():
            return
        output_relative = f"{project.storage_root}/training/{run.id}/validation"
        output_directory = resolve_managed_project_path(settings, output_relative)
        shutil.rmtree(output_directory, ignore_errors=True)
        device = resolve_torch_device(run.device)
        evaluation_config = dict(run.evaluation_config_json or {})

    payload, artifact_paths, plot_paths = run_ultralytics_validation(
        checkpoint_path=checkpoint,
        data_yaml=data_yaml,
        task=run.task,
        device=device,
        evaluation_config=evaluation_config,
        output_directory=output_directory,
    )
    managed_artifacts = _managed_value(settings, artifact_paths)
    managed_plots = _managed_value(settings, plot_paths)

    with factory() as session:
        run = session.get(TrainingRun, run_id)
        if run is None:
            return
        artifact_manifest = dict(run.artifact_manifest_json or {})
        artifact_manifest["ultralytics_validation"] = {
            "summary": payload,
            "json_path": managed_artifacts.get("json"),
            "csv_path": managed_artifacts.get("csv"),
            "plot_paths": managed_plots,
            "output_path": output_relative,
        }
        run.artifact_manifest_json = artifact_manifest
        metrics = dict(run.metrics_json or {})
        for key, value in dict(payload.get("aggregate", {})).items():
            metrics[f"validation/{key}"] = value
        run.metrics_json = metrics
        experiment = session.scalar(
            select(ExperimentRecord).where(ExperimentRecord.training_run_id == run.id)
        )
        if experiment is not None:
            experiment.summary_metrics_json = metrics
            experiment.artifact_manifest_json = artifact_manifest
        session.commit()


def process_advanced_ultralytics_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    """Tune if requested, use the stable task worker, then add class-wise validation."""

    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "training" or job.status != "queued":
            return False
        run_id = str(job.request_json.get("training_run_id", ""))
        run = session.get(TrainingRun, run_id)
        if run is None or run.task not in ULTRALYTICS_TASKS:
            return False
        tuning_config = normalize_tuning_config(run.tuning_config_json)

    try:
        if tuning_config["mode"] != "disabled":
            _execute_tuning(settings, factory, job_id, run_id)
        succeeded = (
            process_segmentation_training_job(settings, factory, job_id)
            if run.task == "segment"
            else process_training_job(settings, factory, job_id)
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
                        *list(run.warnings_json or []),
                        f"Post-training class-wise validation failed: {exc}",
                    ]
                    if run.logs_path:
                        _append_log(
                            resolve_managed_project_path(settings, run.logs_path),
                            f"[{datetime.now(UTC).isoformat()}] validation warning: {exc}",
                        )
                    session.commit()
        return True
    except Exception as exc:
        _fail(factory, job_id, run_id, str(exc))
        return False
