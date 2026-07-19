"""Background-job status, orchestration, dependency, and retry endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.schemas.jobs import (
    JobDependencyCreateRequest,
    JobDependencyResponse,
    JobDependencyStatus,
    JobEventResponse,
    JobHeartbeatRequest,
    JobResponse,
    JobRetryRequest,
)
from reefvision.services.jobs import JobService
from reefvision.storage.catalog_models import catalog_model_directories

router = APIRouter(tags=["jobs"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _materialize_job_defaults(job: Job) -> None:
    """Populate ORM insert defaults for transient Job instances used by adapters/tests."""

    scalar_defaults: tuple[tuple[str, object], ...] = (
        ("priority", 100),
        ("retry_count", 0),
        ("max_retries", 0),
        ("state_version", 0),
        ("progress_current", 0),
        ("progress_total", 0),
        ("resume_supported", False),
    )
    mapping_defaults = (
        "request_json",
        "checkpoint_json",
        "resource_requirements_json",
        "resource_assignment_json",
    )
    for attribute, default in scalar_defaults:
        if getattr(job, attribute, None) is None:
            setattr(job, attribute, default)
    for attribute in mapping_defaults:
        if getattr(job, attribute, None) is None:
            setattr(job, attribute, {})
    if getattr(job, "created_at", None) is None:
        job.created_at = datetime.now(UTC)


def _live_model_install_response(job: Job, settings: Settings) -> JobResponse:
    """Overlay the on-disk partial-download size onto the persisted job state."""

    _materialize_job_defaults(job)
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
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    job = JobService(session).get(job_id)
    settings: Settings = request.app.state.settings
    return _live_model_install_response(job, settings)


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
def retry_job(
    job_id: str,
    session: DbSession,
    payload: JobRetryRequest | None = None,
) -> JobResponse:
    request = payload or JobRetryRequest()
    return JobResponse.model_validate(
        JobService(session).retry(job_id, from_checkpoint=request.from_checkpoint)
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: str, session: DbSession) -> JobResponse:
    return JobResponse.model_validate(JobService(session).cancel(job_id))


@router.post("/jobs/{job_id}/pause", response_model=JobResponse)
def pause_job(job_id: str, session: DbSession) -> JobResponse:
    return JobResponse.model_validate(JobService(session).request_pause(job_id))


@router.post("/jobs/{job_id}/resume", response_model=JobResponse)
def resume_job(job_id: str, session: DbSession) -> JobResponse:
    return JobResponse.model_validate(JobService(session).resume(job_id))


@router.post("/jobs/{job_id}/heartbeat", response_model=JobResponse)
def heartbeat_job(
    job_id: str,
    payload: JobHeartbeatRequest,
    session: DbSession,
) -> JobResponse:
    return JobResponse.model_validate(
        JobService(session).heartbeat(
            job_id,
            worker_id=payload.worker_id,
            progress_current=payload.progress_current,
            progress_total=payload.progress_total,
            checkpoint=payload.checkpoint,
        )
    )


@router.post("/jobs/{job_id}/dependencies", response_model=JobDependencyResponse)
def add_job_dependency(
    job_id: str,
    payload: JobDependencyCreateRequest,
    session: DbSession,
) -> JobDependencyResponse:
    service = JobService(session)
    service.add_dependency(
        job_id,
        payload.depends_on_job_id,
        required_status=payload.required_status,
    )
    satisfied, dependencies = service.dependency_status(job_id)
    return JobDependencyResponse(
        satisfied=satisfied,
        dependencies=[JobDependencyStatus.model_validate(item) for item in dependencies],
    )


@router.get("/jobs/{job_id}/dependencies", response_model=JobDependencyResponse)
def get_job_dependencies(job_id: str, session: DbSession) -> JobDependencyResponse:
    satisfied, dependencies = JobService(session).dependency_status(job_id)
    return JobDependencyResponse(
        satisfied=satisfied,
        dependencies=[JobDependencyStatus.model_validate(item) for item in dependencies],
    )


@router.get("/jobs/{job_id}/events", response_model=list[JobEventResponse])
def get_job_events(job_id: str, session: DbSession) -> list[JobEventResponse]:
    return [JobEventResponse.model_validate(item) for item in JobService(session).events(job_id)]
