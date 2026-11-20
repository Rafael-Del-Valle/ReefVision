"""Replay a sealed reviewer agreement report from the standalone service."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services import workflow_runtime_adapters
from reefvision.services.reviewer_lab_v15 import ReviewerLabService

NODE_TYPE = "reviewer_lab_agreement_report"


class ReportParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: UUID


def extend_reviewer_lab_registry(
    base: Callable[[], dict[str, WorkflowNodeDefinitionResponse]],
) -> Callable[[], dict[str, WorkflowNodeDefinitionResponse]]:
    def registry() -> dict[str, WorkflowNodeDefinitionResponse]:
        nodes = dict(base())
        nodes[NODE_TYPE] = WorkflowNodeDefinitionResponse(
            node_type=NODE_TYPE,
            display_name="Reviewer Lab Agreement Report",
            category="Scientific analysis",
            description="Replay a sealed report from an independent local review round.",
            input_ports=[
                WorkflowPortDefinition(
                    port_id="project",
                    display_name="Project",
                    accepted_types=["project_reference"],
                )
            ],
            output_ports=[
                WorkflowPortDefinition(
                    port_id="report",
                    display_name="Agreement report",
                    accepted_types=[NODE_TYPE],
                    required=False,
                    multiple=True,
                )
            ],
            required_parameters=["report_id"],
            optional_parameters={},
            execution_state="executable_analysis",
            executable=True,
            implementation_notes=[
                "Choose the sealed agreement report ID from Reviewer lab.",
                "Replays the original independent decisions, denominators, and role revisions.",
            ],
        )
        return nodes

    return registry


def execute_report(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or (projects[0].payload_json or {}).get("project_id") != project_id:
        raise ValidationError("Reviewer Lab agreement requires the current project reference")
    try:
        scope = ReportParameters.model_validate(
            {
                key: value
                for key, value in parameters.items()
                if key not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
        report = ReviewerLabService(session, project_id).report(str(scope.report_id))
    except (PydanticValidationError, ConflictError, NotFoundError) as exc:
        raise ValidationError(f"Reviewer Lab replay failed: {exc}") from exc
    return [
        {"port_id": "report", "data_type": NODE_TYPE, "payload": report.model_dump(mode="json")}
    ]


def register_reviewer_lab_adapter() -> None:
    workflow_runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.add(NODE_TYPE)
    workflow_runtime_adapters._ADAPTERS[NODE_TYPE] = execute_report
