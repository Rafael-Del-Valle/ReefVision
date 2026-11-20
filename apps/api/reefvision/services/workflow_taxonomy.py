"""Reopen a single immutable detectability receipt through the typed workflow worker."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError as SchemaError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.workflow_execution import WorkflowArtifact
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.taxonomy import Digest, TaxonomyModel
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.taxonomy import TaxonomyService

NODE = "detectability_assessment"


class DetectabilityPin(TaxonomyModel):
    assessment_id: UUID
    assessment_sha256: Digest


def detectability_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type=NODE,
        display_name="Read detectability assessment",
        category="Scientific analysis",
        description="Reopen a frozen known-presence survey estimate or withholding report.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="assessment", display_name="Detectability assessment", accepted_types=[NODE]
            )
        ],
        required_parameters=["assessment_id", "assessment_sha256"],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "The checksum pins the grouped result, exclusions, source hashes and local decisions.",
            "Replay reads the saved assessment even when the live survey has later decisions.",
        ],
    )


def execute_detectability(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Detectability replay requires the assessment's owning project")
    try:
        pin = DetectabilityPin.model_validate(
            {
                k: v
                for k, v in parameters.items()
                if k not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
    except SchemaError as exc:
        raise ValidationError("Choose a saved detectability assessment and its checksum") from exc
    record = TaxonomyService(session, settings, project_id).get_assessment(str(pin.assessment_id))
    if record.result_sha256 != pin.assessment_sha256:
        raise ConflictError("The saved detectability assessment checksum changed")
    return [{"port_id": "assessment", "data_type": NODE, "payload": record.model_dump(mode="json")}]
