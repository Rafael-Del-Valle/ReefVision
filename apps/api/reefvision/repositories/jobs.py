"""Background-job persistence operations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import Job


def paired_owner_active(
    session: Session, project_id: str | None, owner_id: str, *, queued: bool = False
) -> bool:
    owner = session.get(Job, owner_id, populate_existing=True)
    return (
        owner is not None
        and project_id is not None
        and owner.project_id == project_id
        and owner.job_type in {"paired_model_comparison", "workflow_run"}
        and owner.status in ({"queued", "running"} if queued else {"running"})
    )


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: Job) -> None:
        self.session.add(job)

    def get(self, job_id: str) -> Job | None:
        return self.session.get(Job, job_id)

    def next_queued(self) -> Job | None:
        statement = (
            select(Job)
            .where(
                Job.status == "queued",
                # The executing workflow owns its validation and acquisition QC children.
                (
                    Job.job_type.notin_(
                        ("reefpose_validation", "qc", "static_comparison", "temporal_reefpose")
                    )
                )
                | (func.coalesce(Job.request_json["workflow_run_id"].as_string(), "") == ""),
                (Job.job_type != "inference")
                | (func.coalesce(Job.request_json["paired_owner_run_id"].as_string(), "") == ""),
            )
            .order_by(Job.created_at, Job.id)
            .limit(1)
        )
        return self.session.scalar(statement)

    def has_active_jobs(self) -> bool:
        statement = select(Job.id).where(Job.status.in_(("queued", "running", "cancel_requested")))
        return self.session.scalar(statement) is not None

    def recover_interrupted_jobs(self) -> int:
        jobs = list(
            self.session.scalars(
                select(Job).where(
                    Job.status.in_(("running", "cancel_requested")),
                    Job.job_type.notin_(("training", "video_tracking")),
                )
            )
        )
        now = datetime.now(UTC)

        for job in jobs:
            result = dict(job.result_json or {})

            if job.status == "cancel_requested":
                job.status = "cancelled"
                job.completed_at = now
                job.error_message = "Cancellation finalized after ReefVision restart"
                if job.job_type == "pose_evaluation":
                    job.deduplication_key = None
                result.update(
                    {
                        "stage": "cancelled",
                        "recovery": "cancelled_on_startup",
                        "recovered_at": now.isoformat(),
                    }
                )
            else:
                job.status = "queued"
                job.started_at = None
                job.completed_at = None
                job.error_message = "Recovered after interruption"
                result.update(
                    {
                        "stage": "queued",
                        "recovery": "requeued_on_startup",
                        "recovered_at": now.isoformat(),
                    }
                )

            job.result_json = result

        # Startup recovery must see the transitions just applied above, including
        # a formerly running owner that was requeued or cancelled.
        self.session.flush()
        orphans = 0
        children = self.session.scalars(
            select(Job).where(
                Job.job_type == "inference",
                Job.status == "queued",
                func.coalesce(Job.request_json["paired_owner_run_id"].as_string(), "") != "",
            )
        )
        for child in children:
            owner_id = child.request_json["paired_owner_run_id"]
            if isinstance(owner_id, str) and paired_owner_active(
                self.session, child.project_id, owner_id, queued=True
            ):
                continue
            child.status = "cancelled"
            child.completed_at = now
            child.error_message = "Paired comparison stopped before inference resumed"
            child.result_json = {**(child.result_json or {}), "stage": "cancelled"}
            orphans += 1
        return len(jobs) + orphans
