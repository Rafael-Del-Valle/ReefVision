"""Persisted workflow revision, execution, recovery, and cleanup routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.workflow_cleanup import (
    WorkflowArtifactCleanupApplyRequest,
    WorkflowArtifactCleanupApplyResponse,
    WorkflowArtifactCleanupPreviewRequest,
    WorkflowArtifactCleanupPreviewResponse,
    WorkflowArtifactQuarantineResponse,
    WorkflowArtifactRestoreRequest,
    WorkflowArtifactRestoreResponse,
)
from reefvision.schemas.workflows import (
    WorkflowArtifactResponse,
    WorkflowCreateRequest,
    WorkflowDetailResponse,
    WorkflowResponse,
    WorkflowRevisionCreateRequest,
    WorkflowRevisionResponse,
    WorkflowRunCreateRequest,
    WorkflowRunCreateResponse,
    WorkflowRunResponse,
    WorkflowRunRetryRequest,
)
from reefvision.services.persistent_workflows import PersistentWorkflowService
from reefvision.services.workflow_artifact_cleanup import WorkflowArtifactCleanupService

router = APIRouter(tags=["workflow-persistence"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/projects/{project_id}/workflows",
    response_model=list[WorkflowResponse],
)
def list_project_workflows(
    project_id: str,
    session: DbSession,
) -> list[WorkflowResponse]:
    return PersistentWorkflowService(session).list_workflows(project_id)


@router.post(
    "/projects/{project_id}/workflows",
    response_model=WorkflowDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_workflow(
    project_id: str,
    payload: WorkflowCreateRequest,
    session: DbSession,
) -> WorkflowDetailResponse:
    return PersistentWorkflowService(session).create(project_id, payload)


@router.get("/workflows/{workflow_id}", response_model=WorkflowDetailResponse)
def get_persisted_workflow(
    workflow_id: str,
    session: DbSession,
) -> WorkflowDetailResponse:
    return PersistentWorkflowService(session).get(workflow_id)


@router.post(
    "/workflows/{workflow_id}/revisions",
    response_model=WorkflowDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_revision(
    workflow_id: str,
    payload: WorkflowRevisionCreateRequest,
    session: DbSession,
) -> WorkflowDetailResponse:
    return PersistentWorkflowService(session).create_revision(workflow_id, payload)


@router.get(
    "/workflows/{workflow_id}/revisions",
    response_model=list[WorkflowRevisionResponse],
)
def list_workflow_revisions(
    workflow_id: str,
    session: DbSession,
) -> list[WorkflowRevisionResponse]:
    return PersistentWorkflowService(session).list_revisions(workflow_id)


@router.post(
    "/workflows/{workflow_id}/runs",
    response_model=WorkflowRunCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_workflow_run(
    workflow_id: str,
    payload: WorkflowRunCreateRequest,
    session: DbSession,
) -> WorkflowRunCreateResponse:
    return PersistentWorkflowService(session).queue_run(workflow_id, payload)


@router.get(
    "/workflows/{workflow_id}/runs",
    response_model=list[WorkflowRunResponse],
)
def list_workflow_runs(
    workflow_id: str,
    session: DbSession,
) -> list[WorkflowRunResponse]:
    return PersistentWorkflowService(session).list_runs(workflow_id)


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunResponse)
def get_workflow_run(
    run_id: str,
    session: DbSession,
) -> WorkflowRunResponse:
    return PersistentWorkflowService(session).get_run(run_id)


@router.post(
    "/workflow-runs/{run_id}/retry",
    response_model=WorkflowRunCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_workflow_run(
    run_id: str,
    payload: WorkflowRunRetryRequest,
    session: DbSession,
) -> WorkflowRunCreateResponse:
    return PersistentWorkflowService(session).retry_run(run_id, payload)


@router.get(
    "/workflow-runs/{run_id}/artifacts",
    response_model=list[WorkflowArtifactResponse],
)
def list_workflow_run_artifacts(
    run_id: str,
    session: DbSession,
) -> list[WorkflowArtifactResponse]:
    return PersistentWorkflowService(session).artifacts(run_id)


@router.post(
    "/workflow-runs/{run_id}/artifact-cleanup/preview",
    response_model=WorkflowArtifactCleanupPreviewResponse,
)
def preview_workflow_artifact_cleanup(
    run_id: str,
    payload: WorkflowArtifactCleanupPreviewRequest,
    request: Request,
    session: DbSession,
) -> WorkflowArtifactCleanupPreviewResponse:
    return WorkflowArtifactCleanupService(
        session,
        request.app.state.settings,
    ).preview(run_id, payload)


@router.post(
    "/workflow-runs/{run_id}/artifact-cleanup/apply",
    response_model=WorkflowArtifactCleanupApplyResponse,
)
def apply_workflow_artifact_cleanup(
    run_id: str,
    payload: WorkflowArtifactCleanupApplyRequest,
    request: Request,
    session: DbSession,
) -> WorkflowArtifactCleanupApplyResponse:
    return WorkflowArtifactCleanupService(
        session,
        request.app.state.settings,
    ).apply(run_id, payload)


@router.get(
    "/workflow-runs/{run_id}/artifact-quarantine",
    response_model=WorkflowArtifactQuarantineResponse,
)
def list_workflow_artifact_quarantine(
    run_id: str,
    request: Request,
    session: DbSession,
) -> WorkflowArtifactQuarantineResponse:
    return WorkflowArtifactCleanupService(
        session,
        request.app.state.settings,
    ).quarantine(run_id)


@router.post(
    "/workflow-runs/{run_id}/artifact-quarantine/restore",
    response_model=WorkflowArtifactRestoreResponse,
)
def restore_workflow_artifact_quarantine(
    run_id: str,
    payload: WorkflowArtifactRestoreRequest,
    request: Request,
    session: DbSession,
) -> WorkflowArtifactRestoreResponse:
    return WorkflowArtifactCleanupService(
        session,
        request.app.state.settings,
    ).restore(run_id, payload)
