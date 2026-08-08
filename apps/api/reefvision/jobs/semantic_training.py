"""Background nnU-Net semantic-segmentation training execution."""

from __future__ import annotations

import json
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
    _package_versions_snapshot,
    _relative_to_data_dir,
)
from reefvision.ml.semantic_segmentation import (
    SEMANTIC_SEGMENTATION_TASK,
    SemanticClassDefinition,
    SemanticDatasetContract,
    SemanticTrainingRequest,
    semantic_provider_for_name,
)
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.segmentation_exports import write_semantic_mask_export


def _classes(path: Path) -> tuple[SemanticClassDefinition, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_classes = payload.get("classes")
    if not isinstance(raw_classes, list):
        raise RuntimeError("Semantic dataset classes metadata is invalid")
    return tuple(
        SemanticClassDefinition(
            class_index=int(item["class_index"]),
            pixel_value=int(item["pixel_value"]),
            class_name=str(item["name"]),
        )
        for item in raw_classes
        if isinstance(item, dict)
    )


def process_semantic_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    """Execute one queued semantic-segmentation training run."""

    run_id: str | None = None
    try:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None or job.job_type != "training" or job.status != "queued":
                return False
            run_id = str(job.request_json["training_run_id"])
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise RuntimeError("Training run is missing")
            if run.task != SEMANTIC_SEGMENTATION_TASK:
                return False
            run.status = "preflight"
            run.stage = "preflight"
            run.started_at = datetime.now(UTC)
            job.status = "running"
            job.started_at = datetime.now(UTC)
            job.result_json = {"stage": "preflight", "task": run.task}
            session.commit()

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None or run.dataset_version_id is None:
                raise RuntimeError("Semantic training references missing records")
            project = session.get(Project, run.project_id)
            version = session.get(DatasetVersion, run.dataset_version_id)
            if project is None or version is None:
                raise RuntimeError("Semantic training references a missing project or dataset")
            if dict(run.tuning_config_json).get("mode", "disabled") != "disabled":
                raise RuntimeError("Semantic tuning execution is not implemented")
            if dict(run.tiling_config_json).get("mode", "none") != "none":
                raise RuntimeError("ReefVision tiling must remain disabled for nnU-Net")

            run.status = "preparing_dataset"
            run.stage = "preparing_dataset"
            job.result_json = {"stage": "preparing_dataset", "task": run.task}
            session.commit()

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
            if any(not path.is_file() for path in image_paths.values()):
                raise FileNotFoundError("A managed source image is missing for semantic training")

            base = f"{project.storage_root}/training/{run.id}"
            dataset_relative = f"{base}/semantic-dataset"
            manifest_relative = f"{base}/semantic-dataset-manifest.json"
            archive_relative = f"{base}/semantic-dataset.zip"
            dataset_root = resolve_managed_project_path(settings, dataset_relative)
            shutil.rmtree(dataset_root, ignore_errors=True)
            resolve_managed_project_path(settings, archive_relative).unlink(missing_ok=True)
            export_result = write_semantic_mask_export(
                settings,
                export_id=run.id,
                version=version,
                items=items,
                image_paths=image_paths,
                output_path=dataset_relative,
                manifest_path=manifest_relative,
                archive_path=archive_relative,
            )
            classes_path = dataset_root / "classes.json"
            classes_payload = json.loads(classes_path.read_text(encoding="utf-8"))
            contract = SemanticDatasetContract(
                dataset_version_id=version.id,
                dataset_manifest_sha256=version.manifest_sha256,
                split_manifest_sha256=run.split_manifest_sha256,
                export_root=dataset_root,
                images_root=dataset_root / "images",
                masks_root=dataset_root / "masks",
                classes_file=classes_path,
                classes=_classes(classes_path),
                background_pixel_value=int(classes_payload.get("background_pixel_value", 0)),
                overlap_policy=str(classes_payload.get("overlap_policy", "")),
            )
            workspace_relative = f"{base}/nnunet"
            workspace = resolve_managed_project_path(settings, workspace_relative)
            log_relative = f"{workspace_relative}/training.log"
            log_path = resolve_managed_project_path(settings, log_relative)
            _append_log(log_path, "Semantic dataset prepared")

            run.status = "training"
            run.stage = "training"
            run.logs_path = log_relative
            run.artifact_manifest_json = {
                "task": run.task,
                "dataset_format": "semantic_masks",
                "dataset_output_path": dataset_relative,
                "dataset_manifest_path": manifest_relative,
                "dataset_archive_path": archive_relative,
                "dataset_export_result": export_result,
                "workspace_root": workspace_relative,
            }
            job.result_json = {
                "stage": "training",
                "task": run.task,
                "dataset_output_path": dataset_relative,
            }
            request = SemanticTrainingRequest(
                run_id=run.id,
                project_id=run.project_id,
                dataset=contract,
                device=run.device,
                precision=run.precision,
                random_seed=run.random_seed,
                training_config=dict(run.training_config_json),
                resource_limits=dict(run.resource_limits_json),
                workspace_root=workspace,
                log_path=log_path,
            )
            provider_id = run.provider_id
            session.commit()

        result = semantic_provider_for_name(provider_id).train(request)

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None:
                raise RuntimeError("Semantic training run disappeared")
            if job.status == "cancel_requested":
                job.status = "cancelled"
                run.status = "cancelled"
                run.stage = "cancelled"
            else:
                checkpoint = _relative_to_data_dir(settings, result.checkpoint_path)
                run.metrics_json = dict(result.metrics)
                run.metrics_history_json = dict(result.metrics_history)
                run.result_checkpoint_path = checkpoint
                run.artifact_manifest_json = {
                    **dict(run.artifact_manifest_json),
                    **dict(result.artifact_manifest),
                    "provider_version": result.provider_version,
                    "semantic_model_bundle": checkpoint,
                }
                run.status = "completed"
                run.stage = "completed"
                job.status = "succeeded"
                job.progress_current = max(job.progress_total, 1)
                job.result_json = {
                    "stage": "completed",
                    "task": run.task,
                    "metrics": dict(result.metrics),
                    "result_checkpoint_path": checkpoint,
                }
                packages = _package_versions_snapshot()
                packages["nnunetv2"] = result.provider_version
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
                        summary_metrics_json=dict(result.metrics),
                        comparison_warnings_json=list(run.warnings_json),
                        artifact_manifest_json=dict(run.artifact_manifest_json),
                        package_versions_json=packages,
                    )
                )
                _append_log(
                    resolve_managed_project_path(settings, run.logs_path or ""),
                    "Semantic training completed",
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
                job.result_json = {
                    "stage": "failed",
                    "task": SEMANTIC_SEGMENTATION_TASK,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
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
                            f"Semantic training failed: {exc}",
                        )
            session.commit()
        return False
