"""Background training-job execution for the Training workspace."""
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import csv
import logging
import math
import shutil
import sys
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
from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import configure_provider_runtime, require_provider_ready
from reefvision.ml.providers import resolve_torch_device
from reefvision.ml.ultralytics_tuning import (
    FITNESS_DEFINITION,
    best_trial,
    effective_search_space,
    normalize_tuning_csv,
)
from reefvision.storage.catalog_models import catalog_asset_path, catalog_manifest_record
from reefvision.storage.datasets import write_yolo_detection_export
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.training import intact_torch_checkpoint

LOGGER = logging.getLogger("reefvision.training")


def _complete_training_run(session: Session, run: TrainingRun, job: Job) -> None:
    """Commit with the caller so run, job and experiment become durable together."""
    now = datetime.now(UTC)
    run.status = run.stage = "completed"
    run.error_message = job.error_message = None
    run.completed_at = run.completed_at or now
    job.completed_at = job.completed_at or now
    job.status = "succeeded"
    job.progress_current = run.progress_epoch
    job.progress_total = run.progress_total_epochs
    job.result_json = {
        "stage": "completed",
        "metrics": dict(run.metrics_json),
        "result_checkpoint_path": run.result_checkpoint_path,
    }
    if (
        session.scalar(
            select(ExperimentRecord.id).where(ExperimentRecord.training_run_id == run.id)
        )
        is None
    ):
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
                summary_metrics_json=dict(run.metrics_json),
                comparison_warnings_json=list(run.warnings_json),
                artifact_manifest_json=dict(run.artifact_manifest_json),
                package_versions_json=_package_versions_snapshot(),
            )
        )


def recover_training_run(session: Session, settings: Settings | None, job: Job) -> None:
    """Finalize interrupted training conservatively; never execute or remove output."""
    run = session.scalar(select(TrainingRun).where(TrainingRun.job_id == job.id))
    if run is not None and run.status == "completed":
        _complete_training_run(session, run, job)
        return
    cancelled = job.status == "cancel_requested" or (
        run is not None and run.status in {"cancel_requested", "cancelled"}
    )
    if not cancelled and run is not None and settings is not None:
        try:
            if _recover_completed_artifacts(session, settings, run, job):
                LOGGER.info("Recovered completed training run %s after restart", run.id)
                return
        except (OSError, ValueError, csv.Error, ValidationError) as exc:
            LOGGER.warning("Cannot validate interrupted training artifacts for %s: %s", run.id, exc)
    final_status = "cancelled" if cancelled else "failed"
    message = (
        "Training cancellation finalized after application restart."
        if cancelled
        else "Training was interrupted by an application restart; complete final artifacts "
        "could not be verified. Training was not restarted."
    ) + " Existing checkpoints, metrics, logs and artifacts were preserved."
    now = datetime.now(UTC)
    job.status = final_status
    job.error_message = message
    job.completed_at = now
    job.result_json = {**(job.result_json or {}), "stage": final_status}
    if run is not None:
        run.status = run.stage = final_status
        run.error_message = message
        run.completed_at = now


