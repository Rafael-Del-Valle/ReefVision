"""Cancellable workers for Phase 5 measurement and event runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, PoseEventDetectionRun, PoseMeasurementRun
from reefvision.services.pose_biological_measurement import (
    PoseBiologicalMeasurementCancelled,
    PoseBiologicalMeasurementService,
)


def process_pose_biological_measurement_job(
    settings: Settings, factory: sessionmaker[Session], job_id: str
) -> bool:
    del settings
    with factory() as session:
        job = session.get(Job, job_id)
        if (
            job is None
            or job.job_type
            not in {"pose_biological_measurement", "pose_biological_event_detection"}
            or job.status not in {"queued", "cancel_requested"}
        ):
            return False
        run_id = str((job.request_json or {}).get("run_id") or "")
        model = (
            PoseMeasurementRun
            if job.job_type == "pose_biological_measurement"
            else PoseEventDetectionRun
        )
        run = cast(
            PoseMeasurementRun | PoseEventDetectionRun | None,
            session.get(model, run_id),
        )
        if run is None:
            job.status = "failed"
            job.error_message = "Analysis run disappeared"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return True
        if job.status == "cancel_requested":
            job.status = run.status = "cancelled"
            job.completed_at = run.completed_at = datetime.now(UTC)
            session.commit()
            return True
        job.status = run.status = "running"
        job.started_at = datetime.now(UTC)
        session.commit()

        def cancel() -> None:
            with factory() as status_session:
                if (
                    status_session.scalar(select(Job.status).where(Job.id == job_id))
                    == "cancel_requested"
                ):
                    raise PoseBiologicalMeasurementCancelled

        def progress(current: int, total: int) -> None:
            with factory() as progress_session:
                j = progress_session.get(Job, job_id)
                r = cast(
                    PoseMeasurementRun | PoseEventDetectionRun | None,
                    progress_session.get(model, run_id),
                )
                if j is None or r is None or j.status == "cancel_requested":
                    raise PoseBiologicalMeasurementCancelled
                j.progress_current = current
                j.progress_total = total
                j.result_json = {
                    "run_id": run_id,
                    "stage": "running",
                    "current": current,
                    "total": total,
                }
                r.progress_json = {"stage": "running", "current": current, "total": total}
                progress_session.commit()

        try:
            service = PoseBiologicalMeasurementService(session)
            completed = (
                service.execute_measurements(run_id, cancellation_check=cancel, progress=progress)
                if job.job_type == "pose_biological_measurement"
                else service.execute_events(run_id, cancellation_check=cancel, progress=progress)
            )
            session.refresh(job)
            job.status = "completed"
            job.progress_current = job.progress_total
            job.completed_at = completed.completed_at
            job.result_json = {
                "run_id": run_id,
                "stage": "completed",
                "result_sha256": completed.result_sha256,
            }
            session.commit()
        except PoseBiologicalMeasurementCancelled:
            session.rollback()
            job = session.get(Job, job_id)
            run = cast(
                PoseMeasurementRun | PoseEventDetectionRun | None,
                session.get(model, run_id),
            )
            assert job and run
            job.status = run.status = "cancelled"
            job.completed_at = run.completed_at = datetime.now(UTC)
            session.commit()
        except Exception as exc:
            session.rollback()
            job = session.get(Job, job_id)
            run = cast(
                PoseMeasurementRun | PoseEventDetectionRun | None,
                session.get(model, run_id),
            )
            assert job and run
            job.status = run.status = "failed"
            job.error_message = str(exc)
            job.completed_at = run.completed_at = datetime.now(UTC)
            run.error_json = {"type": type(exc).__name__, "message": str(exc)}
            session.commit()
        return True
