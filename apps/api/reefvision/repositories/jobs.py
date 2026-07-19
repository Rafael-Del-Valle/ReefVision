"""Background-job persistence operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from reefvision.db.models import Job, JobDependency


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: Job) -> None:
        self.session.add(job)

    def get(self, job_id: str) -> Job | None:
        return self.session.get(Job, job_id)

    def next_queued(self) -> Job | None:
        """Return the highest-priority runnable job whose dependencies are satisfied."""

        candidates = list(
            self.session.scalars(
                select(Job)
                .where(Job.status == "queued")
                .order_by(Job.priority, Job.created_at, Job.id)
                .limit(200)
            )
        )
        now = datetime.now(UTC)
        for candidate in candidates:
            if candidate.cancel_after is not None and candidate.cancel_after <= now:
                continue
            dependencies = list(
                self.session.execute(
                    select(JobDependency, Job)
                    .join(Job, Job.id == JobDependency.depends_on_job_id)
                    .where(JobDependency.job_id == candidate.id)
                )
            )
            if all(
                upstream.status == dependency.required_status
                for dependency, upstream in dependencies
            ):
                return candidate
        return None

    def has_active_jobs(self) -> bool:
        statement = select(Job.id).where(
            Job.status.in_(
                (
                    "queued",
                    "blocked",
                    "running",
                    "pause_requested",
                    "paused",
                    "cancel_requested",
                )
            )
        )
        return self.session.scalar(statement) is not None

    def recover_interrupted_jobs(self) -> int:
        """Legacy startup recovery retained for older job producers.

        New workers should use JobOrchestrationService heartbeats and structured events.
        This fallback requeues resumable work and fails non-resumable work instead of
        silently replaying side effects.
        """

        resumable = cast(
            CursorResult[Any],
            self.session.execute(
                update(Job)
                .where(
                    Job.status.in_(("running", "pause_requested")),
                    Job.resume_supported.is_(True),
                )
                .values(
                    status="queued",
                    started_at=None,
                    heartbeat_at=None,
                    worker_id=None,
                    error_message="Recovered resumable job after interruption",
                )
            ),
        )
        failed = cast(
            CursorResult[Any],
            self.session.execute(
                update(Job)
                .where(
                    Job.status.in_(("running", "pause_requested")),
                    Job.resume_supported.is_(False),
                )
                .values(
                    status="failed",
                    heartbeat_at=None,
                    worker_id=None,
                    completed_at=datetime.now(UTC),
                    error_message="Interrupted non-resumable job requires explicit retry",
                )
            ),
        )
        cancelled = cast(
            CursorResult[Any],
            self.session.execute(
                update(Job)
                .where(Job.status == "cancel_requested")
                .values(
                    status="cancelled",
                    heartbeat_at=None,
                    worker_id=None,
                    completed_at=datetime.now(UTC),
                    error_message="Cancellation completed during startup recovery",
                )
            ),
        )
        return int((resumable.rowcount or 0) + (failed.rowcount or 0) + (cancelled.rowcount or 0))
