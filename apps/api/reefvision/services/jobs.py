"""Job status and retry services."""

from sqlalchemy.orm import Session

from reefvision.db.models import Job
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError
from reefvision.repositories.backups import BackupRepository
from reefvision.repositories.jobs import JobRepository
from reefvision.repositories.quality_control import QualityControlRepository


class JobService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.jobs = JobRepository(session)
        self.backups = BackupRepository(session)
        self.quality_control = QualityControlRepository(session)

    def get(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise NotFoundError("Job not found")
        return job

    def retry(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status != "failed" or job.job_type not in {
            "thumbnail",
            "inference",
            "export",
            "backup",
            "restore",
            "diagnostics",
            "model_install",
        }:
            raise ConflictError(
                "Only failed thumbnail, inference, export, backup, restore, "
                "or diagnostics jobs can be retried"
            )
        job.status = "queued"
        job.progress_current = 0
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        job.result_json = None
        backup = self.backups.get_by_job_id(job.id) if job.job_type == "backup" else None
        if backup is not None:
            backup.status = "queued"
            backup.error_message = None
            backup.started_at = None
            backup.completed_at = None
            backup.result_json = None
        self.session.commit()
        self.session.refresh(job)
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        quality_control_run = (
            self.quality_control.get_run_by_job_id(job.id) if job.job_type == "qc" else None
        )
        backup = self.backups.get_by_job_id(job.id) if job.job_type == "backup" else None
        if job.status == "queued":
            job.status = "cancelled"
            job.completed_at = None
            if quality_control_run is not None:
                quality_control_run.status = "cancelled"
                quality_control_run.cancelled_at = utc_now()
            if backup is not None:
                backup.status = "cancelled"
                backup.completed_at = utc_now()
        elif job.status == "running":
            job.status = "cancel_requested"
            if quality_control_run is not None:
                quality_control_run.status = "cancel_requested"
            if backup is not None:
                backup.status = "cancel_requested"
        else:
            raise ConflictError("Only queued or running jobs can be cancelled")
        self.session.commit()
        self.session.refresh(job)
        return job
