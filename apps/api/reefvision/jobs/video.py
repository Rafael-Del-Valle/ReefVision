"""Video frame extraction job."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

import cv2
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, VideoAsset
from reefvision.storage.projects import resolve_managed_project_path


def _fail(
    factory: sessionmaker[Session],
    job_id: str,
    video_id: str,
    message: str,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        video = session.get(VideoAsset, video_id)
        if job is not None:
            job.status = "failed"
            job.error_message = message
            job.completed_at = datetime.now(UTC)
        if video is not None:
            video.status = "extraction_failed"
            video.revision += 1
        session.commit()


def process_video_extract_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "video_extract" or job.status != "queued":
            return False
        request = dict(job.request_json)
        video_id = str(request.get("video_asset_id", ""))
        video = session.get(VideoAsset, video_id)
        if video is None:
            job.status = "failed"
            job.error_message = "Video extraction asset not found"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        video.status = "extracting"
        session.commit()

    source = resolve_managed_project_path(settings, str(request["video_path"]))
    output = resolve_managed_project_path(settings, str(request["frames_path"]))
    every_n = max(1, int(request.get("every_n_frames", 1)))
    try:
        if not source.is_file():
            raise RuntimeError("Managed source video is missing")
        shutil.rmtree(output, ignore_errors=True)
        output.mkdir(parents=True, exist_ok=False)
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
                if frame_index % 100 == 0:
                    with factory() as session:
                        progress_job = session.get(Job, job_id)
                        if progress_job is not None:
                            progress_job.progress_current = written
                            session.commit()
        finally:
            capture.release()

        with factory() as session:
            job = session.get(Job, job_id)
            video = session.get(VideoAsset, video_id)
            if job is None or video is None:
                raise RuntimeError("Video extraction records disappeared")
            job.status = "succeeded"
            job.progress_current = written
            job.progress_total = written
            job.result_json = {
                "frames_path": str(request["frames_path"]),
                "source_frame_count": frame_index,
                "written_frame_count": written,
                "every_n_frames": every_n,
            }
            job.completed_at = datetime.now(UTC)
            video.frame_directory_path = str(request["frames_path"])
            video.status = "frames_ready"
            video.revision += 1
            session.commit()
        return True
    except Exception as exc:
        shutil.rmtree(output, ignore_errors=True)
        _fail(factory, job_id, video_id, str(exc))
        return False
