"""Background-job persistence operations."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from reefvision.db.models import Job, JobDependency, TrainingRun
from reefvision.services.resource_scheduler import ResourceScheduler
from reefvision.services.training_resource_requirements import (
    training_scheduler_requirements,
)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _training_run_for_job(session: Session, job: Job) -> TrainingRun | None:
    if job.job_type != "training":
        return None
    run_id = dict(job.request_json or {}).get("training_run_id")
    return session.get(TrainingRun, run_id) if isinstance(run_id, str) and run_id else None


def _should_bind_training_device(
    run: TrainingRun,
    requirements: dict[str, Any],
    assignment: dict[str, Any],
) -> bool:
    requested = str(run.device or "auto").strip().casefold()
    return (
        int(assignment.get("gpu_count", 0) or 0) > 0
        or bool(requirements.get("gpu_required"))
        or int(requirements.get("gpu_count", 0) or 0) > 0
        or requested == "cpu"
        or requested.startswith("cuda")
        or requested in {"gpu"}
        or bool(requested and requested != "auto" and requested[0].isdigit())
    )


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: Job) -> None:
        self.session.add(job)

    def get(self, job_id: str) -> Job | None:
        return self.session.get(Job, job_id)

    def next_queued(self, worker_id: str | None = None) -> Job | None:
        """Atomically claim the highest-priority runnable, resource-compatible job."""

        resolved_worker_id = worker_id or f"worker-{os.getpid()}-{uuid4().hex[:8]}"
        now = datetime.now(UTC)
        stale_claim = now - timedelta(minutes=2)
        claimable = or_(
            Job.worker_id.is_(None),
            Job.heartbeat_at.is_(None),
            Job.heartbeat_at < stale_claim,
        )
        candidates = list(
            self.session.scalars(
                select(Job)
                .where(Job.status == "queued", claimable)
                .order_by(Job.priority, Job.created_at, Job.id)
                .limit(200)
            )
        )
        scheduler = ResourceScheduler(self.session)
        for candidate in candidates:
            if candidate.cancel_after is not None and _as_utc(candidate.cancel_after) <= now:
                continue
            dependencies = list(
                self.session.execute(
                    select(JobDependency, Job)
                    .join(Job, Job.id == JobDependency.depends_on_job_id)
                    .where(JobDependency.job_id == candidate.id)
                )
            )
            if not all(
                upstream.status == dependency.required_status
                for dependency, upstream in dependencies
            ):
                continue

            training_run = _training_run_for_job(self.session, candidate)
            if training_run is not None and not dict(candidate.resource_requirements_json or {}):
                candidate.resource_requirements_json = training_scheduler_requirements(training_run)
                self.session.flush()

            decision = scheduler.evaluate(candidate)
            if not decision.eligible:
                continue
            assignment = dict(decision.assignment)
            assignment_device = str(assignment.get("device", "cpu"))
            assigned_gpu_count = int(assignment.get("gpu_count", 0) or 0)
            request_json = dict(candidate.request_json or {})
            requirements = dict(candidate.resource_requirements_json or {})
            if (
                "device" in request_json
                or requirements.get("gpu_required")
                or int(requirements.get("gpu_count", 0) or 0) > 0
                or assigned_gpu_count > 0
            ):
                request_json["device"] = assignment_device
            if "device_id" in request_json or candidate.job_type == "provider_benchmark":
                request_json["device_id"] = assignment_device
            if assignment.get("gpu_indices"):
                request_json["assigned_gpu_indices"] = list(assignment["gpu_indices"])
                request_json["cuda_visible_devices"] = str(
                    assignment.get("cuda_visible_devices", "")
                )
            claimed = cast(
                CursorResult[Any],
                self.session.execute(
                    update(Job)
                    .where(
                        Job.id == candidate.id,
                        Job.status == "queued",
                        claimable,
                    )
                    .values(
                        worker_id=resolved_worker_id,
                        heartbeat_at=now,
                        request_json=request_json,
                        resource_requirements_json=requirements,
                        resource_assignment_json=assignment,
                    )
                ),
            )
            if (claimed.rowcount or 0) != 1:
                self.session.rollback()
                continue
            if training_run is not None:
                if _should_bind_training_device(training_run, requirements, assignment):
                    training_run.device = assignment_device
                training_run.resource_limits_json = {
                    **dict(training_run.resource_limits_json or {}),
                    "scheduler_assignment": assignment,
                }
            self.session.commit()
            refreshed = self.session.get(Job, candidate.id)
            if refreshed is not None:
                return refreshed
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
        """Recover interrupted execution and expired queued dispatch leases."""

        stale_claim = datetime.now(UTC) - timedelta(minutes=2)
        resumable = cast(
            CursorResult[Any],
            self.session.execute(
                update(Job)
                .where(
                    Job.status.in_(("running", "pause_requested")),
                    or_(
                        Job.resume_supported.is_(True),
                        Job.job_type == "thumbnail",
                    ),
                )
                .values(
                    status="queued",
                    started_at=None,
                    heartbeat_at=None,
                    worker_id=None,
                    resource_assignment_json={},
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
                    Job.resume_supported.is_not(True),
                    Job.job_type != "thumbnail",
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
        released_claims = cast(
            CursorResult[Any],
            self.session.execute(
                update(Job)
                .where(
                    Job.status == "queued",
                    Job.worker_id.is_not(None),
                    or_(Job.heartbeat_at.is_(None), Job.heartbeat_at < stale_claim),
                )
                .values(
                    worker_id=None,
                    heartbeat_at=None,
                    resource_assignment_json={},
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
        return int(
            (resumable.rowcount or 0)
            + (failed.rowcount or 0)
            + (released_claims.rowcount or 0)
            + (cancelled.rowcount or 0)
        )
