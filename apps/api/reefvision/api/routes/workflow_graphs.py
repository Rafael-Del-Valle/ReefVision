"""Workflow node registry, validation, and dry-run planning endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.workflow_graphs import (
    WorkflowGraphPlanResponse,
    WorkflowGraphRequest,
    WorkflowGraphValidationResponse,
    WorkflowNodeDefinitionResponse,
)
from reefvision.services.workflow_graphs import WorkflowGraphService

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
