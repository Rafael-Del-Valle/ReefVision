"""Background-job persistence operations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: Job) -> None:
        self.session.add(job)

    def get(self, job_id: str) -> Job | None:
        return self.session.get(Job, job_id)

    def next_queued(self) -> Job | None:
        statement = (
            select(Job).where(Job.status == "queued").order_by(Job.created_at, Job.id).limit(1)
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

        return len(jobs)
