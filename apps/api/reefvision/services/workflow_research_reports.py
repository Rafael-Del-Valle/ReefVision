"""Expose persisted publication figures as a typed workflow output."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError as InvalidConfiguration
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.research_reports import FigureRequest
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
        required_parameters=[],
        optional_parameters={"report_id": "", "configuration": {}},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Choose a saved report, or provide its figure configuration in advanced parameters."
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
    identifier = parameters.get("report_id")
    configuration = parameters.get("configuration")
    if bool(identifier) == bool(configuration):
        raise ValidationError("Provide exactly one saved report ID or figure configuration")
    service = ResearchReportService(session)
    try:
        report = (
            service.get(project_id, str(UUID(str(identifier))))
            if identifier
            else service.save(project_id, FigureRequest.model_validate(configuration))
        )
    except InvalidConfiguration as exc:
        raise ValidationError(f"Invalid research figure configuration: {exc}") from exc
    except ValueError as exc:
        raise ValidationError("Choose a saved research report UUID") from exc
    if report.stale:
        raise ConflictError("Recalculate the changed source before republishing the figure")
    return [
        {
            "port_id": "figure",
            "data_type": "research_report_figure",
            "payload": {
                "project_id": project_id,
                "report_id": str(report.id),
                "content_sha256": report.content_sha256,
                "source_sha256": report.snapshot.source_sha256,
                "method": report.snapshot.method,
            },
        }
    ]
