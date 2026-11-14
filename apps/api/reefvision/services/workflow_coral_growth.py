"""Execute the reviewed coral calculation through the shared service."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.workflow_execution import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.coral_graph import CoralGraphService
from reefvision.storage.datasets import canonical_json_sha256


def coral_growth_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="ecology_coral_growth",
        display_name="Calculate Reviewed Coral Branch Growth",
        category="Scientific analysis",
        description="Calculate two-date growth from a current scientist-reviewed correspondence.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="growth",
                display_name="Reviewed branch growth",
                accepted_types=["coral_branch_growth"],
                multiple=True,
            )
        ],
        required_parameters=["correspondence_revision_id"],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Review both graphs and their correspondence in Organisms and ecology."
        ],
    )


def execute_coral_growth(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    if set(parameters) - {
        "correspondence_revision_id",
        "__workflow_run_id",
        "__workflow_node_run_id",
    }:
        raise ValidationError("Reviewed branch growth has unsupported parameters")
    project = inputs.get("project", [])
    if len(project) != 1 or project[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Reviewed branch growth requires the current project")
    identifier = parameters.get("correspondence_revision_id")
    try:
        if not isinstance(identifier, str):
            raise ValueError
        correspondence_id = str(UUID(identifier))
    except ValueError as exc:
        raise ValidationError("A reviewed correspondence revision UUID is required") from exc
    result = CoralGraphService(session, settings).calculate_growth(project_id, correspondence_id)
    snapshot = result.model_dump(mode="json")
    return [
        {
            "port_id": "growth",
            "data_type": "coral_branch_growth",
            "payload": {
                "project_id": project_id,
                "correspondence_revision_id": correspondence_id,
                "snapshot": snapshot,
                "content_sha256": canonical_json_sha256(snapshot),
            },
        }
    ]
