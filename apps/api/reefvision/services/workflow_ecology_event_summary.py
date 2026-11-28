"""Publish a saved reviewed ecological event summary in Workflow Builder."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError as InvalidConfiguration
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.ecology_event_summary import EventSummaryCreate
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
        required_parameters=[],
        optional_parameters={"summary_id": "", "configuration": {}},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Use a saved summary, or provide the confirmed configuration in advanced parameters."
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
    identifier = parameters.get("summary_id")
    configuration = parameters.get("configuration")
    if bool(identifier) == bool(configuration):
        raise ValidationError("Provide exactly one saved summary ID or reviewed configuration")
    service = EcologyEventSummaryService(session)
    try:
        record = (
            service.get(project_id, str(UUID(str(identifier))))
            if identifier
            else service.save(project_id, EventSummaryCreate.model_validate(configuration))
        )
    except InvalidConfiguration as exc:
        raise ValidationError(f"Invalid reviewed event configuration: {exc}") from exc
    except ValueError as exc:
        raise ValidationError("Choose a saved event summary UUID") from exc
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
                "summary_id": str(record.id),
                "content_sha256": record.content_sha256,
                "organisms": [row.model_dump(mode="json") for row in record.snapshot.organisms],
                "units": [row.model_dump(mode="json") for row in record.snapshot.units],
            },
        }
    ]
