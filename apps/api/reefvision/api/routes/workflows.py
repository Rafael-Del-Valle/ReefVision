"""Fusion workflow graph definitions, templates, and validation endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.workflows import (
    WorkflowNodeDefinition,
    WorkflowTemplate,
    WorkflowValidationRequest,
    WorkflowValidationResponse,
)
from reefvision.services.workflows import WorkflowService

router = APIRouter(tags=["workflows"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/workflow-node-definitions",
    response_model=list[WorkflowNodeDefinition],
)
def list_workflow_node_definitions() -> list[WorkflowNodeDefinition]:
    return WorkflowService.definitions()


@router.get(
    "/workflow-templates",
    response_model=list[WorkflowTemplate],
)
def list_workflow_templates() -> list[WorkflowTemplate]:
    return WorkflowService.templates()


@router.post(
    "/projects/{project_id}/workflows/validate",
    response_model=WorkflowValidationResponse,
)
def validate_workflow(
    project_id: str,
    payload: WorkflowValidationRequest,
    session: DbSession,
) -> WorkflowValidationResponse:
    return WorkflowService(session).validate(project_id, payload)
