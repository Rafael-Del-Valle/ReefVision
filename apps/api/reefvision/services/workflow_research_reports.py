"""Expose persisted publication figures as a typed workflow output."""

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
from reefvision.services.research_reports import ResearchReportService


def research_report_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="research_publication_figure",
        display_name="Publish Research Figure",
        category="Scientific analysis",
        description="Recover a saved publication figure and its source provenance.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="figure",
                display_name="Research report",
                accepted_types=["research_report_figure"],
                multiple=True,
            )
        ],
        required_parameters=["report_id"],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Save a figure from reviewed source evidence in the Research reports workspace."
        ],
    )


def execute_research_report(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Research reports require the current project")
    try:
        identifier = str(UUID(str(parameters["report_id"])))
    except (KeyError, ValueError) as exc:
        raise ValidationError("Choose a saved research report") from exc
    report = ResearchReportService(session).get(project_id, identifier)
    if report.stale:
        raise ConflictError("Recalculate the changed source before republishing the figure")
    return [
        {
            "port_id": "figure",
            "data_type": "research_report_figure",
            "payload": {
                "project_id": project_id,
                "report_id": identifier,
                "content_sha256": report.content_sha256,
                "source_sha256": report.snapshot.source_sha256,
                "method": report.snapshot.method,
            },
        }
    ]
