"""Background training-job execution for the Training workspace."""

from __future__ import annotations

import csv
import shutil
from contextlib import suppress
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
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
    ModelRegistration,
    Project,
    TrainingRun,
)
from reefvision.ml.dependencies import configure_provider_runtime, require_provider_ready
from reefvision.ml.providers import resolve_torch_device
from reefvision.storage.catalog_models import catalog_asset_path, catalog_manifest_record
from reefvision.storage.datasets import write_yolo_detection_export
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path


def process_training_job(settings: Settings, factory: sessionmaker[Session], job_id: str) -> bool:
    dataset_output_path: str | None = None
    dataset_archive_path: str | None = None
    run_id: str | None = None
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "training" or job.status != "queued":
            return False
        run_id = str(job.request_json["training_run_id"])
        run = session.get(TrainingRun, run_id)
        if run is None:
            job.status = "failed"
            job.error_message = "Training run is missing"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        run.status = "preflight"
        run.stage = "preflight"
        run.started_at = datetime.now(UTC)
        run.error_message = None
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        job.result_json = {"stage": "preflight"}
        session.commit()

    try:
        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None:
                raise RuntimeError("Training run or job is missing")
            if run.dataset_version_id is None:
                raise RuntimeError("Training run is missing its dataset version")
            project = session.get(Project, run.project_id)
            version_row = session.get(DatasetVersion, run.dataset_version_id)
            if project is None or version_row is None:
                raise RuntimeError("Training run references missing project or dataset version")
            if run.task != "detect":
                raise RuntimeError(
                    "This Training foundation currently executes only object-detection runs"
                )
            if dict(run.tuning_config_json).get("mode", "disabled") != "disabled":
                raise RuntimeError(
                    "Tuning execution is not implemented in this Training foundation"
                )
            if dict(run.tiling_config_json).get("mode", "none") != "none":
                raise RuntimeError(
                    "The current training executor launches only the no-tiling baseline"
                )
            require_provider_ready(run.provider_id, settings)

            run.status = "preparing_dataset"
            run.stage = "preparing_dataset"
            job.result_json = {"stage": "preparing_dataset"}
            session.commit()

            items = list(
                session.scalars(
                    select(DatasetVersionItem)
                    .where(DatasetVersionItem.dataset_version_id == version_row.id)
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
                        f"Managed source image is missing for training: {image_id}"
                    )

            base_relative = f"{project.storage_root}/training/{run.id}"
            dataset_output_path = f"{base_relative}/dataset"
            dataset_manifest_path = f"{base_relative}/dataset-manifest.json"
            dataset_archive_path = f"{base_relative}/dataset.zip"
            dataset_root = resolve_managed_project_path(settings, dataset_output_path)
            shutil.rmtree(dataset_root, ignore_errors=True)
            dataset_archive = resolve_managed_project_path(settings, dataset_archive_path)
            dataset_archive.unlink(missing_ok=True)
            export_result = write_yolo_detection_export(
                settings,
                export_id=run.id,
                version=version_row,
                items=items,
                image_paths=image_paths,
                output_path=dataset_output_path,
                manifest_path=dataset_manifest_path,
                archive_path=dataset_archive_path,
            )

            save_root_relative = f"{base_relative}/ultralytics"
            save_root = resolve_managed_project_path(settings, save_root_relative)
            shutil.rmtree(save_root, ignore_errors=True)
            save_root.mkdir(parents=True, exist_ok=True)
            logs_path = save_root / "training.log"
            _append_log(logs_path, f"[{datetime.now(UTC).isoformat()}] dataset prepared")

            checkpoint_source = _resolve_model_source(settings, session, run)
            configure_provider_runtime(settings)
            run.status = "training"
            run.stage = "training"
            run.logs_path = _relative_to_data_dir(settings, logs_path)
            run.artifact_manifest_json = {
                "dataset_output_path": dataset_output_path,
                "dataset_manifest_path": dataset_manifest_path,
                "dataset_archive_path": dataset_archive_path,
                "dataset_export_result": export_result,
            }
            job.result_json = {"stage": "training", "dataset_output_path": dataset_output_path}
            session.commit()

        from ultralytics import YOLO  # type: ignore[attr-defined]

        cancellation_requested = {"value": False}
        model = YOLO(checkpoint_source)
        model.add_callback(
            "on_fit_epoch_end",
            lambda trainer: _on_fit_epoch_end(
                settings, factory, job_id, run_id, trainer, cancellation_requested
            ),
        )
        model.add_callback(
            "on_train_start",
            lambda trainer: _on_train_start(settings, factory, job_id, run_id, trainer),
        )
        model.add_callback(
            "on_train_end",
            lambda trainer: _on_train_end(settings, factory, job_id, run_id, trainer),
        )

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise RuntimeError("Training run disappeared before launch")
            train_args = dict(run.training_config_json)
            precision = run.precision
            device = resolve_torch_device(run.device)
            if precision == "fp32":
                train_args["amp"] = False
            elif precision == "amp":
                train_args["amp"] = True
            if run.random_seed is not None:
                train_args["seed"] = run.random_seed
            train_args.update(
                {
                    "data": str(
                        resolve_managed_project_path(settings, dataset_output_path) / "data.yaml"
                    ),
                    "device": device,
                    "project": str(resolve_managed_project_path(settings, f"{base_relative}/runs")),
                    "name": "detect",
                    "exist_ok": True,
                    "save": True,
                    "verbose": False,
                }
            )
            _append_log(
                resolve_managed_project_path(settings, run.logs_path or ""),
                f"[{datetime.now(UTC).isoformat()}] launching Ultralytics detect training",
            )

        model.train(**train_args)

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None:
                raise RuntimeError("Training run disappeared after execution")
            trainer = model.trainer
            if trainer is None:
                raise RuntimeError("Ultralytics trainer unavailable after execution")
            save_dir = Path(str(trainer.save_dir)).resolve()
            results_csv = save_dir / "results.csv"
            weights_dir = save_dir / "weights"
            best_ckpt = weights_dir / "best.pt"
            last_ckpt = weights_dir / "last.pt"
            history = _read_results_csv(results_csv)
            last_metrics = _last_metrics(history)
            run.metrics_history_json = history
            run.metrics_json = last_metrics
            run.artifact_manifest_json = {
                **dict(run.artifact_manifest_json),
                "run_save_dir": _relative_to_data_dir(settings, save_dir),
                "results_csv": _relative_to_data_dir(settings, results_csv)
                if results_csv.is_file()
                else None,
                "best_checkpoint_path": _relative_to_data_dir(settings, best_ckpt)
                if best_ckpt.is_file()
                else None,
                "last_checkpoint_path": _relative_to_data_dir(settings, last_ckpt)
                if last_ckpt.is_file()
                else None,
            }
            run.result_checkpoint_path = (
                _relative_to_data_dir(settings, best_ckpt)
                if best_ckpt.is_file()
                else _relative_to_data_dir(settings, last_ckpt)
                if last_ckpt.is_file()
                else None
            )
            if cancellation_requested["value"] or job.status == "cancel_requested":
                job.status = "cancelled"
                run.status = "cancelled"
                run.stage = "cancelled"
                _append_log(
                    resolve_managed_project_path(settings, run.logs_path or ""),
                    f"[{datetime.now(UTC).isoformat()}] training cancelled",
                )
            else:
                job.status = "succeeded"
                job.progress_current = max(job.progress_total, 1)
                job.result_json = {
                    "stage": "completed",
                    "metrics": last_metrics,
                    "result_checkpoint_path": run.result_checkpoint_path,
                }
                run.status = "completed"
                run.stage = "completed"
                experiment = ExperimentRecord(
                    project_id=run.project_id,
                    training_run_id=run.id,
                    dataset_version_id=run.dataset_version_id,
                    dataset_manifest_sha256=run.dataset_manifest_sha256,
                    split_manifest_sha256=run.split_manifest_sha256,
                    task=run.task,
                    provider_id=run.provider_id,
                    architecture=run.architecture,
                    summary_metrics_json=last_metrics,
                    comparison_warnings_json=list(run.warnings_json),
                    artifact_manifest_json=dict(run.artifact_manifest_json),
                    package_versions_json=_package_versions_snapshot(),
                )
                session.add(experiment)
                _append_log(
                    resolve_managed_project_path(settings, run.logs_path or ""),
                    f"[{datetime.now(UTC).isoformat()}] training completed",
                )
            run.completed_at = datetime.now(UTC)
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            run = session.get(TrainingRun, run_id) if run_id is not None else None
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


def _resolve_model_source(settings: Settings, session: Session, run: TrainingRun) -> str:
    resolved_asset_id = (run.resolved_model_asset_id or "").strip()
    if resolved_asset_id.startswith("catalog_model:"):
        catalog_id = resolved_asset_id.partition(":")[2].strip()
        if not catalog_id:
            raise RuntimeError("Training run is missing its managed catalog model id")
        from reefvision.services.model_catalog import ModelCatalogService

        entry = ModelCatalogService(session, settings).get_static_catalog_item(catalog_id)
        if len(entry.expected_files) != 1:
            raise RuntimeError("Managed catalog model has an invalid expected-file manifest")
        expected = entry.expected_files[0]
        path = catalog_asset_path(settings, catalog_id, expected.filename)
        record = catalog_manifest_record(settings, catalog_id)
        if record is None or not path.is_file():
            raise RuntimeError("The selected managed catalog checkpoint is missing")
        checksum, size = hash_model_file(path)
        if checksum != expected.sha256 or size != expected.size_bytes:
            raise RuntimeError("The selected managed catalog checkpoint failed verification")
        if run.resolved_model_checksum and checksum != run.resolved_model_checksum:
            raise RuntimeError("Training provenance checksum does not match the managed checkpoint")
        return str(path)
    if resolved_asset_id.startswith("registered_model:"):
        model_id = resolved_asset_id.partition(":")[2].strip() or run.initial_checkpoint_model_id
        if not model_id:
            raise RuntimeError("Training run is missing its resolved initial checkpoint model")
        model = session.get(ModelRegistration, model_id)
        if model is None:
            raise RuntimeError("The selected initial checkpoint is missing")
        return str(resolve_managed_project_path(settings, model.managed_path))
    if resolved_asset_id.startswith("builtin_architecture:"):
        architecture = resolved_asset_id.partition(":")[2].strip()
        if architecture:
            return architecture
    if run.initial_checkpoint_source == "registered_model":
        if run.initial_checkpoint_model_id is None:
            raise RuntimeError("Training run is missing its initial checkpoint model")
        model = session.get(ModelRegistration, run.initial_checkpoint_model_id)
        if model is None:
            raise RuntimeError("The selected initial checkpoint is missing")
        return str(resolve_managed_project_path(settings, model.managed_path))
    if run.architecture:
        return run.architecture
    raise RuntimeError("Training run is missing its architecture selection")


def _append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def _read_results_csv(path: Path) -> dict[str, list[float]]:
    if not path.is_file():
        return {}
    rows: dict[str, list[float]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            for key, value in row.items():
                if key is None or value is None:
                    continue
                normalized = key.strip()
                try:
                    rows.setdefault(normalized, []).append(float(value))
                except ValueError:
                    continue
    return rows


def _last_metrics(history: dict[str, list[float]]) -> dict[str, float]:
    return {key: values[-1] for key, values in history.items() if values}


def _on_train_start(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
    run_id: str,
    trainer: Any,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        run = session.get(TrainingRun, run_id)
        if job is None or run is None:
            return
        run.status = "training"
        run.stage = "training"
        run.progress_total_epochs = int(getattr(trainer, "epochs", run.progress_total_epochs) or 0)
        job.result_json = {"stage": "training"}
        session.commit()


def _on_fit_epoch_end(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
    run_id: str,
    trainer: Any,
    cancellation_requested: dict[str, bool],
) -> None:
    history = _read_results_csv(Path(str(trainer.csv)))
    last_metrics = _last_metrics(history)
    with factory() as session:
        job = session.get(Job, job_id)
        run = session.get(TrainingRun, run_id)
        if job is None or run is None:
            return
        run.progress_epoch = int(getattr(trainer, "epoch", 0)) + 1
        run.progress_total_epochs = int(getattr(trainer, "epochs", run.progress_total_epochs) or 0)
        run.metrics_history_json = history
        run.metrics_json = last_metrics
        job.progress_current = max(run.progress_epoch, job.progress_current)
        job.progress_total = max(run.progress_total_epochs, job.progress_total)
        job.result_json = {
            "stage": "training",
            "epoch": run.progress_epoch,
            "total_epochs": run.progress_total_epochs,
            "metrics": last_metrics,
        }
        if job.status == "cancel_requested":
            cancellation_requested["value"] = True
            trainer.stop = True
        session.commit()


def _on_train_end(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
    run_id: str,
    trainer: Any,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        run = session.get(TrainingRun, run_id)
        if job is None or run is None:
            return
        run.stage = "evaluating"
        job.result_json = {"stage": "evaluating"}
        session.commit()


def _relative_to_data_dir(settings: Settings, path: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(settings.resolved_data_dir).as_posix()


def _package_versions_snapshot() -> dict[str, str | None]:
    return {
        package: _package_version(package)
        for package in ("ultralytics", "torch", "torchvision", "numpy")
    }


def _package_version(distribution_name: str) -> str | None:
    try:
        return version(distribution_name)
    except PackageNotFoundError:
        return None
