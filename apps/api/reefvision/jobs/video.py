"""Video metadata and frame extraction job."""

from __future__ import annotations

import os
import shutil
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import cv2
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.storage.projects import resolve_managed_project_path


def _finish_job(
    factory: sessionmaker[Session],
    job_id: str,
    *,
    status: str,
    result: dict[str, object],
    error_message: str | None = None,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = status
        job.error_message = error_message
        job.completed_at = datetime.now(UTC)
        job.heartbeat_at = job.completed_at
        job.result_json = result
        session.commit()


def _cancellation_requested(factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        return job is None or job.status == "cancel_requested"


def _remove_empty_parent(path: Path) -> None:
    with suppress(OSError):
        path.parent.rmdir()


def process_video_extract_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "video_extract" or job.status != "queued":
            return False
        now = datetime.now(UTC)
        job.status = "running"
        job.started_at = now
        job.heartbeat_at = now
        job.error_message = None
        request = dict(job.request_json)
        session.commit()

    source = resolve_managed_project_path(settings, str(request["video_path"]))
    output = resolve_managed_project_path(settings, str(request["frames_path"]))
    every_n = max(1, int(request.get("every_n_frames", 1)))
    temporary = output.with_name(f".{output.name}.{uuid4().hex[:8]}.tmp")
    capture = None
    frame_index = 0
    written = 0
    published = False
    try:
        if not source.is_file():
            raise FileNotFoundError("The managed source video is missing")
        if output.exists():
            raise FileExistsError("The managed frame-extraction destination already exists")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary.mkdir(parents=False, exist_ok=False)
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise RuntimeError("Unable to open the managed source video")
        source_frame_count = max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
        estimated_writes = (
            (source_frame_count + every_n - 1) // every_n if source_frame_count else 0
        )
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise RuntimeError("Video extraction job disappeared")
            job.progress_total = estimated_writes
            job.result_json = {
                "stage": "extracting",
                "frames_path": str(request["frames_path"]),
            }
            session.commit()
        while True:
            if _cancellation_requested(factory, job_id):
                _finish_job(
                    factory,
                    job_id,
                    status="cancelled",
                    result={"stage": "cancelled", "written_frame_count": written},
                )
                return True
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % every_n == 0:
                destination = temporary / f"frame_{frame_index:08d}.jpg"
                if not cv2.imwrite(str(destination), frame):
                    raise RuntimeError(f"Unable to write extracted frame {frame_index}")
                written += 1
                with factory() as session:
                    job = session.get(Job, job_id)
                    if job is None:
                        raise RuntimeError("Video extraction job disappeared")
                    job.progress_current = written
                    job.heartbeat_at = datetime.now(UTC)
                    session.commit()
            frame_index += 1
        os.replace(temporary, output)
        published = True
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise RuntimeError("Video extraction job disappeared")
            job.status = "succeeded"
            job.progress_current = written
            job.progress_total = written
            job.result_json = {
                "stage": "completed",
                "frames_path": str(request["frames_path"]),
                "source_frame_count": frame_index,
                "written_frame_count": written,
            }
            job.completed_at = datetime.now(UTC)
            job.heartbeat_at = job.completed_at
            session.commit()
        return True
    except Exception as exc:
        if published:
            shutil.rmtree(output, ignore_errors=True)
        _finish_job(
            factory,
            job_id,
            status="failed",
            result={"stage": "failed", "written_frame_count": written},
            error_message=str(exc),
        )
        return False
    finally:
        if capture is not None:
            capture.release()
        shutil.rmtree(temporary, ignore_errors=True)
        _remove_empty_parent(temporary)
