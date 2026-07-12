"""Managed diagnostic-bundle job processing for Milestone 8."""

from __future__ import annotations

import logging
import os
import platform
import shutil
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.jobs.restores import JobCancelled, ensure_job_not_cancelled
from reefvision.logging_utils import default_logs_dir
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
_DEPENDENCY_NAMES = ("fastapi", "sqlalchemy", "pydantic", "alembic")


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
        job.error_message = None
        job.result_json = {"stage": "collecting"}
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
        ensure_job_not_cancelled(factory, job_id)
        log_snippets = _collect_log_snippets(
            settings=settings,
            strict_redaction=strict_redaction,
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
    disk_usage = shutil.disk_usage(settings.resolved_data_dir)
    with factory() as session:
        recent_failures = [
            {
                "job_id": item.id,
                "job_type": item.job_type,
                "status": item.status,
                "error_message": item.error_message,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            }
            for item in session.scalars(
                select(Job)
                .where(Job.status == "failed")
                .order_by(Job.completed_at.desc().nullslast(), Job.created_at.desc())
                .limit(10)
            )
        ]
    payload = {
        "diagnostic_bundle_version": DIAGNOSTIC_BUNDLE_VERSION,
        "reefvision_application_version": __version__,
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "job_id": job_id,
        "strict_redaction": strict_redaction,
        "environment": settings.env,
        "platform": {
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "python_executable": sys.executable,
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "cpu_count": os.cpu_count(),
        },
        "paths": {
            "data_dir": str(settings.resolved_data_dir),
            "database_url": settings.resolved_database_url,
            "logs_dir": str(default_logs_dir(settings)),
        },
        "disk": {
            "total_bytes": disk_usage.total,
            "used_bytes": disk_usage.used,
            "free_bytes": disk_usage.free,
        },
        "dependencies": {name: _dependency_version(name) for name in _DEPENDENCY_NAMES},
        "recent_failed_jobs": recent_failures,
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


def _dependency_version(name: str) -> str | None:
    try:
        return package_version(name)
    except PackageNotFoundError:
        return None


def _finalize_success(
    factory: sessionmaker[Session],
    *,
    job_id: str,
    bundle_path: str,
    bundle_size: int,
    strict_redaction: bool,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "succeeded"
        job.progress_current = 1
        job.progress_total = 1
        job.completed_at = datetime.now(UTC)
        job.result_json = {
            "stage": "completed",
            "bundle_path": bundle_path,
            "bundle_size_bytes": bundle_size,
            "diagnostic_bundle_version": DIAGNOSTIC_BUNDLE_VERSION,
            "strict_redaction": strict_redaction,
        }
        session.commit()


def _finalize_cancel(factory: sessionmaker[Session], *, job_id: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "cancelled"
        job.completed_at = datetime.now(UTC)
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
        job.result_json = {"stage": "failed", "error": message}
        session.commit()
