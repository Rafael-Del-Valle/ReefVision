"""In-process and standalone background worker."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import BackupRecord, ImageAsset, Job, QualityControlRun
from reefvision.jobs.backups import process_backup_job
from reefvision.jobs.classification_inference import process_classification_inference_job
from reefvision.jobs.classification_snapshot_evaluation import (
    process_classification_snapshot_evaluation_job,
)
from reefvision.jobs.depth import process_depth_map_job
from reefvision.jobs.diagnostics import process_diagnostics_job
from reefvision.jobs.export import process_export_job
from reefvision.jobs.image_embeddings import process_image_embedding_job
from reefvision.jobs.inference import process_inference_job
from reefvision.jobs.model_install import process_model_install_job
from reefvision.jobs.project_archives import (
    process_project_archive_export_job,
    process_project_archive_import_job,
    process_project_duplicate_job,
    process_project_storage_migration_job,
)
from reefvision.jobs.provider_benchmarks import process_provider_benchmark_job
from reefvision.jobs.quality_control import process_quality_control_job
from reefvision.jobs.restores import process_restore_job
from reefvision.jobs.sam2_video import process_sam2_video_propagation_job
from reefvision.jobs.training_dispatch import process_task_aware_training_job
from reefvision.jobs.video import process_video_extract_job
from reefvision.jobs.video_exports import process_video_render_export_job
from reefvision.jobs.video_tracking import process_video_tracking_job
from reefvision.jobs.workflow_consensus import process_workflow_run_job
from reefvision.jobs import workflow_sam2_refiners as _workflow_sam2_refiners  # noqa: F401
from reefvision.repositories.jobs import JobRepository
from reefvision.storage.images import create_thumbnail
from reefvision.storage.projects import resolve_managed_project_path

LOGGER = logging.getLogger("reefvision.worker")


def recover_interrupted_jobs(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        count = JobRepository(session).recover_interrupted_jobs()
        for run in session.scalars(
            select(QualityControlRun).where(
                QualityControlRun.status.in_(("running", "cancel_requested"))
            )
        ):
            run.status = "queued"
            run.error_message = "Recovered after interruption"
            run.started_at = None
        for backup in session.scalars(
            select(BackupRecord).where(BackupRecord.status.in_(("running", "verifying")))
        ):
            backup.status = "queued"
            backup.error_message = "Recovered after interruption"
            backup.started_at = None
        session.commit()
        return count


def _fail_job(factory: sessionmaker[Session], job_id: str, message: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = datetime.now(UTC)
        session.commit()


def process_thumbnail_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "thumbnail" or job.status != "queued":
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        session.commit()
        request = dict(job.request_json)

    try:
        image_id = str(request["image_id"])
        source_relative = str(request["source_path"])
        thumbnail_relative = str(request["thumbnail_path"])
        source = resolve_managed_project_path(settings, source_relative)
        destination = resolve_managed_project_path(settings, thumbnail_relative)
        if not source.is_file():
            raise FileNotFoundError(f"Managed source image is missing: {source_relative}")
        create_thumbnail(
            source,
            destination,
            max_width=settings.thumbnail_max_width,
            max_height=settings.thumbnail_max_height,
        )
        with factory() as session:
            job = session.get(Job, job_id)
            image = session.get(ImageAsset, image_id)
            if job is None or image is None:
                destination.unlink(missing_ok=True)
                raise RuntimeError("Thumbnail job references missing database records")
            image.thumbnail_path = thumbnail_relative
            job.status = "succeeded"
            job.progress_current = 1
            job.result_json = {"thumbnail_path": thumbnail_relative}
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        _fail_job(factory, job_id, str(exc))
        return False


def process_next_thumbnail_job(
    settings: Settings,
    factory: sessionmaker[Session],
    worker_id: str | None = None,
) -> bool:
    with factory() as session:
        job = JobRepository(session).next_queued(worker_id)
        job_id = job.id if job is not None else None
        job_type = job.job_type if job is not None else None
    if job_id is None:
        return False

    try:
        processors = {
            "thumbnail": process_thumbnail_job,
            "inference": process_inference_job,
            "classification_inference": process_classification_inference_job,
            "classification_snapshot_evaluation": process_classification_snapshot_evaluation_job,
            "export": process_export_job,
            "qc": process_quality_control_job,
            "backup": process_backup_job,
            "restore": process_restore_job,
            "diagnostics": process_diagnostics_job,
            "training": process_task_aware_training_job,
            "model_install": process_model_install_job,
            "video_extract": process_video_extract_job,
            "video_track": process_video_tracking_job,
            "video_render_export": process_video_render_export_job,
            "depth_map": process_depth_map_job,
            "image_embeddings": process_image_embedding_job,
            "workflow_run": process_workflow_run_job,
            "provider_benchmark": process_provider_benchmark_job,
            "sam2_video_propagation": process_sam2_video_propagation_job,
            "project_archive_export": process_project_archive_export_job,
            "project_archive_import": process_project_archive_import_job,
            "project_duplicate": process_project_duplicate_job,
            "project_storage_migration": process_project_storage_migration_job,
        }
        processor = processors.get(str(job_type))
        if processor is not None:
            return processor(settings, factory, job_id)

        message = f"Unsupported queued job type: {job_type}"
        _fail_job(factory, job_id, message)
        LOGGER.error(
            message,
            extra={
                "event_id": "background_job_unsupported",
                "component": "worker",
                "job_id": job_id,
                "job_type": job_type,
            },
        )
        return True
    except Exception as exc:
        _fail_job(factory, job_id, f"Unexpected background job failure: {exc}")
        LOGGER.exception(
            "Background job failed unexpectedly",
            extra={
                "event_id": "background_job_unexpected_failure",
                "component": "background_worker",
                "job_id": job_id,
                "job_type": job_type,
            },
        )
        return True


async def _worker_slot(
    settings: Settings,
    factory: sessionmaker[Session],
    stop_event: asyncio.Event,
    slot_index: int,
) -> None:
    worker_id = f"desktop-{os.getpid()}-slot-{slot_index}"
    while not stop_event.is_set():
        try:
            processed = await asyncio.to_thread(
                process_next_thumbnail_job,
                settings,
                factory,
                worker_id,
            )
        except Exception:
            LOGGER.exception(
                "Background worker iteration failed",
                extra={
                    "event_id": "background_worker_iteration_failure",
                    "component": "background_worker",
                    "worker_id": worker_id,
                },
            )
            processed = False
        if not processed:
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings.worker_poll_seconds,
                )


async def thumbnail_worker_loop(
    settings: Settings,
    factory: sessionmaker[Session],
    stop_event: asyncio.Event,
) -> None:
    recover_interrupted_jobs(factory)
    slots = [
        asyncio.create_task(_worker_slot(settings, factory, stop_event, index))
        for index in range(settings.worker_concurrency)
    ]
    try:
        await asyncio.gather(*slots)
    finally:
        for slot in slots:
            slot.cancel()
        await asyncio.gather(*slots, return_exceptions=True)
