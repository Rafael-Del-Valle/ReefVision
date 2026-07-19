"""Formal job transitions, dependencies, retries, heartbeats, and recovery."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job, JobDependency, JobEvent
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError

TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
ACTIVE_JOB_STATUSES = frozenset(
    {"queued", "blocked", "running", "pause_requested", "paused", "cancel_requested"}
)
ALLOWED_JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"blocked", "running", "cancelled"}),
    "blocked": frozenset({"queued", "cancelled"}),
    "running": frozenset({"pause_requested", "cancel_requested", "succeeded", "failed"}),
    "pause_requested": frozenset({"paused", "cancel_requested", "failed"}),
    "paused": frozenset({"queued", "cancelled"}),
    "cancel_requested": frozenset({"cancelled", "failed", "succeeded"}),
    "succeeded": frozenset(),
    "failed": frozenset({"queued"}),
    "cancelled": frozenset(),
}


class JobOrchestrationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, job_id: str) -> Job:
        job = self.session.get(Job, job_id)
        if job is None:
            raise NotFoundError("Job not found")
        return job

    def events(self, job_id: str) -> list[JobEvent]:
        self.get(job_id)
        return list(
            self.session.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.created_at, JobEvent.id)
            )
        )

    def transition(
        self,
        job_id: str,
        to_status: str,
        *,
        actor: str = "system",
        event_type: str = "status_transition",
        message: str | None = None,
        details: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> Job:
        job = self.get(job_id)
        from_status = job.status
        if to_status == from_status:
            return job
        allowed = ALLOWED_JOB_TRANSITIONS.get(from_status)
        if allowed is None:
            raise ConflictError(f"Unknown persisted job status: {from_status}")
        if to_status not in allowed:
            raise ConflictError(f"Invalid job transition: {from_status} -> {to_status}")
        now = datetime.now(UTC)
        job.status = to_status
        job.state_version += 1
        job.last_transition_at = now
        if to_status == "running":
            job.started_at = job.started_at or now
            job.heartbeat_at = now
            job.completed_at = None
            job.paused_at = None
        elif to_status == "paused":
            job.paused_at = now
            job.heartbeat_at = None
        elif to_status == "queued":
            job.worker_id = None
            job.heartbeat_at = None
            job.paused_at = None
            job.completed_at = None
        elif to_status in TERMINAL_JOB_STATUSES:
            job.completed_at = now
            job.heartbeat_at = None
            job.worker_id = None
        self.session.add(
            JobEvent(
                id=str(uuid4()),
                job_id=job.id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                actor=actor,
                message=message,
                details_json=dict(details or {}),
            )
        )
        if commit:
            self.session.commit()
            self.session.refresh(job)
        return job

    def heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        progress_current: int | None = None,
        progress_total: int | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> Job:
        job = self.get(job_id)
        if job.status not in {"running", "pause_requested", "cancel_requested"}:
            raise ConflictError("Heartbeats are accepted only for active worker jobs")
        if progress_current is not None:
            if progress_current < 0:
                raise ValidationError("Job progress cannot be negative")
            job.progress_current = progress_current
        if progress_total is not None:
            if progress_total < 0:
                raise ValidationError("Job progress total cannot be negative")
            job.progress_total = progress_total
        if job.progress_total > 0 and job.progress_current > job.progress_total:
            raise ValidationError("Job progress cannot exceed its total")
        job.worker_id = worker_id
        job.heartbeat_at = datetime.now(UTC)
        if checkpoint is not None:
            if not job.resume_supported:
                raise ConflictError("This job type does not support persisted checkpoints")
            job.checkpoint_json = dict(checkpoint)
        self.session.commit()
        self.session.refresh(job)
        return job

    def add_dependency(
        self,
        job_id: str,
        depends_on_job_id: str,
        *,
        required_status: str = "succeeded",
    ) -> JobDependency:
        if job_id == depends_on_job_id:
            raise ValidationError("A job cannot depend on itself")
        job = self.get(job_id)
        dependency_job = self.get(depends_on_job_id)
        if job.project_id != dependency_job.project_id:
            raise ValidationError("Dependent jobs must belong to the same project")
        if job.status not in {"queued", "blocked"}:
            raise ConflictError("Dependencies can be changed only before a job starts")
        if required_status not in TERMINAL_JOB_STATUSES:
            raise ValidationError("Dependency status must be succeeded, failed, or cancelled")
        existing = self.session.get(JobDependency, (job_id, depends_on_job_id))
        if existing is not None:
            existing.required_status = required_status
            dependency = existing
        else:
            dependency = JobDependency(
                job_id=job_id,
                depends_on_job_id=depends_on_job_id,
                required_status=required_status,
            )
            self.session.add(dependency)
        self.session.flush()
        if self._dependency_graph_has_cycle():
            self.session.rollback()
            raise ValidationError("Job dependency would create a cycle")
        self.session.commit()
        return dependency

    def dependency_status(self, job_id: str) -> tuple[bool, list[dict[str, str]]]:
        self.get(job_id)
        rows = list(
            self.session.execute(
                select(JobDependency, Job)
                .join(Job, Job.id == JobDependency.depends_on_job_id)
                .where(JobDependency.job_id == job_id)
            )
        )
        details = [
            {
                "job_id": dependency.depends_on_job_id,
                "required_status": dependency.required_status,
                "actual_status": upstream.status,
            }
            for dependency, upstream in rows
        ]
        return all(item["required_status"] == item["actual_status"] for item in details), details

    def refresh_blocked_state(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status not in {"queued", "blocked"}:
            return job
        satisfied, details = self.dependency_status(job.id)
        target = "queued" if satisfied else "blocked"
        if target == job.status:
            return job
        return self.transition(
            job.id,
            target,
            event_type="dependency_state_changed",
            details={"dependencies": details},
        )

    def retry(self, job_id: str, *, from_checkpoint: bool = True) -> Job:
        job = self.get(job_id)
        if job.status != "failed":
            raise ConflictError("Only failed jobs can be retried")
        if job.retry_count >= job.max_retries:
            raise ConflictError("Job retry limit has been reached")
        job.retry_count += 1
        job.error_message = None
        job.result_json = None
        job.progress_current = 0
        if not from_checkpoint or not job.resume_supported:
            job.checkpoint_json = {}
        self.transition(
            job.id,
            "queued",
            event_type="retry_queued",
            details={
                "retry_count": job.retry_count,
                "max_retries": job.max_retries,
                "from_checkpoint": bool(from_checkpoint and job.resume_supported),
            },
            commit=False,
        )
        self.session.commit()
        self.session.refresh(job)
        return job

    def request_pause(self, job_id: str) -> Job:
        job = self.get(job_id)
        if not job.resume_supported:
            raise ConflictError("This job type does not support pause and resume")
        return self.transition(job.id, "pause_requested", event_type="pause_requested")

    def resume(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status != "paused":
            raise ConflictError("Only paused jobs can be resumed")
        return self.transition(job.id, "queued", event_type="resume_queued")

    def recover_stale(
        self,
        *,
        stale_before: datetime,
        actor: str = "startup_recovery",
    ) -> list[str]:
        candidates = list(
            self.session.scalars(
                select(Job).where(
                    Job.status.in_(("running", "pause_requested", "cancel_requested")),
                    Job.heartbeat_at.is_not(None),
                    Job.heartbeat_at < stale_before,
                )
            )
        )
        recovered: list[str] = []
        for job in candidates:
            if job.status == "cancel_requested":
                self.transition(
                    job.id,
                    "cancelled",
                    actor=actor,
                    event_type="stale_cancel_completed",
                    message="Recovered stale cancellation after worker interruption",
                    commit=False,
                )
            elif job.resume_supported:
                self.transition(
                    job.id,
                    "failed",
                    actor=actor,
                    event_type="worker_lost",
                    message="Worker heartbeat expired; retry can resume from checkpoint",
                    commit=False,
                )
            else:
                self.transition(
                    job.id,
                    "failed",
                    actor=actor,
                    event_type="worker_lost",
                    message="Worker heartbeat expired",
                    commit=False,
                )
            recovered.append(job.id)
        self.session.commit()
        return recovered

    def _dependency_graph_has_cycle(self) -> bool:
        graph: dict[str, list[str]] = defaultdict(list)
        nodes: set[str] = set()
        for dependency in self.session.scalars(select(JobDependency)):
            graph[dependency.job_id].append(dependency.depends_on_job_id)
            nodes.add(dependency.job_id)
            nodes.add(dependency.depends_on_job_id)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(visit(dependency) for dependency in graph[node]):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in nodes)
