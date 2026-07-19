"""Managed diagnostic-bundle job processing with strict privacy controls."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.jobs.restores import JobCancelled, ensure_job_not_cancelled
from reefvision.logging_utils import default_logs_dir
from reefvision.services.system_inventory import collect_system_inventory
from reefvision.storage.backups import BACKUP_FORMAT_VERSION
from reefvision.storage.diagnostics import (
    DIAGNOSTIC_BUNDLE_VERSION,
    default_diagnostic_bundle_path,
    diagnostic_bundle_path,
    redact_value,
    tail_text_file,
    write_diagnostic_bundle,
)

LOGGER = logging.getLogger("reefvision.diagnostics")


def _heartbeat(
    factory: sessionmaker[Session],
    job_id: str,
    *,
    stage: str,
    progress: int,
    checkpoint: dict[str, Any] | None = None,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.progress_current = progress
        job.progress_total = 3
        job.heartbeat_at = datetime.now(UTC)
        job.checkpoint_json = {"stage": stage, **(checkpoint or {})}
        job.result_json = {"stage": stage}
        session.commit()


def process_diagnostics_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "diagnostics" or job.status != "queued":
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.heartbeat_at = job.started_at
        job.progress_current = 0
        job.progress_total = 3
        job.checkpoint_json = {"stage": "collecting_inventory"}
        job.error_message = None
        job.result_json = {"stage": "collecting_inventory"}
        session.commit()
        request = dict(job.request_json)
        created_at = job.created_at

    strict_redaction = bool(request.get("strict_redaction", True))
    destination_relative = str(
        request.get(
            "bundle_path",
            default_diagnostic_bundle_path(
                job_id,
                created_at_label=created_at.strftime("%Y%m%dT%H%M%SZ"),
            ),
        )
    )
    bundle_path = diagnostic_bundle_path(settings, destination_relative)

    try:
        ensure_job_not_cancelled(factory, job_id)
        payload = _build_payload(
            settings=settings,
            factory=factory,
            job_id=job_id,
            strict_redaction=strict_redaction,
        )
        _heartbeat(
            factory,
            job_id,
            stage="collecting_logs",
            progress=1,
            checkpoint={"inventory_collected": True},
        )
        ensure_job_not_cancelled(factory, job_id)
        log_snippets = _collect_log_snippets(
            settings=settings,
            strict_redaction=strict_redaction,
        )
        _heartbeat(
            factory,
            job_id,
            stage="writing_bundle",
            progress=2,
            checkpoint={
                "inventory_collected": True,
                "log_file_count": len(log_snippets),
            },
        )
        ensure_job_not_cancelled(factory, job_id)
        bundle_size = write_diagnostic_bundle(
            bundle_path,
            payload=payload,
            log_snippets=log_snippets,
        )
        _finalize_success(
            factory,
            job_id=job_id,
            bundle_path=destination_relative,
            bundle_size=bundle_size,
            strict_redaction=strict_redaction,
            log_file_count=len(log_snippets),
        )
        LOGGER.info(
            "ReefVision diagnostic bundle created",
            extra={
                "event_id": "diagnostics_complete",
                "component": "diagnostics",
                "job_id": job_id,
            },
        )
        return True
    except JobCancelled:
        bundle_path.unlink(missing_ok=True)
        _finalize_cancel(factory, job_id=job_id)
        LOGGER.info(
            "ReefVision diagnostic bundle cancelled",
            extra={
                "event_id": "diagnostics_cancelled",
                "component": "diagnostics",
                "job_id": job_id,
            },
        )
        return False
    except Exception as exc:
        bundle_path.unlink(missing_ok=True)
        _finalize_failure(factory, job_id=job_id, message=str(exc))
        LOGGER.exception(
            "ReefVision diagnostic bundle failed",
            extra={"event_id": "diagnostics_failed", "component": "diagnostics", "job_id": job_id},
        )
        return False


def _build_payload(
    *,
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
    strict_redaction: bool,
) -> dict[str, Any]:
    with factory() as session:
        recent_failures = [
            {
                "job_id": item.id,
                "job_type": item.job_type,
                "status": item.status,
                "error_message": item.error_message,
                "request_summary": {
                    key: value
                    for key, value in (item.request_json or {}).items()
                    if key
                    not in {
                        "document",
                        "notes",
                        "positive_points",
                        "negative_points",
                    }
                },
                "resource_requirements": item.resource_requirements_json,
                "resource_assignment": item.resource_assignment_json,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            }
            for item in session.scalars(
                select(Job)
                .where(Job.status == "failed")
                .order_by(Job.completed_at.desc().nullslast(), Job.created_at.desc())
                .limit(25)
            )
        ]
    payload = {
        "diagnostic_bundle_version": DIAGNOSTIC_BUNDLE_VERSION,
        "reefvision_application_version": __version__,
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "job_id": job_id,
        "strict_redaction": strict_redaction,
        "configuration": {
            "environment": settings.env,
            "api_host": settings.api_host,
            "api_port": settings.api_port,
            "web_origin": settings.web_origin,
            "database_url": settings.resolved_database_url,
            "data_dir": str(settings.resolved_data_dir),
            "safe_mode": settings.safe_mode,
            "background_worker_enabled": settings.background_worker_enabled,
            "worker_concurrency": settings.worker_concurrency,
            "worker_poll_seconds": settings.worker_poll_seconds,
            "thumbnail_max_width": settings.thumbnail_max_width,
            "thumbnail_max_height": settings.thumbnail_max_height,
            "model_max_upload_bytes": settings.model_max_upload_bytes,
            "allow_unsafe_pickled_models": settings.allow_unsafe_pickled_models,
        },
        "system_inventory": collect_system_inventory(settings, factory),
        "recent_failed_jobs": recent_failures,
        "redaction": {
            "paths": True,
            "credentials": True,
            "environment_secret_values": True,
            "email_phone_ip_and_hostname": strict_redaction,
        },
    }
    return cast(
        dict[str, Any],
        redact_value(payload, settings=settings, strict_redaction=strict_redaction),
    )


def _collect_log_snippets(*, settings: Settings, strict_redaction: bool) -> dict[str, str]:
    logs_dir = default_logs_dir(settings)
    snippets: dict[str, str] = {}
    if not logs_dir.is_dir():
        return snippets
    for path in sorted(logs_dir.glob("*.log*")):
        content = tail_text_file(path)
        snippets[path.name] = redact_value(
            content,
            settings=settings,
            strict_redaction=strict_redaction,
        )
    return snippets


def _finalize_success(
    factory: sessionmaker[Session],
    *,
    job_id: str,
    bundle_path: str,
    bundle_size: int,
    strict_redaction: bool,
    log_file_count: int,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "succeeded"
        job.progress_current = 3
        job.progress_total = 3
        job.heartbeat_at = datetime.now(UTC)
        job.completed_at = job.heartbeat_at
        job.checkpoint_json = {
            "stage": "completed",
            "bundle_path": bundle_path,
        }
        job.result_json = {
            "stage": "completed",
            "bundle_path": bundle_path,
            "bundle_size_bytes": bundle_size,
            "diagnostic_bundle_version": DIAGNOSTIC_BUNDLE_VERSION,
            "strict_redaction": strict_redaction,
            "log_file_count": log_file_count,
        }
        session.commit()


def _finalize_cancel(factory: sessionmaker[Session], *, job_id: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "cancelled"
        job.completed_at = datetime.now(UTC)
        job.heartbeat_at = job.completed_at
        job.result_json = {"stage": "cancelled"}
        session.commit()


def _finalize_failure(
    factory: sessionmaker[Session],
    *,
    job_id: str,
    message: str,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = datetime.now(UTC)
        job.heartbeat_at = job.completed_at
        job.result_json = {"stage": "failed", "error": message}
        session.commit()
