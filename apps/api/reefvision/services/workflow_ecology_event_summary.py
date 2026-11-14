"""Publish a saved reviewed ecological event summary in Workflow Builder."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.ecology_event_summary import EcologyEventSummaryService


def event_summary_workflow_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="ecology_event_summary",
        display_name="Reviewed Ecological Event Summary",
        category="Scientific analysis",
        description="Reproduce organism event rates from scoped reviewed ReefPose evidence.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="summary",
                display_name="Reviewed event summary",
                accepted_types=["reviewed_ecology_event_summary"],
                multiple=True,
            )
        ],
        required_parameters=["summary_id"],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Save a reviewed event summary in Organisms & ecology to replay it here."
        ],
    )


def execute_event_summary(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: Mapping[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Event summary replay requires the current project")
    try:
        identifier = str(UUID(parameters["summary_id"]))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Select a saved reviewed event summary") from exc
    record = EcologyEventSummaryService(session).get(project_id, identifier)
    if record.stale_reasons:
        raise ConflictError(
            "Event or sampling evidence changed. Review the source and save a new summary."
        )
    return [
        {
            "port_id": "summary",
            "data_type": "reviewed_ecology_event_summary",
            "payload": {
                "project_id": project_id,
                "summary_id": identifier,
                "content_sha256": record.content_sha256,
                "organisms": [row.model_dump(mode="json") for row in record.snapshot.organisms],
                "units": [row.model_dump(mode="json") for row in record.snapshot.units],
            },
        }
    ]
