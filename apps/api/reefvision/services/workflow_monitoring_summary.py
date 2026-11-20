"""Replay a frozen local monitoring comparison and its attributed decisions."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError as SchemaError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.workflow_execution import WorkflowArtifact
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.monitoring import MonitoringDigest, MonitoringModel
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.monitoring_summaries import MonitoringSummaryService

NODE = "monitoring_project_summary"


class SummaryPin(MonitoringModel):
    summary_id: UUID
    content_sha256: MonitoringDigest


def monitoring_summary_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type=NODE,
        display_name="Read monitoring project summary",
        category="Scientific analysis",
        description="Reopen a local comparison with each project's effort and alert decisions.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="summary",
                display_name="Monitoring project summary",
                accepted_types=["monitoring_project_summary"],
            )
        ],
        required_parameters=["summary_id", "content_sha256"],
        optional_parameters={},
        executable=True,
        execution_state="executable",
        implementation_notes=[
            "The digest covers measurements, exclusions, evidence and the saved review state."
        ],
    )


def execute_monitoring_summary(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("A monitoring comparison requires its owning project")
    try:
        pin = SummaryPin.model_validate(
            {
                k: v
                for k, v in parameters.items()
                if k not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
    except SchemaError as exc:
        raise ValidationError(
            "Choose a saved monitoring comparison and its content checksum"
        ) from exc
    result = MonitoringSummaryService(session, settings).get(project_id, str(pin.summary_id))
    if pin.content_sha256 != result.content_sha256:
        raise ConflictError(
            "The pinned monitoring comparison checksum differs from the saved comparison"
        )
    return [{"port_id": "summary", "data_type": NODE, "payload": result.model_dump(mode="json")}]