def _recover_completed_artifacts(
    session: Session,
    settings: Settings,
    run: TrainingRun,
    job: Job,
) -> bool:
    # Other providers and tuning trials have different completion evidence.
    if (
        run.provider_id != "ultralytics"
        or run.task != "detect"
        or run.tuning_config_json.get("mode", "disabled") != "disabled"
    ):
        return False
    total = int(run.training_config_json.get("epochs", 0))
    project = session.get(Project, run.project_id)
    if total <= 0 or project is None:
        return False
    save_dir = resolve_managed_project_path(
        settings,
        f"{project.storage_root}/training/{run.id}/runs/detect",
    )
    results_csv = save_dir / "results.csv"
    rows = _read_results_table(results_csv)
    if [row.get("epoch") for row in rows] != list(range(1, total + 1)):
        return False
    final_metrics = {key: value for key, value in rows[-1].items() if key.startswith("metrics/")}
    if not final_metrics or not all(
        isinstance(value, (int, float)) and math.isfinite(value) for value in final_metrics.values()
    ):
        return False
    # A torn CSV with invalid numeric values is not durable completion evidence.
    if any(
        isinstance(value, float) and not math.isfinite(value)
        for row in rows
        for value in row.values()
    ):
        return False
    checkpoints = [save_dir / "weights" / name for name in ("best.pt", "last.pt")]
    checkpoint = next((path for path in checkpoints if intact_torch_checkpoint(path)), None)
    if checkpoint is None:
        return False
    _collect_training_results(settings, run, job, save_dir, results_csv)
    run.result_checkpoint_path = _relative_to_data_dir(settings, checkpoint)
    run.progress_epoch = run.progress_total_epochs = total
    _complete_training_run(session, run, job)
    job.result_json = {**(job.result_json or {}), "recovered_after_restart": True}
    return True


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
            tuning_enabled = dict(run.tuning_config_json).get("mode", "disabled") != "disabled"
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
            run.status = "tuning" if tuning_enabled else "training"
            run.stage = "tuning" if tuning_enabled else "training"
            run.logs_path = _relative_to_data_dir(settings, logs_path)
            run.artifact_manifest_json = {
                "dataset_output_path": dataset_output_path,
                "dataset_manifest_path": dataset_manifest_path,
                "dataset_archive_path": dataset_archive_path,
                "dataset_export_result": export_result,
            }
            job.result_json = {"stage": "training", "dataset_output_path": dataset_output_path}
            session.commit()

        from ultralytics import YOLO

        cancellation_requested = {"value": False}
        model = YOLO(checkpoint_source)
        last_reported_epoch = {"value": 0}

        def report_fit_epoch_end(trainer: Any) -> None:
            total = int(getattr(trainer, "epochs", 0))
            epoch = min(int(getattr(trainer, "epoch", 0)) + 1, total)
            # Ultralytics 8.3.228 repeats this hook after standalone final val.
            # Avoid CSV reads and database writes for that duplicate callback.
            if epoch <= last_reported_epoch["value"]:
                return
            _on_fit_epoch_end(settings, factory, job_id, run_id, trainer, cancellation_requested)
            last_reported_epoch["value"] = epoch

        def report_train_start(trainer: Any) -> None:
            last_reported_epoch["value"] = 0
            _on_train_start(settings, factory, job_id, run_id, trainer)

        def report_validation_start(validator: Any) -> None:
            if getattr(validator, "training", True) is False:
                _append_log(
                    logs_path, f"[{datetime.now(UTC).isoformat()}] final validation started"
                )

        model.add_callback("on_fit_epoch_end", report_fit_epoch_end)
        model.add_callback("on_train_start", report_train_start)
        model.add_callback("on_val_start", report_validation_start)
        model.add_callback(
            "on_train_end",
            lambda trainer: _on_train_end(settings, factory, job_id, run_id, trainer),
        )

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise RuntimeError("Training run disappeared before launch")
            train_args = dict(run.training_config_json)
            if sys.platform == "win32":
                train_args["workers"] = 0
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

        tuning_config = dict(run.tuning_config_json)
        if tuning_config.get("mode", "disabled") != "disabled":
            iterations = int(tuning_config.get("max_trials", 20))
            trial_epochs = int(tuning_config.get("epochs_per_trial", 10))
            train_args["epochs"] = trial_epochs
            model.tune(
                iterations=iterations,
                space=effective_search_space(tuning_config),
                **train_args,
            )
        else:
            model.train(**train_args)

        _append_log(
            logs_path,
            f"[{datetime.now(UTC).isoformat()}] provider execution returned; collecting artifacts",
        )

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None:
                raise RuntimeError("Training run disappeared after execution")
            tuning_enabled = dict(run.tuning_config_json).get("mode", "disabled") != "disabled"
            trainer = model.trainer
            if tuning_enabled:
                run_root = resolve_managed_project_path(settings, f"{base_relative}/runs")
                csv_candidates = sorted(
                    run_root.rglob("tune_results.csv"),
                    key=lambda item: item.stat().st_mtime,
                    reverse=True,
                )
                if not csv_candidates:
                    csv_candidates = sorted(
                        run_root.rglob("*.csv"),
                        key=lambda item: item.stat().st_mtime,
                        reverse=True,
                    )
                if not csv_candidates:
                    raise RuntimeError("Ultralytics tuning completed without a tuning results CSV")
                results_csv = csv_candidates[0]
                save_dir = results_csv.parent.resolve()
            else:
                if trainer is None:
                    raise RuntimeError("Ultralytics trainer unavailable after execution")
                save_dir = Path(str(trainer.save_dir)).resolve()
                results_csv = save_dir / "results.csv"
            _collect_training_results(
                settings,
                run,
                job,
                save_dir,
                results_csv,
                tuning_enabled=tuning_enabled,
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
                _complete_training_run(session, run, job)
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
            final_status = "cancelled" if job and job.status == "cancel_requested" else "failed"
            if job is not None:
                job.status = final_status
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
            if run is not None:
                run.status = final_status
                run.stage = final_status
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
    rows: dict[str, list[float]] = {}
    for row in _read_results_table(path):
        for key, value in row.items():
            if isinstance(value, (int, float)):
                rows.setdefault(key, []).append(float(value))
    return rows


def _read_results_table(path: Path) -> list[dict[str, str | float | None]]:
    """Preserve every native results.csv column while ordering rows by epoch."""
    if not path.is_file():
        return []
    rows: list[dict[str, str | float | None]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            row: dict[str, str | float | None] = {}
            for key, value in raw.items():
                if key is None:
                    continue
                normalized_key = key.strip()
                normalized_value = value.strip() if isinstance(value, str) else value
                if normalized_value in (None, ""):
                    row[normalized_key] = None
                    continue
                try:
                    row[normalized_key] = float(normalized_value)
                except ValueError:
                    row[normalized_key] = normalized_value
            rows.append(row)

    def epoch_value(row: dict[str, str | float | None]) -> float:
        value = row.get("epoch")
        return float(value) if isinstance(value, (int, float)) else float("inf")

    return sorted(rows, key=epoch_value)


def _discover_training_artifacts(settings: Settings, save_dir: Path) -> list[dict[str, Any]]:
    """Catalog actual provider artifacts without allowing arbitrary path browsing."""
    artifacts: list[dict[str, Any]] = []
    image_names = {
        "results.png",
        "confusion_matrix.png",
        "confusion_matrix_normalized.png",
        "PR_curve.png",
        "F1_curve.png",
        "P_curve.png",
        "R_curve.png",
        "labels.jpg",
        "labels_correlogram.jpg",
    }
    for path in sorted(item for item in save_dir.rglob("*") if item.is_file()):
        suffix = path.suffix.lower()
        category = (
            "checkpoint"
            if suffix == ".pt"
            else "metrics"
            if path.name == "results.csv"
            else "plot"
            if path.name in image_names or suffix in {".png", ".jpg", ".jpeg"}
            else "configuration"
            if suffix in {".yaml", ".yml", ".json"}
            else "log"
            if suffix in {".log", ".txt"}
            else "native"
        )
        artifacts.append(
            {
                "name": path.name,
                "category": category,
                "relative_path": _relative_to_data_dir(settings, path),
                "size_bytes": path.stat().st_size,
                "previewable": category == "plot",
            }
        )
    return artifacts


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
    with factory() as session:
        job = session.get(Job, job_id)
        run = session.get(TrainingRun, run_id)
        if job is None or run is None:
            return
        if run.status in {"completed", "failed", "cancelled"}:
            return
        if job.status == "cancel_requested":
            cancellation_requested["value"] = True
            trainer.stop = True
        total = int(getattr(trainer, "epochs", run.progress_total_epochs) or 0)
        epoch = max(0, min(int(getattr(trainer, "epoch", 0)) + 1, total))
        if epoch <= run.progress_epoch:
            return
        history = _read_results_csv(Path(str(trainer.csv)))
        last_metrics = _last_metrics(history)
        run.progress_epoch = epoch
        run.progress_total_epochs = total
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
        if run.status in {"completed", "failed", "cancelled"}:
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


def _collect_training_results(
    settings: Settings,
    run: TrainingRun,
    job: Job,
    save_dir: Path,
    results_csv: Path,
    *,
    tuning_enabled: bool = False,
) -> None:
    weights_dir = save_dir / "weights"
    best_ckpt = weights_dir / "best.pt"
    last_ckpt = weights_dir / "last.pt"
    history = {} if tuning_enabled else _read_results_csv(results_csv)
    native_results_rows = _read_results_table(results_csv)
    tuning_trials = normalize_tuning_csv(results_csv) if tuning_enabled else []
    selected_trial = best_trial(tuning_trials)
    last_metrics = (
        dict(selected_trial.get("metrics", {})) if selected_trial else _last_metrics(history)
    )
    artifacts = _discover_training_artifacts(settings, save_dir)
    if tuning_enabled:
        run.progress_epoch = len(tuning_trials)
        run.progress_total_epochs = int(
            dict(run.tuning_config_json).get("max_trials", len(tuning_trials))
        )
        job.progress_current = len(tuning_trials)
        job.progress_total = run.progress_total_epochs
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
        "native_results_rows": native_results_rows,
        "tuning_results": {
            "fitness_definition": FITNESS_DEFINITION,
            "search_space": dict(run.tuning_config_json).get("search_space", {}),
            "max_trials": dict(run.tuning_config_json).get("max_trials"),
            "epochs_per_trial": dict(run.tuning_config_json).get("epochs_per_trial"),
            "patience": dict(run.tuning_config_json).get("patience"),
            "trials": tuning_trials,
            "best_trial_number": selected_trial.get("trial_number") if selected_trial else None,
            "best_hyperparameters": selected_trial.get("hyperparameters", {})
            if selected_trial
            else {},
        }
        if tuning_enabled
        else None,
        "artifacts": artifacts,
    }
    run.result_checkpoint_path = (
        _relative_to_data_dir(settings, best_ckpt)
        if best_ckpt.is_file()
        else _relative_to_data_dir(settings, last_ckpt)
        if last_ckpt.is_file()
        else None
    )
