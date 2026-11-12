"""Cooperatively cancellable worker for pose identity association."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, PoseIdentityAssociationRun
from reefvision.services.pose_identity_tracking import (
    PoseIdentityTrackingCancelled,
    PoseIdentityTrackingService,
)


def process_pose_identity_tracking_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    del settings
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "pose_identity_tracking":
            return False
        if job.status not in {"queued", "cancel_requested"}:
            return False
        run_id = str((job.request_json or {}).get("run_id") or "")
        run = session.get(PoseIdentityAssociationRun, run_id)
        if run is None:
            job.status = "failed"
            job.error_message = "Pose identity association run disappeared"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return True
        if job.status == "cancel_requested":
            job.status = "cancelled"
            job.completed_at = datetime.now(UTC)
            job.result_json = {"run_id": run.id, "stage": "cancelled"}
            run.status = "cancelled"
            run.progress_json = {"stage": "cancelled", "current": 0, "total": 0}
            run.completed_at = job.completed_at
            session.commit()
            return True

        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        run.status = "running"
        run.progress_json = {
            "stage": "associating",
            "current": 0,
            "total": job.progress_total,
        }
        session.commit()
        active_job = job
        active_run = run

        def cancellation_check() -> None:
            session.expire(active_job)
            if active_job.status == "cancel_requested":
                raise PoseIdentityTrackingCancelled

        def progress(current: int, total: int) -> None:
            active_job.progress_current = current
            active_job.progress_total = total
            active_job.result_json = {
                "run_id": active_run.id,
                "stage": "persisting",
                "current": current,
                "total": total,
            }
            active_run.progress_json = {
                "stage": "persisting",
                "current": current,
                "total": total,
            }

        try:
            completed = PoseIdentityTrackingService(session).execute(
                active_run.id,
                [str(value) for value in active_job.request_json.get("source_track_ids", [])],
                expected_manifest=dict(active_job.request_json.get("input_manifest") or {}),
                cancellation_check=cancellation_check,
                progress=progress,
            )
            job.status = "completed"
            job.progress_current = job.progress_total
            job.completed_at = completed.completed_at or datetime.now(UTC)
            job.result_json = {
                "run_id": run.id,
                "run_revision": completed.revision,
                "stage": "completed",
            }
            session.commit()
        except PoseIdentityTrackingCancelled:
            session.rollback()
            job = session.get(Job, job_id)
            run = session.get(PoseIdentityAssociationRun, run_id)
            assert job is not None and run is not None
            job.status = "cancelled"
            job.completed_at = datetime.now(UTC)
            job.result_json = {"run_id": run.id, "stage": "cancelled"}
            run.status = "cancelled"
            run.progress_json = {
                "stage": "cancelled",
                "current": job.progress_current,
                "total": job.progress_total,
            }
            run.completed_at = job.completed_at
            session.commit()
        except Exception as exc:
            session.rollback()
            job = session.get(Job, job_id)
            run = session.get(PoseIdentityAssociationRun, run_id)
            assert job is not None and run is not None
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(UTC)
            job.result_json = {"run_id": run.id, "stage": "failed"}
            run.status = "failed"
            run.error_json = {"type": type(exc).__name__, "message": str(exc)}
            run.progress_json = {"stage": "failed"}
            run.completed_at = job.completed_at
            session.commit()
        return True
