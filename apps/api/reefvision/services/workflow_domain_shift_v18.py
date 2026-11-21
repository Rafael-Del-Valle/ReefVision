"""Replay a frozen domain shift analysis with its declared roster."""

from typing import Any

from pydantic import ValidationError as SchemaError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.paired_models_v15 import ComparisonChoice
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.domain_shift_v18 import read_report

NODE = "domain_shift_report"


def domain_shift_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type=NODE,
        display_name="Saved domain shift report",
        category="Data and evidence",
        description="Replay a frozen domain comparison and its acquisition-group declaration.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="report",
                display_name="Domain shift report",
                accepted_types=["domain_shift_report"],
                required=False,
                multiple=True,
            )
        ],
        required_parameters=["report_id", "content_sha256"],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Replay verifies the saved report and comparison digest without reloading a model."
        ],
    )


def execute_domain_shift(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    references = inputs.get("project", [])
    if len(references) != 1 or references[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Domain shift replay requires the current project reference")
    try:
        pin = ComparisonChoice.model_validate(
            {"id": parameters.get("report_id"), "sha256": parameters.get("content_sha256")}
        )
    except SchemaError as exc:
        raise ValidationError("Choose a saved domain shift report UUID and digest") from exc
    return [
        {
            "port_id": "report",
            "data_type": NODE,
            "payload": read_report(session, project_id, str(pin.id), pin.sha256),
        }
    ]
