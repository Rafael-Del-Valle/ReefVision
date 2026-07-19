"""Job status, orchestration, retry, pause, dependency, and cancellation services."""

from __future__ import annotations

from reefvision.db.models import Job, JobEvent
from reefvision.domain.errors import ConflictError
from reefvision.repositories.backups import BackupRepository
from reefvision.repositories.jobs import JobRepository
from reefvision.repositories.quality_control import QualityControlRepository
from reefvision.services.job_orchestration import JobOrchestrationService
from sqlalchemy.orm import Session


class JobService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.jobs = JobRepository(session)
        self.backups = BackupRepository(session)
        self.quality_control = QualityControlRepository(session)
        self.orchestration = JobOrchestrationService(session)

    def get(self, job_id: str) -> Job:
        return self.orchestration.get(job_id)

    def retry(self, job_id: str, *, from_checkpoint: bool = True) -> Job:
        job = self.get(job_id)
        retryable_types = {
            "thumbnail",
            "inference",
            "classification_inference",
            "export",
            "backup",
            "restore",
            "diagnostics",
            "model_install",
            "training",
            "video_extract",
            "video_track",
            "depth_map",
            "image_embeddings",
            "workflow_run",
        }
        if job.status != "failed" or job.job_type not in retryable_types:
            raise ConflictError("Only failed recoverable jobs can be retried")
        if job.max_retries == 0:
            # Preserve the historical one-click retry behavior for jobs created before
            # retry policies became explicit. New producers should set max_retries.
            job.max_retries = 1
        backup = self.backups.get_by_job_id(job.id) if job.job_type == "backup" else None
        retried = self.orchestration.retry(job.id, from_checkpoint=from_checkpoint)
        if backup is not None:
            backup.status = "queued"
            backup.error_message = None
            backup.started_at = None
            backup.completed_at = None
            backup.result_json = None
            self.session.commit()
            self.session.refresh(retried)
        return retried

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        quality_control_run = (
            self.quality_control.get_run_by_job_id(job.id) if job.job_type == "qc" else None
        )
        backup = self.backups.get_by_job_id(job.id) if job.job_type == "backup" else None
        if job.status in {"queued", "blocked", "paused"}:
            job = self.orchestration.transition(
                job.id,
                "cancelled",
                event_type="cancelled_before_execution",
                commit=False,
            )
            if quality_control_run is not None:
                quality_control_run.status = "cancelled"
                quality_control_run.cancelled_at = job.completed_at
            if backup is not None:
                backup.status = "cancelled"
                backup.completed_at = job.completed_at
        elif job.status in {"running", "pause_requested"}:
            job = self.orchestration.transition(
                job.id,
                "cancel_requested",
                event_type="cancellation_requested",
                commit=False,
            )
            if quality_control_run is not None:
                quality_control_run.status = "cancel_requested"
            if backup is not None:
                backup.status = "cancel_requested"
        else:
            raise ConflictError("Only queued, blocked, running, or paused jobs can be cancelled")
        self.session.commit()
        self.session.refresh(job)
        return job

    def request_pause(self, job_id: str) -> Job:
        return self.orchestration.request_pause(job_id)

    def resume(self, job_id: str) -> Job:
        return self.orchestration.resume(job_id)

    def heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        progress_current: int | None,
        progress_total: int | None,
        checkpoint: dict[str, object] | None,
    ) -> Job:
        return self.orchestration.heartbeat(
            job_id,
            worker_id=worker_id,
            progress_current=progress_current,
            progress_total=progress_total,
            checkpoint=checkpoint,
        )

    def add_dependency(
        self,
        job_id: str,
        depends_on_job_id: str,
        *,
        required_status: str,
    ) -> None:
        self.orchestration.add_dependency(
            job_id,
            depends_on_job_id,
            required_status=required_status,
        )
        self.orchestration.refresh_blocked_state(job_id)

    def dependency_status(self, job_id: str) -> tuple[bool, list[dict[str, str]]]:
        return self.orchestration.dependency_status(job_id)

    def events(self, job_id: str) -> list[JobEvent]:
        return self.orchestration.events(job_id)
