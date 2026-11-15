"""Recompute a reviewed ecological selection through the shared analysis service."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.workflow_execution import WorkflowArtifact
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.ecology_analysis import EcologyAnalysisService


def verified_ecology_analysis_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="ecology_verified_analysis",
        display_name="Recalculate Reviewed Ecological Analysis",
        category="Scientific analysis",
        description=(
            "Recalculate a saved scientist-reviewed ecological selection "
            "against current project evidence."
        ),
        input_ports=[
            WorkflowPortDefinition(
                port_id="project",
                display_name="Project",
                accepted_types=["project_reference"],
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="analysis",
                display_name="Reviewed ecological result",
                accepted_types=["verified_ecology_analysis"],
                multiple=True,
            )
        ],
        required_parameters=["analysis_id"],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "The saved standalone analysis pins immutable scientist-reviewed inputs.",
            "Changed evidence requires explicit review and a new analysis revision.",
        ],
    )


def execute_verified_ecology_analysis(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: Mapping[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings
    if set(parameters) - {"analysis_id", "__workflow_run_id", "__workflow_node_run_id"}:
        raise ValidationError("Reviewed ecological analysis has unsupported parameters")
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Reviewed ecological analysis requires the current project")
    identifier = parameters.get("analysis_id")
    try:
        if not isinstance(identifier, str):
            raise ValueError
        analysis_id = str(UUID(identifier))
    except ValueError as exc:
        raise ValidationError("A saved reviewed ecological analysis UUID is required") from exc
    analysis = EcologyAnalysisService(session).get(project_id, analysis_id)
    if analysis.stale:
        raise ConflictError("Selected evidence has changed; save a freshly reviewed analysis")
    return [
        {
            "port_id": "analysis",
            "data_type": "verified_ecology_analysis",
            "payload": analysis.model_dump(mode="json"),
        }
    ]
