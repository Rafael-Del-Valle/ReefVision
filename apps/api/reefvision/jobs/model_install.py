"""Retire queued legacy acquisition jobs without touching model files."""

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job


def process_model_install_job(
    settings: Settings, factory: sessionmaker[Session], job_id: str
) -> bool:
    """Consume an obsolete queued job once; never acquire or delete any assets."""
    with factory() as session:
        result = cast(
            CursorResult[object],
            session.execute(
                update(Job)
                .where(Job.id == job_id, Job.job_type == "model_install", Job.status == "queued")
                .values(
                    status="failed",
                    completed_at=datetime.now(UTC),
                    error_message=(
                        "Model downloads are disabled. Train from an architecture or register "
                        "a compatible local model."
                    ),
                    result_json={"stage": "policy_disabled"},
                )
            ),
        )
        session.commit()
        return result.rowcount == 1
