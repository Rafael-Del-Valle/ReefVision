"""Background Ultralytics crop-classification training."""

from __future__ import annotations

import shutil
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    ExperimentRecord,
    ImageAsset,
    Job,
    ModelRegistration,
    Project,
    TrainingRun,
)
from reefvision.jobs.training import (
    _append_log,
    _last_metrics,
    _on_fit_epoch_end,
    _on_train_end,
    _on_train_start,
    _package_versions_snapshot,
    _read_results_csv,
    _relative_to_data_dir,
)
from reefvision.ml.classification import (
    CLASSIFICATION_TASK,
    resolve_installed_classification_architecture,
)
from reefvision.ml.providers import resolve_torch_device
from reefvision.storage.classification_exports import write_classification_export
from reefvision.storage.projects import resolve_managed_project_path


def _model_source(settings: Settings, session: Session, run: TrainingRun) -> str:
    if run.initial_checkpoint_source == "registered_model":
        if run.initial_checkpoint_model_id is None:
            raise RuntimeError("Classification run is missing its initial model")
        model = session.get(ModelRegistration, run.initial_checkpoint_model_id)
        if model is None or model.purpose != "classifier" or model.task != CLASSIFICATION_TASK:
            raise RuntimeError("The initial model is not a registered classifier")
        return str(resolve_managed_project_path(settings, model.managed_path))
    if run.architecture:
        return str(resolve_installed_classification_architecture(run.architecture, settings))
    raise RuntimeError("Classification run is missing its architecture")


