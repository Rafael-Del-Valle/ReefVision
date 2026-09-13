"""Background-job persistence operations."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
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
        statement = (
            update(Job)
            .where(
                Job.status.in_(("running", "cancel_requested")),
                Job.job_type.notin_(("training", "video_tracking")),
            )
            .values(
                status="queued",
                started_at=None,
                error_message="Recovered after interruption",
            )
        )
        result = cast(CursorResult[Any], self.session.execute(statement))
        return int(result.rowcount or 0)
