"""Runtime-safe project integrity checks for database timestamp portability."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from reefvision.db.models import Job
from reefvision.services.project_integrity import ProjectIntegrityService


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive datetimes and timezone-aware database values."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ProjectIntegrityRuntimeService(ProjectIntegrityService):
    """Project integrity service with portable stale-job timestamp comparisons."""

    def _inspect_jobs(self, project_id: str, stale_job_minutes: int) -> None:
        jobs = list(
            self.session.scalars(
                select(Job).where(Job.project_id == project_id).order_by(Job.created_at, Job.id)
            )
        )
        self.categories["job"].record_count = len(jobs)
        cutoff = datetime.now(UTC) - timedelta(minutes=stale_job_minutes)
        for job in jobs:
            timestamp = _as_utc(job.started_at or job.created_at)
            if job.status in {"running", "cancel_requested"} and timestamp < cutoff:
                self._issue(
                    severity="warning",
                    code="stale_active_job",
                    resource_kind="job",
                    record_id=job.id,
                    message=(
                        f"The {job.job_type} job has remained {job.status!r} longer "
                        f"than {stale_job_minutes} minutes."
                    ),
                    repairable=True,
                )
            if job.status == "failed" and not job.error_message:
                self._issue(
                    severity="warning",
                    code="failed_job_without_error",
                    resource_kind="job",
                    record_id=job.id,
                    message="The failed job does not contain a persisted error message.",
                )
