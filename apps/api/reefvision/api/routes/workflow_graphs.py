"""Workflow registry, validation, persistence, and execution endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.api.routes.spatial_mesh_preview_v14 import router as mesh_preview_router
from reefvision.schemas.workflow_execution import (
    WorkflowGraphRecordResponse,
    WorkflowGraphSaveRequest,
    WorkflowReviewResumeRequest,
    WorkflowRunCreateRequest,
    WorkflowRunDetailResponse,
    WorkflowRunResponse,
)
from reefvision.schemas.workflow_graphs import (
    WorkflowGraphPlanResponse,
    WorkflowGraphRequest,
    WorkflowGraphValidationResponse,
    WorkflowNodeDefinitionResponse,
)
from reefvision.services.workflow_execution import WorkflowExecutionService
from reefvision.services.workflow_graphs import WorkflowGraphService
from reefvision.services.workflow_review import resume_review_gate

router = APIRouter(tags=["workflow-graphs"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/workflow-graphs/node-registry",
    response_model=list[WorkflowNodeDefinitionResponse],
)
def get_workflow_node_registry(session: DbSession) -> list[WorkflowNodeDefinitionResponse]:
    return WorkflowGraphService(session).node_registry()


@router.post(
    "/projects/{project_id}/workflow-graphs/validate",
    response_model=WorkflowGraphValidationResponse,
)
def validate_workflow_graph(
    project_id: str,
    payload: WorkflowGraphRequest,
    session: DbSession,
) -> WorkflowGraphValidationResponse:
    return WorkflowGraphService(session).validate(project_id, payload)


@router.post(
    "/projects/{project_id}/workflow-graphs/plan",
    response_model=WorkflowGraphPlanResponse,
)
def plan_workflow_graph(
    project_id: str,
    payload: WorkflowGraphRequest,
    session: DbSession,
) -> WorkflowGraphPlanResponse:
    return WorkflowGraphService(session).plan(project_id, payload)


@router.get(
    "/projects/{project_id}/workflow-graphs",
    response_model=list[WorkflowGraphRecordResponse],
)
def list_saved_workflow_graphs(
    project_id: str,
    session: DbSession,
) -> list[WorkflowGraphRecordResponse]:
    return WorkflowExecutionService(session).list_graphs(project_id)


@router.post(
    "/projects/{project_id}/workflow-graphs",
    response_model=WorkflowGraphRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_workflow_graph(
    project_id: str,
    payload: WorkflowGraphSaveRequest,
    session: DbSession,
) -> WorkflowGraphRecordResponse:
    return WorkflowExecutionService(session).save_graph(project_id, payload)


@router.get(
    "/projects/{project_id}/workflow-runs",
    response_model=list[WorkflowRunResponse],
)
def list_workflow_runs(
    project_id: str,
    session: DbSession,
) -> list[WorkflowRunResponse]:
    return WorkflowExecutionService(session).list_runs(project_id)


@router.post(
    "/projects/{project_id}/workflow-runs",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_workflow_run(
    project_id: str,
    payload: WorkflowRunCreateRequest,
    request: Request,
    session: DbSession,
) -> WorkflowRunResponse:
    return WorkflowExecutionService(session, request.app.state.settings).queue_run(
        project_id,
        payload,
    )


@router.get(
    "/workflow-runs/{run_id}",
    response_model=WorkflowRunDetailResponse,
)
def get_workflow_run(
    run_id: str,
    session: DbSession,
) -> WorkflowRunDetailResponse:
    return WorkflowExecutionService(session).get_run_detail(run_id)


@router.post(
    "/workflow-node-runs/{node_run_id}/resume-review",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_workflow_review(
    node_run_id: str,
    payload: WorkflowReviewResumeRequest,
    session: DbSession,
) -> WorkflowRunResponse:
    return resume_review_gate(session, node_run_id, payload)


router.include_router(mesh_preview_router)
