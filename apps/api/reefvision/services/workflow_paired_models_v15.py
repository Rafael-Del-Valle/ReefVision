"""Replay a paired model comparison through the same project scoring services."""

from typing import Any

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact, WorkflowRun
from reefvision.domain.errors import ValidationError
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.paired_models_v15 import replay


def paired_models_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="paired_model_comparison",
        display_name="Paired model comparison",
        category="Scientific analysis",
        description="Recompute per-group detector, mask, pose, tracking or event scoring.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="report",
                display_name="Paired model comparison",
                accepted_types=["paired_model_report"],
            )
        ],
        required_parameters=["comparison_id", "comparison_sha256"],
        optional_parameters={},
        executable=True,
        execution_state="executable",
        implementation_notes=["Pins both model receipts and the independent reference."],
    )


def execute_paired_models(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Paired comparison requires its owning project")
    owner = session.get(WorkflowRun, str(parameters.get("__workflow_run_id", "")))
    if owner is None or owner.project_id != project_id or not owner.job_id:
        raise ValidationError("Paired comparison requires an active project workflow run")
    report = replay(
        session,
        settings,
        project_id,
        str(parameters.get("comparison_id", "")),
        str(parameters.get("comparison_sha256", "")),
        owner_run_id=owner.job_id,
    )
    return [{"port_id": "report", "data_type": "paired_model_report", "payload": report}]
