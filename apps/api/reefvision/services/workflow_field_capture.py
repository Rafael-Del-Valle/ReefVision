"""Replay the same exact field reconciliation through Workflow Builder."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError as SchemaValidationError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.workflow_execution import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.field_capture import FieldCaptureReconcileRequest
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.field_capture_reconciliation import FieldCaptureReconciliationService


class FieldReconciliationParameters(FieldCaptureReconcileRequest):
    batch_id: UUID


def field_capture_reconcile_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="field_capture_reconcile",
        display_name="Reconcile field batch",
        category="Data and evidence",
        description="Import preserved originals and report duplicate or conflicting observations.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="reconciliation",
                display_name="Field reconciliation",
                accepted_types=["field_capture_reconciliation"],
            )
        ],
        required_parameters=["batch_id", "manifest_sha256"],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "The graph pins the batch and sealed source checksum.",
            "A replay verifies original and imported bytes before returning its saved receipt.",
            "Conflicting field observations remain available for attributed review.",
        ],
    )


def execute_field_capture_reconcile(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Field reconciliation requires the current project reference")
    try:
        pins = FieldReconciliationParameters.model_validate(
            {
                key: value
                for key, value in parameters.items()
                if key not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
    except SchemaValidationError as exc:
        raise ValidationError(
            "Field reconciliation requires a sealed batch UUID and checksum"
        ) from exc
    report = FieldCaptureReconciliationService(session, settings).reconcile(
        project_id,
        str(pins.batch_id),
        pins.manifest_sha256,
    )
    return [
        {
            "port_id": "reconciliation",
            "data_type": "field_capture_reconciliation",
            "payload": report.model_dump(mode="json"),
        }
    ]
