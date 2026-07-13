"""Model catalog and tracker catalog endpoints."""

from threading import Thread
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.domain.errors import CatalogResourceError
from reefvision.jobs.model_install import process_model_install_job
from reefvision.schemas.bootstrap import ModelHubBootstrapResponse
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.model_catalog import (
    CatalogInstallRequest,
    CatalogReadinessResponse,
    CatalogTask,
    CatalogVerifyResponse,
    CatalogWorkflow,
    ModelCatalogEntryResponse,
    ModelCatalogResponse,
    TrackerCatalogResponse,
)
from reefvision.services.bootstrap import BootstrapService
from reefvision.services.model_catalog import ModelCatalogService
from reefvision.services.model_install import ModelInstallService

router = APIRouter(tags=["model-catalog"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ModelCatalogService:
    settings: Settings = request.app.state.settings
    return ModelCatalogService(session, settings)


def bootstrap_service(request: Request, session: Session) -> BootstrapService:
    settings: Settings = request.app.state.settings
    return BootstrapService(session, settings)


def install_service(request: Request, session: Session) -> ModelInstallService:
    settings: Settings = request.app.state.settings
    return ModelInstallService(session, settings)


def _catalog_http_error(exc: CatalogResourceError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.details)


def _start_model_install_thread(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> None:
    """Start the one-shot installer only after the HTTP response is finalized."""

    Thread(
        target=process_model_install_job,
        args=(settings, factory, job_id),
        name=f"reefvision-model-install-{job_id[:8]}",
        daemon=True,
    ).start()


@router.get(
    "/projects/{project_id}/model-catalog",
    response_model=ModelCatalogResponse,
)
def list_project_model_catalog(
    project_id: str,
    request: Request,
    session: DbSession,
    workflow: CatalogWorkflow | None = None,
    task: CatalogTask | None = None,
    include_unavailable: bool = True,
) -> ModelCatalogResponse:
    try:
        return service(request, session).list_project_catalog(
            project_id,
            workflow=workflow,
            task=task,
            include_unavailable=include_unavailable,
        )
    except CatalogResourceError as exc:
        raise _catalog_http_error(exc) from exc


@router.get(
    "/projects/{project_id}/model-hub/bootstrap",
    response_model=ModelHubBootstrapResponse,
)
def get_model_hub_bootstrap(
    project_id: str,
    request: Request,
    session: DbSession,
) -> ModelHubBootstrapResponse:
    try:
        return bootstrap_service(request, session).model_hub_bootstrap(project_id)
    except CatalogResourceError as exc:
        raise _catalog_http_error(exc) from exc


@router.get(
    "/projects/{project_id}/model-catalog/{catalog_id:path}",
    response_model=ModelCatalogEntryResponse,
)
def get_project_model_catalog_item(
    project_id: str,
    catalog_id: str,
    request: Request,
    session: DbSession,
) -> ModelCatalogEntryResponse:
    try:
        return service(request, session).get_project_catalog_item(project_id, catalog_id)
    except CatalogResourceError as exc:
        raise _catalog_http_error(exc) from exc


@router.post(
    "/projects/{project_id}/model-installs/{catalog_id:path}",
    response_model=JobResponse,
)
def install_catalog_model(
    project_id: str,
    catalog_id: str,
    payload: CatalogInstallRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: DbSession,
) -> JobResponse:
    job = install_service(request, session).create_install_job(
        project_id, catalog_id, confirmed=payload.confirmed
    )
    # Freeze the response before any worker can mutate the ORM row. Previously,
    # the installer thread raced FastAPI response serialization, so the model
    # downloaded successfully while the confirmation mutation appeared to fail
    # or remain unresolved in the desktop UI.
    response = JobResponse.model_validate(job)
    settings: Settings = request.app.state.settings
    if settings.background_worker_enabled:
        # Launch only after FastAPI has finalized and sent the response. The
        # normal queue worker still provides restart recovery; atomic claiming
        # prevents duplicate execution if both paths see the same queued job.
        background_tasks.add_task(
            _start_model_install_thread,
            settings,
            request.app.state.session_factory,
            job.id,
        )
    return response


@router.get(
    "/projects/{project_id}/model-readiness/{catalog_id:path}",
    response_model=CatalogReadinessResponse,
)
def get_catalog_model_readiness(
    project_id: str, catalog_id: str, request: Request, session: DbSession
) -> CatalogReadinessResponse:
    return install_service(request, session).readiness(project_id, catalog_id)


@router.post(
    "/projects/{project_id}/model-verifications/{catalog_id:path}",
    response_model=CatalogVerifyResponse,
)
def verify_catalog_model(
    project_id: str, catalog_id: str, request: Request, session: DbSession
) -> CatalogVerifyResponse:
    return install_service(request, session).verify(project_id, catalog_id)


@router.delete(
    "/projects/{project_id}/model-installs/{catalog_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_catalog_model(
    project_id: str, catalog_id: str, request: Request, session: DbSession
) -> None:
    install_service(request, session).remove(project_id, catalog_id)


@router.get("/tracker-catalog", response_model=TrackerCatalogResponse)
def get_tracker_catalog(request: Request, session: DbSession) -> TrackerCatalogResponse:
    return service(request, session).tracker_catalog()
