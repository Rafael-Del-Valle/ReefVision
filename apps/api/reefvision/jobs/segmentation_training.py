"""Background Ultralytics instance-segmentation training execution."""
# mypy: disable-error-code="attr-defined"

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
    _resolve_model_source,
)
from reefvision.ml.dependencies import (
    configure_provider_runtime,
    require_provider_ready,
)
from reefvision.ml.providers import resolve_torch_device
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.segmentation_exports import (
    write_yolo_segmentation_export,
)

SEGMENTATION_TASK = "segment"


def process_segmentation_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    """Execute one queued polygon instance-segmentation training run."""

    dataset_output_path: str | None = None
    run_id: str | None = None
    with factory() as session:
        job = session.get(Job, job_id)
        if (
            job is None
            or job.job_type != "training"
            or job.status != "queued"
        ):
            return False
        run_id = str(job.request_json["training_run_id"])
        run = session.get(TrainingRun, run_id)
        if run is None:
            job.status = "failed"
            job.error_message = "Training run is missing"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        if run.task != SEGMENTATION_TASK:
            return False
        run.status = "preflight"
        run.stage = "preflight"
        run.started_at = datetime.now(UTC)
        run.error_message = None
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        job.result_json = {
            "stage": "preflight",
            "task": SEGMENTATION_TASK,
        }
        session.commit()

    try:
        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None:
                raise RuntimeError("Training run or job is missing")
            if run.dataset_version_id is None:
                raise RuntimeError(
                    "Training run is missing its dataset version"
                )
            project = session.get(Project, run.project_id)
            version_row = session.get(
                DatasetVersion,
                run.dataset_version_id,
            )
            if project is None or version_row is None:
                raise RuntimeError(
                    "Training run references missing project or dataset version"
                )
            if run.task != SEGMENTATION_TASK:
                raise RuntimeError(
                    "Segmentation worker received a non-segmentation training run"
                )
            if (
                dict(run.tuning_config_json).get("mode", "disabled")
                != "disabled"
            ):
                raise RuntimeError(
                    "Segmentation tuning execution is not implemented"
                )
            if dict(run.tiling_config_json).get("mode", "none") != "none":
                raise RuntimeError(
                    "The segmentation training executor launches only the "
                    "no-tiling baseline"
                )
            require_provider_ready(run.provider_id, settings)

            run.status = "preparing_dataset"
            run.stage = "preparing_dataset"
            job.result_json = {
                "stage": "preparing_dataset",
                "task": SEGMENTATION_TASK,
            }
            session.commit()

            items = list(
                session.scalars(
                    select(DatasetVersionItem)
                    .where(
                        DatasetVersionItem.dataset_version_id
                        == version_row.id
                    )
                    .order_by(
                        DatasetVersionItem.split,
                        DatasetVersionItem.original_filename,
                        DatasetVersionItem.image_id,
                    )
                )
            )
            images = list(
                session.scalars(
                    select(ImageAsset).where(
                        ImageAsset.id.in_(
                            [item.image_id for item in items]
                        )
                    )
                )
            )
            image_paths = {
                image.id: resolve_managed_project_path(
                    settings,
                    image.managed_path,
                )
                for image in images
            }
            for image_id, path in image_paths.items():
                if not path.is_file():
                    raise FileNotFoundError(
                        "Managed source image is missing for training: "
                        f"{image_id}"
                    )

            base_relative = f"{project.storage_root}/training/{run.id}"
            dataset_output_path = f"{base_relative}/dataset"
            dataset_manifest_path = (
                f"{base_relative}/dataset-manifest.json"
            )
            dataset_archive_path = f"{base_relative}/dataset.zip"
            dataset_root = resolve_managed_project_path(
                settings,
                dataset_output_path,
            )
            shutil.rmtree(dataset_root, ignore_errors=True)
            dataset_archive = resolve_managed_project_path(
                settings,
                dataset_archive_path,
            )
            dataset_archive.unlink(missing_ok=True)
            export_result = write_yolo_segmentation_export(
                settings,
                export_id=run.id,
                version=version_row,
                items=items,
                image_paths=image_paths,
                output_path=dataset_output_path,
                manifest_path=dataset_manifest_path,
                archive_path=dataset_archive_path,
            )
            if int(export_result.get("polygon_count", 0)) <= 0:
                raise RuntimeError(
                    "The immutable dataset export contains no polygon masks "
                    "for segmentation"
                )

            save_root_relative = f"{base_relative}/ultralytics"
            save_root = resolve_managed_project_path(
                settings,
                save_root_relative,
            )
            shutil.rmtree(save_root, ignore_errors=True)
            save_root.mkdir(parents=True, exist_ok=True)
            logs_path = save_root / "training.log"
            _append_log(
                logs_path,
                (
                    f"[{datetime.now(UTC).isoformat()}] polygon "
                    "segmentation dataset prepared"
                ),
            )

            checkpoint_source = _resolve_model_source(
                settings,
                session,
                run,
            )
            configure_provider_runtime(settings)
            run.status = "training"
            run.stage = "training"
            run.logs_path = _relative_to_data_dir(settings, logs_path)
            run.artifact_manifest_json = {
                "task": SEGMENTATION_TASK,
                "dataset_format": "yolo_segmentation",
                "dataset_output_path": dataset_output_path,
                "dataset_manifest_path": dataset_manifest_path,
                "dataset_archive_path": dataset_archive_path,
                "dataset_export_result": export_result,
                "mask_metrics_preserved": True,
            }
            job.result_json = {
                "stage": "training",
                "task": SEGMENTATION_TASK,
                "dataset_output_path": dataset_output_path,
            }
            session.commit()

        from ultralytics import YOLO

        cancellation_requested = {"value": False}
        model = YOLO(checkpoint_source)
        model.add_callback(
            "on_fit_epoch_end",
            lambda trainer: _on_fit_epoch_end(
                settings,
                factory,
                job_id,
                run_id,
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
                run_id,
                trainer,
            ),
        )
        model.add_callback(
            "on_train_end",
            lambda trainer: _on_train_end(
                settings,
                factory,
                job_id,
                run_id,
                trainer,
            ),
        )

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise RuntimeError(
                    "Training run disappeared before launch"
                )
            train_args = dict(run.training_config_json)
            device = resolve_torch_device(run.device)
            train_args["amp"] = run.precision == "amp"
            if run.random_seed is not None:
                train_args["seed"] = run.random_seed
            train_args.update(
                {
                    "data": str(
                        resolve_managed_project_path(
                            settings,
                            dataset_output_path,
                        )
                        / "data.yaml"
                    ),
                    "device": device,
                    "project": str(
                        resolve_managed_project_path(
                            settings,
                            f"{base_relative}/runs",
                        )
                    ),
                    "name": SEGMENTATION_TASK,
                    "exist_ok": True,
                    "save": True,
                    "verbose": False,
                }
            )
            _append_log(
                resolve_managed_project_path(
                    settings,
                    run.logs_path or "",
                ),
                (
                    f"[{datetime.now(UTC).isoformat()}] launching "
                    "Ultralytics segment training"
                ),
            )

        model.train(**train_args)

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None:
                raise RuntimeError(
                    "Training run disappeared after execution"
                )
            trainer = model.trainer
            if trainer is None:
                raise RuntimeError(
                    "Ultralytics trainer unavailable after execution"
                )
            save_dir = Path(str(trainer.save_dir)).resolve()
            results_csv = save_dir / "results.csv"
            weights_dir = save_dir / "weights"
            best_ckpt = weights_dir / "best.pt"
            last_ckpt = weights_dir / "last.pt"
            history = _read_results_csv(results_csv)
            last_metrics = _last_metrics(history)
            mask_metrics = {
                key: value
                for key, value in last_metrics.items()
                if "(M)" in key
                or "mask" in key.casefold()
                or "seg" in key.casefold()
            }
            run.metrics_history_json = history
            run.metrics_json = last_metrics
            run.artifact_manifest_json = {
                **dict(run.artifact_manifest_json),
                "run_save_dir": _relative_to_data_dir(
                    settings,
                    save_dir,
                ),
                "results_csv": (
                    _relative_to_data_dir(settings, results_csv)
                    if results_csv.is_file()
                    else None
                ),
                "best_checkpoint_path": (
                    _relative_to_data_dir(settings, best_ckpt)
                    if best_ckpt.is_file()
                    else None
                ),
                "last_checkpoint_path": (
                    _relative_to_data_dir(settings, last_ckpt)
                    if last_ckpt.is_file()
                    else None
                ),
                "mask_metrics": mask_metrics,
            }
            run.result_checkpoint_path = (
                _relative_to_data_dir(settings, best_ckpt)
                if best_ckpt.is_file()
                else _relative_to_data_dir(settings, last_ckpt)
                if last_ckpt.is_file()
                else None
            )
            if (
                cancellation_requested["value"]
                or job.status == "cancel_requested"
            ):
                job.status = "cancelled"
                run.status = "cancelled"
                run.stage = "cancelled"
                _append_log(
                    resolve_managed_project_path(
                        settings,
                        run.logs_path or "",
                    ),
                    (
                        f"[{datetime.now(UTC).isoformat()}] segmentation "
                        "training cancelled"
                    ),
                )
            else:
                job.status = "succeeded"
                job.progress_current = max(job.progress_total, 1)
                job.result_json = {
                    "stage": "completed",
                    "task": SEGMENTATION_TASK,
                    "metrics": last_metrics,
                    "mask_metrics": mask_metrics,
                    "result_checkpoint_path": run.result_checkpoint_path,
                }
                run.status = "completed"
                run.stage = "completed"
                experiment = ExperimentRecord(
                    project_id=run.project_id,
                    training_run_id=run.id,
                    dataset_version_id=run.dataset_version_id,
                    dataset_manifest_sha256=(
                        run.dataset_manifest_sha256
                    ),
                    split_manifest_sha256=run.split_manifest_sha256,
                    task=run.task,
                    provider_id=run.provider_id,
                    architecture=run.architecture,
                    summary_metrics_json=last_metrics,
                    comparison_warnings_json=list(run.warnings_json),
                    artifact_manifest_json=dict(
                        run.artifact_manifest_json
                    ),
                    package_versions_json=_package_versions_snapshot(),
                )
                session.add(experiment)
                _append_log(
                    resolve_managed_project_path(
                        settings,
                        run.logs_path or "",
                    ),
                    (
                        f"[{datetime.now(UTC).isoformat()}] segmentation "
                        "training completed"
                    ),
                )
            run.completed_at = datetime.now(UTC)
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            run = (
                session.get(TrainingRun, run_id)
                if run_id is not None
                else None
            )
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
                            resolve_managed_project_path(
                                settings,
                                run.logs_path,
                            ),
                            (
                                f"[{datetime.now(UTC).isoformat()}] "
                                f"failure: {exc}"
                            ),
                        )
            session.commit()
        return False
