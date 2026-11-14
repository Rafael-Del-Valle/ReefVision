"""Publish a saved scientific comparison to a typed workflow report."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.scientific_comparison import ComparisonRecord
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.scientific_comparison import read_comparison


def comparison_artifact(record: ComparisonRecord) -> dict[str, str]:
    return {
        "project_id": str(record.project_id),
        "comparison_id": str(record.id),
        "content_sha256": record.content_sha256,
        "method": record.snapshot.method,
        "data_kind": record.snapshot.data_kind,
        "export_path": f"/projects/{record.project_id}/scientific-comparisons/{record.id}/export",
    }


def execute(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings
    if set(parameters) - {"comparison_id", "__workflow_run_id", "__workflow_node_run_id"}:
        raise ValidationError("Unsupported scientific comparison parameters")
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Scientific comparison requires the current project")
    try:
        identifier = str(UUID(str(parameters.get("comparison_id"))))
    except ValueError as exc:
        raise ValidationError("A saved comparison UUID is required") from exc
    report = read_comparison(session, project_id, identifier)
    if report.stale:
        raise ConflictError("Source validation evidence changed; save a fresh comparison")
    return [
        {
            "port_id": "report",
            "data_type": "scientific_comparison_report",
            "payload": comparison_artifact(report),
        }
    ]


def register_scientific_comparison_nodes() -> dict[str, WorkflowNodeDefinitionResponse]:
    from reefvision.services import workflow_runtime_adapters as runtime

    node_type = "scientific_comparison"
    runtime.RUNTIME_ADAPTER_NODE_TYPES.add(node_type)
    runtime._ADAPTERS[node_type] = execute
    return {
        node_type: WorkflowNodeDefinitionResponse(
            node_type=node_type,
            display_name="Publish Scientific Comparison",
            category="Scientific analysis",
            description="Use a saved model comparison on frozen ReefPose held-out evidence.",
            input_ports=[
                WorkflowPortDefinition(
                    port_id="project", display_name="Project", accepted_types=["project_reference"]
                )
            ],
            output_ports=[
                WorkflowPortDefinition(
                    port_id="report",
                    display_name="Scientific comparison",
                    accepted_types=["scientific_comparison_report"],
                )
            ],
            required_parameters=["comparison_id"],
            optional_parameters={},
            execution_state="executable",
            executable=True,
            implementation_notes=[
                "Create the comparison in ReefPose Scientific Validation first.",
                "Reuses the same immutable analysis and checks source evidence on replay.",
            ],
        )
    }
