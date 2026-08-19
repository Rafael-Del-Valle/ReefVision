"""Background ReefVision project exchange export jobs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, ProjectExchangePackage
from reefvision.services.project_exchange_v1 import ProjectExchangeV1Service


def process_project_exchange_export_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "project_exchange_export" or job.status != "queued":
            return False
        package_id = str(job.request_json.get("package_id", ""))
        package = session.get(ProjectExchangePackage, package_id)
        if package is None:
            job.status = "failed"
            job.error_message = "Project exchange package not found"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        package.status = "running"
        session.commit()

    try:
        with factory() as session:
            package_response = ProjectExchangeV1Service(session, settings).build_export(package_id)
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise RuntimeError("Project exchange job disappeared")
            job.status = "succeeded"
            job.progress_current = 1
            job.progress_total = 1
            job.result_json = {
                "package_id": package_response.id,
                "archive_path": package_response.archive_path,
                "manifest_sha256": package_response.manifest_sha256,
                "format_version": package_response.format_version,
            }
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            package = session.get(ProjectExchangePackage, package_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
            if package is not None:
                package.status = "failed"
                package.error_message = str(exc)
            session.commit()
        return False
