"""In-process and standalone thumbnail worker."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    BackupRecord,
    ImageAsset,
    Job,
    QualityControlRun,
    VideoAsset,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.jobs.backups import process_backup_job
from reefvision.jobs.classification_inference import process_classification_inference_job
from reefvision.jobs.classification_training import process_classification_training_job
from reefvision.jobs.diagnostics import process_diagnostics_job
from reefvision.jobs.export import process_export_job
from reefvision.jobs.inference import process_inference_job
from reefvision.jobs.model_install import process_model_install_job
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.quality_control import process_quality_control_job
from reefvision.jobs.restores import process_restore_job
from reefvision.jobs.sam_image_proposals import process_sam_image_proposals_job
from reefvision.jobs.training import recover_training_run
from reefvision.jobs.training_dispatch import process_task_aware_training_job
from reefvision.jobs.video import process_video_extract_job
from reefvision.jobs.video_annotated_export import process_video_annotated_export_job
from reefvision.jobs.video_metric_depth import process_video_metric_depth_job
from reefvision.jobs.video_tracking import process_video_tracking_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.repositories.jobs import JobRepository
from reefvision.services.sam2_install import process_sam2_install
from reefvision.services.segmentation_evaluation_queue import SegmentationEvaluationQueueService
from reefvision.storage.images import create_thumbnail
from reefvision.storage.projects import resolve_managed_project_path

LOGGER = logging.getLogger("reefvision.worker")


def _next_queued_job_identity(
    factory: sessionmaker[Session],
) -> tuple[str, str] | None:
    with factory() as session:
        job = JobRepository(session).next_queued()
        if job is None:
            return None
        return job.id, job.job_type


def _claim_isolated_job(
    factory: sessionmaker[Session],
    job_id: str,
    job_type: str,
) -> bool:
    """Atomically claim one queued isolated job before launching its child process."""

    now = datetime.now(UTC)
    with factory() as session:
        result = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.job_type == job_type,
                Job.status == "queued",
            )
            .values(
                status="running",
                started_at=now,
                error_message=None,
                result_json={
                    "stage": "launching_process",
                    "heartbeat_at": now.isoformat(),
                },
            )
        )
        session.commit()
        return int(getattr(result, "rowcount", 0) or 0) == 1


def _video_tracking_worker_command(
    settings: Settings,
    job_id: str,
) -> list[str]:
    child_log = settings.resolved_data_dir / "logs" / f"video-tracking-{job_id}.log"

    args = [
        "--data-dir",
        str(settings.resolved_data_dir),
        "--log-file",
        str(child_log),
        "--skip-migrations",
        "--video-tracking-job",
        job_id,
    ]

    if bool(vars(sys).get("frozen", False)):
        return [sys.executable, *args]

    return [
        sys.executable,
        "-m",
        "reefvision.desktop",
        *args,
    ]


def _start_isolated_process(command: list[str]) -> subprocess.Popen[bytes]:
    """Start an isolated worker without depending on asyncio subprocess support."""

    creationflags = (
        int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0
    )
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def _fail_isolated_launch(
    factory: sessionmaker[Session],
    job_id: str,
    message: str,
) -> None:
    """Make a claimed isolated job terminal when its child cannot be launched."""

    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return

        now = datetime.now(UTC)
        result = dict(job.result_json or {})
        result.update(
            {
                "stage": "failed",
                "heartbeat_at": now.isoformat(),
            }
        )
        job.status = "failed"
        job.result_json = result
        job.error_message = message
        job.completed_at = now
        session.commit()


async def process_isolated_video_tracking_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
    stop_event: asyncio.Event,
) -> bool:
    if not _claim_isolated_job(factory, job_id, "video_tracking"):
        LOGGER.info(
            "Skipping isolated video tracking launch because job was already claimed",
            extra={
                "event_id": "video_tracking_process_claim_skipped",
                "component": "worker",
                "job_id": job_id,
            },
        )
        return True

    command = _video_tracking_worker_command(settings, job_id)

    LOGGER.info(
        "Launching isolated video tracking process",
        extra={
            "event_id": "video_tracking_process_start",
            "component": "worker",
            "job_id": job_id,
        },
    )

    try:
        process = await asyncio.to_thread(_start_isolated_process, command)
    except Exception as exc:
        message = f"Failed to launch isolated video tracking process: {exc}"
        _fail_isolated_launch(factory, job_id, message)
        LOGGER.exception(
            message,
            extra={
                "event_id": "video_tracking_process_launch_failure",
                "component": "worker",
                "job_id": job_id,
            },
        )
        return True

    wait_task = asyncio.create_task(asyncio.to_thread(process.wait))
    stop_task = asyncio.create_task(stop_event.wait())

    done, _ = await asyncio.wait(
        {wait_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if stop_task in done and stop_event.is_set():
        if process.returncode is None:
            LOGGER.info(
                "Stopping isolated video tracking process during API shutdown",
                extra={
                    "event_id": "video_tracking_process_shutdown",
                    "component": "worker",
                    "job_id": job_id,
                },
            )
            process.terminate()
            try:
                await asyncio.wait_for(asyncio.shield(wait_task), timeout=3.0)
            except TimeoutError:
                process.kill()
                await wait_task

        if not wait_task.done():
            await wait_task

        return True

    if not stop_task.done():
        stop_task.cancel()
        with suppress(asyncio.CancelledError):
            await stop_task

    return_code = await wait_task

    with factory() as session:
        job = session.get(Job, job_id)

        if job is None:
            return True

        if job.status in {"succeeded", "failed", "cancelled"}:
            LOGGER.info(
                "Isolated video tracking process exited with status %s",
                job.status,
                extra={
                    "event_id": "video_tracking_process_exit",
                    "component": "worker",
                    "job_id": job_id,
                    "return_code": return_code,
                },
            )
            return True

    _fail_job(
        factory,
        job_id,
        (f"Isolated video tracking process exited unexpectedly with code {return_code}"),
    )
    return True


def recover_interrupted_video_tracking_jobs(session: Session) -> int:
    jobs = list(
        session.scalars(
            select(Job).where(
                Job.job_type == "video_tracking",
                Job.status.in_(("running", "cancel_requested")),
            )
        )
    )
    now = datetime.now(UTC)

    for job in jobs:
        result = dict(job.result_json or {})

        if job.status == "cancel_requested":
            job.status = "cancelled"
            stage = "cancelled"
            message = "Cancellation finalized after ReefVision restart"
            video_status = "tracking_cancelled"
        else:
            job.status = "failed"
            stage = "interrupted"
            message = (
                "Video tracking was interrupted while ReefVision was closed at "
                f"frame {job.progress_current}/{job.progress_total}. "
                "Start or retry the tracking run explicitly."
            )
            video_status = "tracking_failed"

        result.update(
            {
                "stage": stage,
                "recovery": "interrupted_on_startup",
                "recovered_at": now.isoformat(),
            }
        )
        job.result_json = result
        job.error_message = message
        job.completed_at = now

        video_id = str(dict(job.request_json or {}).get("video_id", ""))
        if video_id:
            video = session.get(VideoAsset, video_id)
            if video is not None:
                video.status = video_status
                video.revision += 1

    return len(jobs)


def recover_interrupted_jobs(
    factory: sessionmaker[Session],
    settings: Settings | None = None,
) -> int:
    with factory() as session:
        interrupted_training_jobs = list(
            session.scalars(
                select(Job).where(
                    Job.job_type == "training",
                    Job.status.in_(("running", "cancel_requested")),
                )
            )
        )
        count = len(interrupted_training_jobs)
        for job in interrupted_training_jobs:
            recover_training_run(session, settings, job)
        count += recover_interrupted_video_tracking_jobs(session)
        count += JobRepository(session).recover_interrupted_jobs()

        recovered_at = datetime.now(UTC)

        for qc_run in session.scalars(
            select(QualityControlRun).where(
                QualityControlRun.status.in_(("running", "cancel_requested"))
            )
        ):
            if qc_run.status == "cancel_requested":
                qc_run.status = "cancelled"
                qc_run.cancelled_at = recovered_at
                qc_run.completed_at = recovered_at
                qc_run.error_message = "Cancellation finalized after ReefVision restart"
            else:
                qc_run.status = "queued"
                qc_run.error_message = "Recovered after interruption"
                qc_run.started_at = None
                qc_run.completed_at = None

        for backup in session.scalars(
            select(BackupRecord).where(
                BackupRecord.status.in_(("running", "verifying", "cancel_requested"))
            )
        ):
            if backup.status == "cancel_requested":
                backup.status = "cancelled"
                backup.completed_at = recovered_at
                backup.error_message = "Cancellation finalized after ReefVision restart"
                backup.result_json = {
                    **dict(backup.result_json or {}),
                    "stage": "cancelled",
                    "recovery": "cancelled_on_startup",
                    "recovered_at": recovered_at.isoformat(),
                }
            else:
                backup.status = "queued"
                backup.error_message = "Recovered after interruption"
                backup.started_at = None
                backup.completed_at = None

        for workflow_run in session.scalars(
            select(WorkflowRun).where(
                WorkflowRun.status.in_(
                    (
                        "running",
                        "cancel_requested",
                    )
                )
            )
        ):
            previous_status = workflow_run.status

            result = dict(workflow_run.result_json or {})

            raw_history = result.get(
                "recovery_history",
                [],
            )

            history = (
                list(raw_history)
                if isinstance(
                    raw_history,
                    list,
                )
                else []
            )

            recovery_action = (
                "cancelled_on_startup"
                if previous_status == "cancel_requested"
                else "requeued_on_startup"
            )

            history.append(
                {
                    "recovered_at": (recovered_at.isoformat()),
                    "from_status": (previous_status),
                    "action": (recovery_action),
                }
            )

            if previous_status == "cancel_requested":
                workflow_run.status = "cancelled"
                workflow_run.completed_at = recovered_at
                workflow_run.error_message = "Cancellation finalized after ReefVision restart"
                workflow_run.result_json = {
                    **result,
                    "stage": "cancelled",
                    "recovery": ("cancelled_on_startup"),
                    "recovered_at": (recovered_at.isoformat()),
                    "recovery_history": (history),
                }

                for node in session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == workflow_run.id,
                        WorkflowNodeRun.status.in_(
                            (
                                "pending",
                                "running",
                                "waiting_for_review",
                                "review_approved",
                            )
                        ),
                    )
                ):
                    node.status = "cancelled"
                    node.completed_at = recovered_at
                    node.error_message = "Workflow cancellation finalized after ReefVision restart"

            else:
                workflow_run.status = "queued"
                workflow_run.started_at = None
                workflow_run.completed_at = None
                workflow_run.error_message = "Recovered after interruption"
                workflow_run.result_json = {
                    **result,
                    "stage": "queued",
                    "recovery": ("requeued_on_startup"),
                    "recovered_at": (recovered_at.isoformat()),
                    "recovery_history": (history),
                }

                # Only the node that was actively executing is
                # made pending again. Already-succeeded nodes and
                # their artifact identities remain untouched.
                for node in session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == workflow_run.id,
                        WorkflowNodeRun.status == "running",
                    )
                ):
                    node.status = "pending"
                    node.started_at = None
                    node.completed_at = None
                    node.error_message = "Recovered after interrupted workflow execution"
                    node.result_json = {
                        **dict(node.result_json or {}),
                        "recovery": {
                            "action": ("requeued_on_startup"),
                            "recovered_at": (recovered_at.isoformat()),
                        },
                    }

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


def process_thumbnail_job(settings: Settings, factory: sessionmaker[Session], job_id: str) -> bool:
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


def process_next_waiting_segmentation_evaluation(
    settings: Settings, factory: sessionmaker[Session]
) -> bool:
    """Finalize one terminal held-out evaluation without activating any model.

    The normal worker checks this only when no queued job is available.
    Incomplete child inference does not trigger repeated DB writes.
    """
    with factory() as session:
        # A fixed first page can starve completed evaluations indefinitely when
        # older inference children remain active. Scan successive stable pages
        # until a terminal evaluation is found, without modifying active jobs.
        offset = 0
        while True:
            waiting = list(
                session.scalars(
                    select(Job)
                    .where(
                        Job.job_type == "segmentation_learning_evaluation",
                        Job.status == "waiting",
                    )
                    .order_by(Job.created_at, Job.id)
                    .offset(offset)
                    .limit(32)
                )
            )
            if not waiting:
                break
            for record in waiting:
                request = dict(record.request_json or {})
                if request.get("task") != "segment":
                    continue
                candidate_id = request.get("candidate_job_id")
                if not isinstance(candidate_id, str) or not candidate_id:
                    continue
                ids = [candidate_id]
                incumbent_id = request.get("incumbent_job_id")
                if incumbent_id is not None:
                    if not isinstance(incumbent_id, str) or not incumbent_id:
                        continue
                    ids.append(incumbent_id)
                child_jobs = [session.get(Job, child_id) for child_id in ids]
                statuses = [child.status if child is not None else "missing" for child in child_jobs]
                if not (
                    any(status in {"failed", "cancelled", "missing"} for status in statuses)
                    or all(status == "succeeded" for status in statuses)
                ):
                    continue
                record_id = record.id
                project_id = record.project_id
                if project_id is None:
                    continue
                try:
                    SegmentationEvaluationQueueService(session, settings).advance(
                        str(project_id), record_id
                    )
                except Exception:
                    session.rollback()
                    failed = session.get(Job, record_id)
                    if failed is not None and failed.status == "waiting":
                        failed.status = "failed"
                        failed.completed_at = datetime.now(UTC)
                        failed.error_message = (
                            "Held-out segmentation evaluation could not be finalized; "
                            "inspect the local scientific audit logs"
                        )
                        failed.result_json = {
                            "promotion_eligible": False,
                            "blockers": [failed.error_message],
                        }
                        session.commit()
                    LOGGER.exception(
                        "Held-out segmentation evaluation could not be finalized",
                        extra={
                            "event_id": "segmentation_evaluation_finalization_failed",
                            "component": "worker",
                            "job_id": record_id,
                        },
                    )
                return True
            offset += len(waiting)
    return False


def process_next_thumbnail_job(settings: Settings, factory: sessionmaker[Session]) -> bool:
    with factory() as session:
        job = JobRepository(session).next_queued()
        job_id = job.id if job is not None else None
        job_type = job.job_type if job is not None else None
    if job_id is None:
        return process_next_waiting_segmentation_evaluation(settings, factory)

    try:
        if job_type == "thumbnail":
            return process_thumbnail_job(settings, factory, job_id)
        if job_type == "inference":
            return process_inference_job(settings, factory, job_id)
        if job_type == "sam_image_proposals":
            return process_sam_image_proposals_job(settings, factory, job_id)
        if job_type == "classification_inference":
            return process_classification_inference_job(settings, factory, job_id)
        if job_type == "classification_training":
            return process_classification_training_job(settings, factory, job_id)
        if job_type == "export":
            return process_export_job(settings, factory, job_id)
        if job_type == "qc":
            return process_quality_control_job(settings, factory, job_id)
        if job_type == "backup":
            return process_backup_job(settings, factory, job_id)
        if job_type == "restore":
            return process_restore_job(settings, factory, job_id)
        if job_type == "diagnostics":
            return process_diagnostics_job(settings, factory, job_id)
        if job_type == "training":
            return process_task_aware_training_job(settings, factory, job_id)
        if job_type == "model_install":
            return process_model_install_job(settings, factory, job_id)
        if job_type == "sam2_install":
            return process_sam2_install(settings, factory, job_id)
        if job_type == "video_extract":
            return process_video_extract_job(settings, factory, job_id)
        if job_type == "video_tracking":
            return process_video_tracking_job(settings, factory, job_id)
        if job_type == "video_annotated_export":
            return process_video_annotated_export_job(settings, factory, job_id)
        if job_type == "video_metric_depth_3d":
            return process_video_metric_depth_job(settings, factory, job_id)
        if job_type == "project_exchange_export":
            return process_project_exchange_export_job(settings, factory, job_id)
        if job_type == "workflow_run":
            return process_workflow_run_job(settings, factory, job_id)

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
                "component": "worker",
                "job_id": job_id,
                "job_type": job_type,
            },
        )
        return True


def _annotated_video_export_worker_command(
    settings: Settings,
    job_id: str,
) -> list[str]:
    child_log = settings.resolved_data_dir / "logs" / f"annotated-video-export-{job_id}.log"
    args = [
        "--data-dir",
        str(settings.resolved_data_dir),
        "--log-file",
        str(child_log),
        "--skip-migrations",
        "--annotated-video-export-job",
        job_id,
    ]
    if bool(vars(sys).get("frozen", False)):
        return [sys.executable, *args]
    return [sys.executable, "-m", "reefvision.desktop", *args]


async def process_isolated_annotated_video_export_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
    stop_event: asyncio.Event,
) -> bool:
    if not _claim_isolated_job(factory, job_id, "video_annotated_export"):
        LOGGER.info(
            "Skipping isolated annotated-video export launch because job was already claimed",
            extra={
                "event_id": "annotated_video_export_process_claim_skipped",
                "component": "worker",
                "job_id": job_id,
            },
        )
        return True

    command = _annotated_video_export_worker_command(settings, job_id)
    LOGGER.info(
        "Launching isolated annotated-video export process",
        extra={
            "event_id": "annotated_video_export_process_start",
            "component": "worker",
            "job_id": job_id,
        },
    )
    try:
        process = await asyncio.to_thread(_start_isolated_process, command)
    except Exception as exc:
        message = f"Failed to launch isolated annotated-video export process: {exc}"
        _fail_isolated_launch(factory, job_id, message)
        LOGGER.exception(
            message,
            extra={
                "event_id": "annotated_video_export_process_launch_failure",
                "component": "worker",
                "job_id": job_id,
            },
        )
        return True

    wait_task = asyncio.create_task(asyncio.to_thread(process.wait))
    stop_task = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {wait_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if stop_task in done and stop_event.is_set():
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(asyncio.shield(wait_task), timeout=3.0)
            except TimeoutError:
                process.kill()
                await wait_task
        if not wait_task.done():
            await wait_task
        return True

    if not stop_task.done():
        stop_task.cancel()
        with suppress(asyncio.CancelledError):
            await stop_task

    return_code = await wait_task
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return True
        if job.status in {"succeeded", "failed", "cancelled"}:
            LOGGER.info(
                "Isolated annotated-video export process exited with status %s",
                job.status,
                extra={
                    "event_id": "annotated_video_export_process_exit",
                    "component": "worker",
                    "job_id": job_id,
                    "return_code": return_code,
                },
            )
            return True

    _fail_job(
        factory,
        job_id,
        f"Isolated annotated-video export process exited unexpectedly with code {return_code}",
    )
    return True


async def thumbnail_worker_loop(
    settings: Settings,
    factory: sessionmaker[Session],
    stop_event: asyncio.Event,
) -> None:
    recover_interrupted_jobs(factory, settings)
    while not stop_event.is_set():
        try:
            queued = _next_queued_job_identity(factory)

            if queued is not None and queued[1] == "video_tracking":
                processed = await process_isolated_video_tracking_job(
                    settings,
                    factory,
                    queued[0],
                    stop_event,
                )
            elif queued is not None and queued[1] == "video_annotated_export":
                processed = await process_isolated_annotated_video_export_job(
                    settings,
                    factory,
                    queued[0],
                    stop_event,
                )
            else:
                processed = await asyncio.to_thread(
                    process_next_thumbnail_job,
                    settings,
                    factory,
                )
        except Exception:
            LOGGER.exception(
                "Background worker iteration failed",
                extra={
                    "event_id": "background_worker_iteration_failure",
                    "component": "worker",
                },
            )
            processed = False
        if not processed:
            with suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=settings.worker_poll_seconds)
