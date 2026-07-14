"""Video metadata and frame extraction job."""

from __future__ import annotations

from datetime import UTC, datetime

import cv2
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.storage.projects import resolve_managed_project_path


def process_video_extract_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "video_extract" or job.status != "queued":
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        request = dict(job.request_json)
        session.commit()

    source = resolve_managed_project_path(settings, str(request["video_path"]))
    output = resolve_managed_project_path(settings, str(request["frames_path"]))
    every_n = max(1, int(request.get("every_n_frames", 1)))
    output.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video: {source}")

    frame_index = 0
    written = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % every_n == 0:
                destination = output / f"frame_{frame_index:08d}.jpg"
                if not cv2.imwrite(str(destination), frame):
                    raise RuntimeError(f"Unable to write frame: {destination}")
                written += 1
            frame_index += 1
    finally:
        capture.release()

    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise RuntimeError("Video extraction job disappeared.")
        job.status = "succeeded"
        job.progress_current = written
        job.progress_total = written
        job.result_json = {
            "frames_path": str(request["frames_path"]),
            "source_frame_count": frame_index,
            "written_frame_count": written,
        }
        job.completed_at = datetime.now(UTC)
        session.commit()
    return True
