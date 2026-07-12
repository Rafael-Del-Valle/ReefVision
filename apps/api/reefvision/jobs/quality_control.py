"""Background quality-control job execution."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.services.quality_control import QualityControlService


def process_quality_control_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "qc" or job.status not in {"queued", "running"}:
            return False
        run_id = str(job.request_json.get("quality_control_run_id", ""))
        if not run_id:
            job.status = "failed"
            job.error_message = "The quality-control job is missing its run reference"
            session.commit()
            return False
    with factory() as session:
        service = QualityControlService(session, settings)
        service.execute_run(run_id)
        return True
