"""Replay a pinned condition report through the saved Workflow Builder."""

from __future__ import annotations

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
from reefvision.services.spatial_condition_v14 import SpatialConditionService

NODE_TYPE = "spatial_condition_report"


class ConditionReportParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    revision_id: UUID


def extend_condition_registry(
    base: Callable[[], dict[str, WorkflowNodeDefinitionResponse]],
) -> Callable[[], dict[str, WorkflowNodeDefinitionResponse]]:
    def registry() -> dict[str, WorkflowNodeDefinitionResponse]:
        nodes = dict(base())
        nodes[NODE_TYPE] = WorkflowNodeDefinitionResponse(
            node_type=NODE_TYPE,
            display_name="3D Condition Review Report",
            category="Scientific analysis",
            description="Replay a saved condition observation and its attributed local decisions.",
            input_ports=[
                WorkflowPortDefinition(
                    port_id="project", display_name="Project", accepted_types=["project_reference"]
                )
            ],
            output_ports=[
                WorkflowPortDefinition(
                    port_id="report",
                    display_name="Condition report",
                    accepted_types=[NODE_TYPE],
                    required=False,
                    multiple=True,
                )
            ],
            required_parameters=["asset_id", "revision_id"],
            optional_parameters={},
            execution_state="executable_analysis",
            executable=True,
            implementation_notes=[
                "Use the source asset and condition revision IDs shown in Condition review.",
                "Uses the standalone report service and refuses stale asset metadata.",
                "Reports carry local attribution and preserve disagreements and uncertainty.",
            ],
        )
        return nodes

    return registry


def execute_condition_report(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or (projects[0].payload_json or {}).get("project_id") != project_id:
        raise ValidationError("Condition report requires the current project reference")
    try:
        scope = ConditionReportParameters.model_validate(
            {
                key: value
                for key, value in parameters.items()
                if key not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
        report = SpatialConditionService(session, settings).report(
            project_id, str(scope.asset_id), str(scope.revision_id), require_current=True
        )
    except (PydanticValidationError, ConflictError, NotFoundError) as exc:
        raise ValidationError(f"Condition replay failed: {exc}") from exc
    return [
        {"port_id": "report", "data_type": NODE_TYPE, "payload": report.model_dump(mode="json")}
    ]


def register_condition_adapter() -> None:
    workflow_runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.add(NODE_TYPE)
    workflow_runtime_adapters._ADAPTERS[NODE_TYPE] = execute_condition_report