def process_classification_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    run_id: str | None = None
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "training" or job.status != "queued":
            return False
        run_id = str(job.request_json.get("training_run_id", ""))
        run = session.get(TrainingRun, run_id)
        if run is None or run.task != CLASSIFICATION_TASK:
            return False
        run.status = "preparing_dataset"
        run.stage = "preparing_dataset"
        run.started_at = datetime.now(UTC)
        run.error_message = None
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        job.result_json = {"stage": "preparing_dataset"}
        session.commit()

    try:
        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None or run.dataset_version_id is None:
                raise RuntimeError("Classification training records are incomplete")
            version = session.get(DatasetVersion, run.dataset_version_id)
            project = session.get(Project, run.project_id)
            if version is None or project is None:
                raise RuntimeError("Classification run references missing data")
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
            for image_id, path in image_paths.items():
                if not path.is_file():
                    raise FileNotFoundError(
                        f"Managed source image is missing for classification: {image_id}"
                    )

            config = dict(run.training_config_json)
            mode = str(config.pop("classification_mode", "multiclass"))
            minimum_crop_size_px = int(config.pop("minimum_crop_size_px", 10))
            padding_fraction = float(config.pop("padding_fraction", 0.0))
            base_relative = f"{project.storage_root}/training/{run.id}"
            dataset_output = f"{base_relative}/classification-dataset"
            dataset_manifest = f"{dataset_output}/export-manifest.json"
            dataset_archive = f"{dataset_output}.zip"
            dataset_root = resolve_managed_project_path(settings, dataset_output)
            shutil.rmtree(dataset_root, ignore_errors=True)
            resolve_managed_project_path(settings, dataset_archive).unlink(missing_ok=True)
            export_result = write_classification_export(
                settings,
                export_id=run.id,
                version=version,
                items=items,
                image_paths=image_paths,
                output_path=dataset_output,
                manifest_path=dataset_manifest,
                archive_path=dataset_archive,
                mode=mode,
                minimum_crop_size_px=minimum_crop_size_px,
                padding_fraction=padding_fraction,
            )
            if int(export_result["item_count"]) <= 0:
                raise RuntimeError("No classification crops remained after preprocessing")

            save_root = resolve_managed_project_path(settings, f"{base_relative}/ultralytics")
            shutil.rmtree(save_root, ignore_errors=True)
            save_root.mkdir(parents=True, exist_ok=True)
            logs_path = save_root / "training.log"
            _append_log(
                logs_path,
                f"[{datetime.now(UTC).isoformat()}] classification dataset prepared",
            )
            checkpoint_source = _model_source(settings, session, run)
            run.status = "training"
            run.stage = "training"
            run.logs_path = _relative_to_data_dir(settings, logs_path)
            run.artifact_manifest_json = {
                "classification_mode": mode,
                "minimum_crop_size_px": minimum_crop_size_px,
                "padding_fraction": padding_fraction,
                "dataset_output_path": dataset_output,
                "dataset_manifest_path": dataset_manifest,
                "dataset_archive_path": dataset_archive,
                "dataset_export_result": export_result,
                "resolved_architecture_path": checkpoint_source
                if run.initial_checkpoint_source == "scratch"
                else None,
            }
            job.result_json = {
                "stage": "training",
                "dataset_output_path": dataset_output,
            }
            session.commit()

        from ultralytics import YOLO  # type: ignore[attr-defined]

        cancellation_requested = {"value": False}
        model = YOLO(checkpoint_source)
        model.add_callback(
            "on_fit_epoch_end",
            lambda trainer: _on_fit_epoch_end(
                settings,
                factory,
                job_id,
                run_id or "",
                trainer,
                cancellation_requested,
            ),
        )
        model.add_callback(
            "on_train_start",
            lambda trainer: _on_train_start(
                settings,
                factory,
                job_id,
                run_id or "",
                trainer,
            ),
        )
        model.add_callback(
            "on_train_end",
            lambda trainer: _on_train_end(
                settings,
                factory,
                job_id,
                run_id or "",
                trainer,
            ),
        )

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise RuntimeError("Classification run disappeared before launch")
            train_args = dict(run.training_config_json)
            for key in (
                "classification_mode",
                "minimum_crop_size_px",
                "padding_fraction",
            ):
                train_args.pop(key, None)
            train_args.update(
                {
                    "data": str(dataset_root),
                    "device": resolve_torch_device(run.device),
                    "project": str(resolve_managed_project_path(settings, f"{base_relative}/runs")),
                    "name": "classify",
                    "exist_ok": True,
                    "save": True,
                    "verbose": False,
                    "amp": run.precision == "amp",
                }
            )
            if run.random_seed is not None:
                train_args["seed"] = run.random_seed
            _append_log(
                resolve_managed_project_path(settings, run.logs_path or ""),
                f"[{datetime.now(UTC).isoformat()}] launching Ultralytics classification",
            )

        model.train(**train_args)

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None or model.trainer is None:
                raise RuntimeError("Classification run disappeared after execution")
            save_dir = Path(str(model.trainer.save_dir)).resolve()
            results_csv = save_dir / "results.csv"
            weights_dir = save_dir / "weights"
            best_ckpt = weights_dir / "best.pt"
            last_ckpt = weights_dir / "last.pt"
            history = _read_results_csv(results_csv)
            metrics = _last_metrics(history)
            run.metrics_history_json = history
            run.metrics_json = metrics
            run.artifact_manifest_json = {
                **dict(run.artifact_manifest_json),
                "run_save_dir": _relative_to_data_dir(settings, save_dir),
                "results_csv": (
                    _relative_to_data_dir(settings, results_csv) if results_csv.is_file() else None
                ),
                "best_checkpoint_path": (
                    _relative_to_data_dir(settings, best_ckpt) if best_ckpt.is_file() else None
                ),
                "last_checkpoint_path": (
                    _relative_to_data_dir(settings, last_ckpt) if last_ckpt.is_file() else None
                ),
            }
            run.result_checkpoint_path = (
                _relative_to_data_dir(settings, best_ckpt)
                if best_ckpt.is_file()
                else _relative_to_data_dir(settings, last_ckpt)
                if last_ckpt.is_file()
                else None
            )
            if cancellation_requested["value"] or job.status == "cancel_requested":
                run.status = "cancelled"
                run.stage = "cancelled"
                job.status = "cancelled"
            elif run.result_checkpoint_path is None:
                raise RuntimeError("Classification training produced no checkpoint")
            else:
                run.status = "completed"
                run.stage = "completed"
                job.status = "succeeded"
                job.progress_current = max(job.progress_total, 1)
                job.result_json = {
                    "stage": "completed",
                    "metrics": metrics,
                    "result_checkpoint_path": run.result_checkpoint_path,
                }
                session.add(
                    ExperimentRecord(
                        project_id=run.project_id,
                        training_run_id=run.id,
                        dataset_version_id=run.dataset_version_id,
                        dataset_manifest_sha256=run.dataset_manifest_sha256,
                        split_manifest_sha256=run.split_manifest_sha256,
                        task=run.task,
                        provider_id=run.provider_id,
                        architecture=run.architecture,
                        summary_metrics_json=metrics,
                        comparison_warnings_json=list(run.warnings_json),
                        artifact_manifest_json=dict(run.artifact_manifest_json),
                        package_versions_json=_package_versions_snapshot(),
                    )
                )
            run.completed_at = datetime.now(UTC)
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            run = session.get(TrainingRun, run_id) if run_id else None
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
            if run is not None:
                run.status = "failed"
                run.stage = "failed"
                run.error_message = str(exc)
                run.completed_at = datetime.now(UTC)
                if run.logs_path:
                    with suppress(Exception):
                        _append_log(
                            resolve_managed_project_path(settings, run.logs_path),
                            f"[{datetime.now(UTC).isoformat()}] failure: {exc}",
                        )
            session.commit()
        return False
