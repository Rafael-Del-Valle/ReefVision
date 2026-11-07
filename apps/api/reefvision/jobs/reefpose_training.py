"""Native ReefPose-S training from immutable ReefVision pose truth."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
from sqlalchemy.orm import Session, sessionmaker
from torch.utils.data import DataLoader

from reefvision.config import Settings
from reefvision.db.models import Job, PoseTrainingDataset, Project, TrainingRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.training import _complete_training_run, _relative_to_data_dir
from reefvision.ml.reefpose.checkpoints import load_checkpoint
from reefvision.ml.reefpose.data import ReefPoseDataset, load_reefvision_pose_export
from reefvision.ml.reefpose.errors import ReefPoseCancelledError
from reefvision.ml.reefpose.model import ReefPoseConfig, ReefPoseS
from reefvision.ml.reefpose.training import ReefPoseTrainer, ReefPoseTrainingConfig
from reefvision.services.pose_training_exports import PoseTrainingExportService
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path


def _dataset_for_run(
    session: Session,
    *,
    run: TrainingRun,
    dataset_id: str,
    role: str,
) -> PoseTrainingDataset:
    dataset = session.get(PoseTrainingDataset, dataset_id)
    if dataset is None or dataset.project_id != run.project_id:
        raise ValidationError(f"Pose {role} dataset is unavailable")
    if dataset.status != "complete":
        raise ValidationError(f"Pose {role} dataset must remain complete")
    manifest = dict(run.artifact_manifest_json or {})
    expected_id = manifest.get(f"pose_{role}_dataset_id")
    expected_sha = manifest.get(f"pose_{role}_dataset_manifest_sha256")
    if expected_id is not None and expected_id != dataset.id:
        raise ValidationError(f"Pose {role} dataset identity changed before execution")
    if role == "training" and dataset.manifest_sha256 != run.dataset_manifest_sha256:
        raise ValidationError("Pose training dataset manifest changed before execution")
    if expected_sha is not None and expected_sha != dataset.manifest_sha256:
        raise ValidationError(f"Pose {role} dataset manifest changed before execution")
    if (
        dataset.pose_schema_id != manifest.get("pose_schema_id")
        or dataset.pose_schema_revision != manifest.get("pose_schema_revision")
        or dataset.pose_schema_content_hash != manifest.get("pose_schema_content_hash")
    ):
        raise ValidationError(f"Pose {role} landmark schema changed before execution")
    return dataset


def _validate_bundle(bundle: Any, dataset: PoseTrainingDataset, *, role: str) -> None:
    if bundle.dataset_manifest_sha256 != dataset.manifest_sha256:
        raise ValidationError(f"Pose {role} export dataset checksum does not match frozen truth")
    if bundle.source_schema_content_hash != dataset.pose_schema_content_hash:
        raise ValidationError(f"Pose {role} export landmark schema does not match frozen truth")


def _metrics_history(rows: list[dict[str, float]]) -> dict[str, list[float | int]]:
    history: dict[str, list[float | int]] = {"epoch": []}
    for index, row in enumerate(rows, start=1):
        history["epoch"].append(index)
        for key, value in row.items():
            history.setdefault(key, []).append(float(value))
    return history


def _record_interrupted_checkpoint(
    settings: Settings,
    run: TrainingRun,
    work_output_dir: Path,
    managed_output_dir: Path,
) -> None:
    checkpoint = work_output_dir / "cancelled.pt"
    if not checkpoint.is_file():
        checkpoint = work_output_dir / "last.pt"
    if checkpoint.is_file():
        managed_output_dir.mkdir(parents=True, exist_ok=True)
        persisted = managed_output_dir / checkpoint.name
        shutil.copy2(checkpoint, persisted)
        run.artifact_manifest_json = {
            **dict(run.artifact_manifest_json or {}),
            "resume_checkpoint_path": _relative_to_data_dir(settings, persisted),
        }


def process_reefpose_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    """Run one native ReefPose training child job."""

    run_id: str | None = None
    output_dir: Path | None = None
    managed_output_dir: Path | None = None
    extraction_root: Path | None = None
    work_root: Path | None = None
    try:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None or job.job_type != "training" or job.status != "queued":
                return False
            run_id = str(job.request_json.get("training_run_id") or "")
            run = session.get(TrainingRun, run_id)
            if run is None:
                job.status = "failed"
                job.error_message = "Pose training run is missing"
                job.completed_at = datetime.now(UTC)
                session.commit()
                return False
            if run.task != "pose" or run.provider_id != "reefpose":
                raise ValidationError(
                    "Native ReefPose trainer requires provider=reefpose and task=pose"
                )
            run.status = run.stage = "preflight"
            run.started_at = run.started_at or datetime.now(UTC)
            run.completed_at = None
            run.error_message = None
            job.status = "running"
            job.started_at = job.started_at or datetime.now(UTC)
            job.completed_at = None
            job.error_message = None
            job.result_json = {"stage": "preflight", "task": "pose", "provider_id": "reefpose"}
            session.commit()

        with factory() as session:
            job = session.get(Job, job_id)
            run = session.get(TrainingRun, run_id)
            if job is None or run is None:
                raise RuntimeError("ReefPose training run or job disappeared")
            project = session.get(Project, run.project_id)
            if project is None:
                raise ValidationError("Pose training project is unavailable")
            training_id = str(job.request_json.get("pose_training_dataset_id") or "")
            validation_id = str(job.request_json.get("pose_validation_dataset_id") or "") or None
            training_dataset = _dataset_for_run(
                session, run=run, dataset_id=training_id, role="training"
            )
            validation_dataset = (
                _dataset_for_run(session, run=run, dataset_id=validation_id, role="validation")
                if validation_id
                else None
            )
            if validation_dataset is not None and (
                validation_dataset.pose_schema_content_hash
                != training_dataset.pose_schema_content_hash
            ):
                raise ValidationError("Pose validation landmark schema does not match training")

            base_relative = f"{project.storage_root}/training/{run.id}/reefpose"
            native_root = resolve_managed_project_path(settings, base_relative)
            manifest = dict(run.artifact_manifest_json or {})
            resume_relative = str(manifest.get("resume_checkpoint_path") or "") or None
            if resume_relative is None:
                shutil.rmtree(native_root, ignore_errors=True)
            native_root.mkdir(parents=True, exist_ok=True)
            managed_output_dir = native_root / "checkpoints"
            managed_output_dir.mkdir(parents=True, exist_ok=True)
            work_root = Path(tempfile.mkdtemp(prefix="reefpose-run-"))
            output_dir = work_root / "checkpoints"
            output_dir.mkdir(parents=True, exist_ok=True)
            export_root = native_root / "exports"
            shutil.rmtree(export_root, ignore_errors=True)
            export_root.mkdir(parents=True, exist_ok=True)
            extraction_root = Path(tempfile.mkdtemp(prefix="reefpose-dataset-"))

            run.status = run.stage = "preparing_dataset"
            job.result_json = {
                "stage": "preparing_dataset",
                "task": "pose",
                "provider_id": "reefpose",
            }
            session.commit()

            exporter = PoseTrainingExportService(session, settings)
            training_export = exporter.export(training_dataset.id, "ultralytics_pose")
            training_archive = export_root / "training.zip"
            training_archive.write_bytes(training_export.content)
            training_bundle = load_reefvision_pose_export(
                training_archive, extraction_root / "training"
            )
            _validate_bundle(training_bundle, training_dataset, role="training")

            validation_export = None
            validation_bundle = None
            if validation_dataset is not None:
                validation_export = exporter.export(validation_dataset.id, "ultralytics_pose")
                validation_archive = export_root / "validation.zip"
                validation_archive.write_bytes(validation_export.content)
                validation_bundle = load_reefvision_pose_export(
                    validation_archive, extraction_root / "validation"
                )
                _validate_bundle(validation_bundle, validation_dataset, role="validation")
                if validation_bundle.schema.integrity_hash != training_bundle.schema.integrity_hash:
                    raise ValidationError("Pose validation anatomy differs from training anatomy")

            configuration = dict(run.training_config_json or {})
            training_data = ReefPoseDataset(
                training_bundle.records,
                training_bundle.schema,
                input_height=int(configuration["input_height"]),
                input_width=int(configuration["input_width"]),
                heatmap_sigma=float(configuration["heatmap_sigma"]),
            )
            validation_data = (
                ReefPoseDataset(
                    validation_bundle.records,
                    validation_bundle.schema,
                    input_height=int(configuration["input_height"]),
                    input_width=int(configuration["input_width"]),
                    heatmap_sigma=float(configuration["heatmap_sigma"]),
                )
                if validation_bundle is not None
                else None
            )
            generator = torch.Generator().manual_seed(run.random_seed or 1337)
            training_loader = DataLoader(
                training_data,
                batch_size=int(configuration["batch"]),
                shuffle=True,
                num_workers=int(configuration["workers"]),
                generator=generator,
            )
            validation_loader = (
                DataLoader(
                    validation_data,
                    batch_size=int(configuration["batch"]),
                    shuffle=False,
                    num_workers=int(configuration["workers"]),
                )
                if validation_data is not None
                else None
            )

            resume_from = (
                resolve_managed_project_path(settings, resume_relative)
                if resume_relative is not None
                else None
            )
            if resume_from is None and run.initial_checkpoint_model_id:
                from reefvision.services.workflow_pose_training import _seed_pose_model

                seed_model = _seed_pose_model(
                    session,
                    settings,
                    project_id=run.project_id,
                    payload={"model_id": run.initial_checkpoint_model_id},
                    dataset=training_dataset,
                    provider_id="reefpose",
                )
                resume_from = resolve_managed_project_path(settings, seed_model.managed_path)

            if resume_from is not None:
                short_resume = output_dir / resume_from.name
                shutil.copy2(resume_from, short_resume)
                source_best = resume_from.with_name("best.pt")
                if source_best.is_file() and source_best != resume_from:
                    shutil.copy2(source_best, output_dir / "best.pt")
                resume_from = short_resume
                state = load_checkpoint(
                    resume_from,
                    device="cpu",
                    expected_schema_hash=training_bundle.schema.integrity_hash,
                )
                model = state.model
                expected = ReefPoseConfig(
                    num_keypoints=training_bundle.schema.keypoint_count,
                    input_height=int(configuration["input_height"]),
                    input_width=int(configuration["input_width"]),
                    base_channels=int(configuration["base_channels"]),
                    fpn_channels=configuration["fpn_channels"],
                )
                if model.config != expected:
                    raise ValidationError("ReefPose resume checkpoint model configuration changed")
            else:
                model = ReefPoseS(
                    ReefPoseConfig(
                        num_keypoints=training_bundle.schema.keypoint_count,
                        input_height=int(configuration["input_height"]),
                        input_width=int(configuration["input_width"]),
                        base_channels=int(configuration["base_channels"]),
                        fpn_channels=configuration["fpn_channels"],
                    )
                )

            trainer = ReefPoseTrainer(
                model,
                training_bundle.schema,
                ReefPoseTrainingConfig(
                    epochs=int(configuration["epochs"]),
                    learning_rate=float(configuration["learning_rate"]),
                    weight_decay=float(configuration["weight_decay"]),
                    device=run.device,
                    amp=run.precision == "amp",
                    seed=run.random_seed or 1337,
                    output_dir=output_dir,
                    gradient_clip_norm=configuration["gradient_clip_norm"],
                    deterministic=bool(configuration["deterministic"]),
                ),
            )
            run.status = run.stage = "training"
            run.logs_path = _relative_to_data_dir(settings, managed_output_dir / "training.jsonl")
            run.artifact_manifest_json = {
                **dict(run.artifact_manifest_json or {}),
                "initialization_mode": (
                    "registered_model" if run.initial_checkpoint_model_id else "random"
                ),
                "effective_precision": "amp" if trainer.amp_enabled else "fp32",
                "pretrained": False,
                "task": "pose",
                "provider_id": "reefpose",
                "dataset_format": "ultralytics_pose",
                "pose_training_dataset_manifest_sha256": training_dataset.manifest_sha256,
                "pose_validation_dataset_manifest_sha256": (
                    validation_dataset.manifest_sha256 if validation_dataset is not None else None
                ),
                "training_export_bundle_sha256": training_export.bundle_sha256,
                "validation_export_bundle_sha256": (
                    validation_export.bundle_sha256 if validation_export is not None else None
                ),
                "validation_mode": (
                    "separate_frozen_pose_dataset" if validation_dataset is not None else "none"
                ),
                "dataset_materialization": "temporary_verified_extraction",
                "reproducibility": dict(trainer.reproducibility),
            }
            job.result_json = {
                "stage": "training",
                "task": "pose",
                "provider_id": "reefpose",
            }
            session.commit()

        def cancellation_check() -> bool:
            with factory() as callback_session:
                callback_job = callback_session.get(Job, job_id)
                return callback_job is None or callback_job.status == "cancel_requested"

        def report_epoch(epoch: int, total: int, metrics: dict[str, float]) -> None:
            with factory() as callback_session:
                callback_run = callback_session.get(TrainingRun, run_id)
                callback_job = callback_session.get(Job, job_id)
                if callback_run is None or callback_job is None:
                    raise RuntimeError("ReefPose progress target disappeared")
                history = dict(callback_run.metrics_history_json or {})
                history.setdefault("epoch", []).append(epoch)
                for key, value in metrics.items():
                    history.setdefault(key, []).append(float(value))
                callback_run.metrics_json = dict(metrics)
                callback_run.metrics_history_json = history
                callback_run.progress_epoch = epoch
                callback_run.progress_total_epochs = total
                callback_job.progress_current = epoch
                callback_job.progress_total = total
                callback_job.result_json = {
                    "stage": "training",
                    "task": "pose",
                    "provider_id": "reefpose",
                    "metrics": dict(metrics),
                }
                callback_session.commit()

        result = trainer.fit(
            training_loader,
            validation_batches=validation_loader,
            cancellation_check=cancellation_check,
            resume_from=resume_from,
            epoch_callback=report_epoch,
        )

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None:
                raise RuntimeError("ReefPose training run disappeared after execution")
            if job.status == "cancel_requested":
                raise ReefPoseCancelledError("ReefPose training was cancelled")
            if managed_output_dir is None:
                raise RuntimeError("ReefPose managed checkpoint directory is unavailable")
            managed_best = managed_output_dir / "best.pt"
            managed_last = managed_output_dir / "last.pt"
            shutil.copy2(result.best_checkpoint, managed_best)
            shutil.copy2(result.last_checkpoint, managed_last)
            if trainer.log_path.is_file():
                shutil.copy2(trainer.log_path, managed_output_dir / "training.jsonl")
            best_relative = _relative_to_data_dir(settings, managed_best)
            last_relative = _relative_to_data_dir(settings, managed_last)
            best_sha256, best_size = hash_model_file(managed_best)
            run.result_checkpoint_path = best_relative
            run.metrics_json = dict(result.metrics_history[-1])
            run.metrics_history_json = _metrics_history(result.metrics_history)
            run.progress_epoch = result.completed_epochs
            run.progress_total_epochs = int(run.training_config_json["epochs"])
            run.artifact_manifest_json = {
                **dict(run.artifact_manifest_json or {}),
                "best_checkpoint_path": best_relative,
                "best_checkpoint_sha256": best_sha256,
                "best_checkpoint_size_bytes": best_size,
                "last_checkpoint_path": last_relative,
                "native_results_rows": list(result.metrics_history),
                "artifacts": [
                    {
                        "name": "best.pt",
                        "category": "checkpoint",
                        "relative_path": best_relative,
                        "sha256": best_sha256,
                    },
                    {
                        "name": "last.pt",
                        "category": "checkpoint",
                        "relative_path": last_relative,
                    },
                ],
            }
            _complete_training_run(session, run, job)
            session.commit()
        if extraction_root is not None:
            shutil.rmtree(extraction_root, ignore_errors=True)
        if work_root is not None:
            shutil.rmtree(work_root, ignore_errors=True)
        return True
    except ReefPoseCancelledError as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            run = session.get(TrainingRun, run_id) if run_id else None
            now = datetime.now(UTC)
            if run is not None:
                if output_dir is not None and managed_output_dir is not None:
                    _record_interrupted_checkpoint(settings, run, output_dir, managed_output_dir)
                    log_path = output_dir / "training.jsonl"
                    if log_path.is_file():
                        shutil.copy2(log_path, managed_output_dir / "training.jsonl")
                run.result_checkpoint_path = None
                run.status = run.stage = "cancelled"
                run.error_message = str(exc)
                run.completed_at = now
            if job is not None:
                job.status = "cancelled"
                job.error_message = str(exc)
                job.completed_at = now
                job.result_json = {**dict(job.result_json or {}), "stage": "cancelled"}
            session.commit()
        if extraction_root is not None:
            shutil.rmtree(extraction_root, ignore_errors=True)
        if work_root is not None:
            shutil.rmtree(work_root, ignore_errors=True)
        return True
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            run = session.get(TrainingRun, run_id) if run_id else None
            now = datetime.now(UTC)
            if run is not None:
                if output_dir is not None and managed_output_dir is not None:
                    with suppress(Exception):
                        _record_interrupted_checkpoint(
                            settings, run, output_dir, managed_output_dir
                        )
                        log_path = output_dir / "training.jsonl"
                        if log_path.is_file():
                            shutil.copy2(log_path, managed_output_dir / "training.jsonl")
                run.result_checkpoint_path = None
                run.status = run.stage = "failed"
                run.error_message = str(exc)
                run.completed_at = now
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = now
                job.result_json = {**dict(job.result_json or {}), "stage": "failed"}
            session.commit()
        if extraction_root is not None:
            shutil.rmtree(extraction_root, ignore_errors=True)
        if work_root is not None:
            shutil.rmtree(work_root, ignore_errors=True)
        return False
