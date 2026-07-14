"""Background-job status and retry endpoints."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.schemas.jobs import JobResponse
from reefvision.services.jobs import JobService
from reefvision.storage.catalog_models import catalog_model_directories

router = APIRouter(tags=["jobs"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _live_model_install_response(job: Job, settings: Settings) -> JobResponse:
    """Overlay the on-disk partial-download size onto the persisted job state.

    SQLite remains the durable source of truth, but the temporary file is the
    most direct measurement of bytes received by the downloader. Reading it
    here keeps the desktop progress bar live even if a database progress write
    is delayed or not yet visible to the polling connection.
    """

    if getattr(job, "created_at", None) is None:
        job.created_at = datetime.now(UTC)

    response = JobResponse.model_validate(job)
    if job.job_type != "model_install" or job.status not in {
        "running",
        "cancel_requested",
    }:
        return response

    temporary_dir = catalog_model_directories(settings)["temporary_downloads"]
    partial_sizes: list[int] = []
    for partial_path in temporary_dir.glob(f"{job.id}-*.part"):
        try:
            partial_sizes.append(partial_path.stat().st_size)
        except FileNotFoundError:
            # The downloader may atomically move or remove the file between
            # directory enumeration and stat during finalization.
            continue
    if not partial_sizes:
        return response

    live_bytes = max(partial_sizes)
    if response.progress_total > 0:
        live_bytes = min(live_bytes, response.progress_total)
    if live_bytes <= response.progress_current:
        return response

    result_json = dict(response.result_json or {})
    result_json["bytes_downloaded"] = live_bytes
    result_json["progress_source"] = "partial_file"
    return response.model_copy(
        update={
            "progress_current": live_bytes,
            "result_json": result_json,
        }
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    request: Request,
    session: DbSession,
    response: Response,
) -> JobResponse:
    # Job status is live state. Desktop webviews must never reuse a cached
    # response while polling model-download progress.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    job = JobService(session).get(job_id)
    settings: Settings = request.app.state.settings
    return _live_model_install_response(job, settings)


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: str, session: DbSession) -> JobResponse:
    return JobResponse.model_validate(JobService(session).retry(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: str, session: DbSession) -> JobResponse:
    return JobResponse.model_validate(JobService(session).cancel(job_id))
