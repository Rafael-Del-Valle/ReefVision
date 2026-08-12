"""Job status and retry services."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job, WorkflowNodeRun, WorkflowRun
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

    def _workflow_run(self, job: Job) -> WorkflowRun | None:
        if job.job_type != "workflow_run":
            return None
        return self.session.scalar(select(WorkflowRun).where(WorkflowRun.job_id == job.id))

    def _workflow_child_jobs(self, run: WorkflowRun, parent_job_id: str) -> list[Job]:
        candidates = list(
            self.session.scalars(
                select(Job).where(
                    Job.project_id == run.project_id,
                    Job.id != parent_job_id,
                    Job.status.in_(("queued", "running", "cancel_requested")),
                )
            )
        )
        return [
            child
            for child in candidates
            if str((child.request_json or {}).get("workflow_run_id") or "") == run.id
        ]

    def _cancel_workflow_children(
        self,
        run: WorkflowRun,
        parent_job_id: str,
        *,
        now,
    ) -> dict[str, int]:
        counts = {"cancelled": 0, "cancel_requested": 0}
        for child in self._workflow_child_jobs(run, parent_job_id):
            if child.status == "queued":
                child.status = "cancelled"
                child.completed_at = now
                child.error_message = "Parent workflow was cancelled before child execution"
                counts["cancelled"] += 1
            elif child.status == "running":
                child.status = "cancel_requested"
                counts["cancel_requested"] += 1
        return counts

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
            "workflow_run",
        }:
            raise ConflictError("Only supported failed background jobs can be retried")
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
        workflow_run = self._workflow_run(job)
        if workflow_run is not None:
            succeeded_nodes = list(
                self.session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == workflow_run.id,
                        WorkflowNodeRun.status == "succeeded",
                    )
                )
            )
            job.progress_current = len(succeeded_nodes)
            workflow_run.status = "queued"
            workflow_run.error_message = None
            workflow_run.started_at = None
            workflow_run.completed_at = None
            workflow_run.result_json = {
                "stage": "queued",
                "completed_nodes": len(succeeded_nodes),
                "retry": True,
            }
            for node in self.session.scalars(
                select(WorkflowNodeRun).where(
                    WorkflowNodeRun.workflow_run_id == workflow_run.id,
                    WorkflowNodeRun.status.in_(("failed", "cancelled", "running")),
                )
            ):
                node.status = "pending"
                node.error_message = None
                node.started_at = None
                node.completed_at = None
                node.input_artifact_ids_json = []
                node.output_artifact_ids_json = []
                node.result_json = {}
        self.session.commit()
        self.session.refresh(job)
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        quality_control_run = (
            self.quality_control.get_run_by_job_id(job.id) if job.job_type == "qc" else None
        )
        backup = self.backups.get_by_job_id(job.id) if job.job_type == "backup" else None
        workflow_run = self._workflow_run(job)
        now = utc_now()
        child_cancellation = {"cancelled": 0, "cancel_requested": 0}
        if workflow_run is not None:
            child_cancellation = self._cancel_workflow_children(
                workflow_run,
                job.id,
                now=now,
            )

        if job.status in {"queued", "waiting_for_review"}:
            job.status = "cancelled"
            job.completed_at = now
            if quality_control_run is not None:
                quality_control_run.status = "cancelled"
                quality_control_run.cancelled_at = now
            if backup is not None:
                backup.status = "cancelled"
                backup.completed_at = now
            if workflow_run is not None:
                workflow_run.status = "cancelled"
                workflow_run.completed_at = now
                workflow_run.result_json = {
                    **dict(workflow_run.result_json or {}),
                    "stage": "cancelled",
                    "child_job_cancellation": child_cancellation,
                }
                for node in self.session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == workflow_run.id,
                        WorkflowNodeRun.status.in_(
                            ("pending", "waiting_for_review", "review_approved")
                        ),
                    )
                ):
                    node.status = "cancelled"
                    node.completed_at = now
                    node.error_message = "Workflow run was cancelled before completion"
        elif job.status == "running":
            job.status = "cancel_requested"
            if quality_control_run is not None:
                quality_control_run.status = "cancel_requested"
            if backup is not None:
                backup.status = "cancel_requested"
            if workflow_run is not None:
                workflow_run.status = "cancel_requested"
                workflow_run.result_json = {
                    **dict(workflow_run.result_json or {}),
                    "stage": "cancel_requested",
                    "child_job_cancellation": child_cancellation,
                }
        else:
            raise ConflictError(
                "Only queued, running, or waiting-for-review jobs can be cancelled"
            )
        self.session.commit()
        self.session.refresh(job)
        return job
