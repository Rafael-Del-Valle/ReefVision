"""Selected SAM 2.1 checkpoint installation and status endpoints."""

from __future__ import annotations

from threading import Thread
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
 from sqlalchemy.orm import Session, sessionmaker

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import Project
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.jobs import JobResponse
from reefvision.services.sam2_install import (
    SAM2_REPOSITORIES,
    process_sam2_install,
    queue_sam2_install,
    sam2_status,
)

router = APIRouter(tags=["sam2-models"])
DbSession = Annotated[Session, Depends(get_db_session)]


 def _launch_sam2_thread(
    settings: Settings, factory: sessionmaker[Session], job_id: str
) -> None:
    Thread(
        target=process_sam2_install,
        args=(settings, factory, job_id),
        name=f"reefvision-sam2-install-{job_id[:8]}",
        daemon=True,
    ).start()


@router.get("/projects/{project_id}/sam2-models")
def sam2_models(
    project_id: str, request: Request, session: DbSession
) -> list[dict[str, object]]:
    if session.get(Project, project_id) is None:
        raise NotFoundError("Project not found")
    settings: Settings = request.app.state.settings
    return [sam2_status(settings, variant) for variant in SAM2_REPOSITORIES]


@router.post("/projects/{project_id}/sam2-models/{variant}/install", response_model=JobResponse)
def install_sam2_model(
    project_id: str,
    variant: str,
     request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
) -> JobResponse:
     job = queue_sam2_install(session, project_id, variant)
    response = JobResponse.model_validate(job)
    settings: Settings = request.app.state.settings
    if settings.background_worker_enabled:
        background_tasks.add_task(
            _launch_sam2_thread,
            settings,
            request.app.state.session_factory,
            job.id,
        )
    return response
