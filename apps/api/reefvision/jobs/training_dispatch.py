"""Task-aware training worker dispatch."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, TrainingRun
from reefvision.jobs.segmentation_training import process_segmentation_training_job
from reefvision.jobs.semantic_training import process_semantic_training_job
from reefvision.jobs.training import process_training_job
from reefvision.ml.semantic_segmentation import SEMANTIC_SEGMENTATION_TASK


def process_task_aware_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    """Route queued training jobs without changing the stable detection worker."""

    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "training" or job.status != "queued":
            return False
        run_id = str(job.request_json.get("training_run_id", ""))
        run = session.get(TrainingRun, run_id)
        if run is None:
            return process_training_job(settings, factory, job_id)
        task = run.task

    if task == "segment":
        return process_segmentation_training_job(settings, factory, job_id)
    if task == SEMANTIC_SEGMENTATION_TASK:
        return process_semantic_training_job(settings, factory, job_id)
    return process_training_job(settings, factory, job_id)
