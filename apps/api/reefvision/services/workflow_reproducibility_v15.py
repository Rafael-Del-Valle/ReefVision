"""Replay the same portable proof produced by the offline research package."""

from typing import Any

from pydantic import ValidationError as SchemaError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.workflow_execution import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.domain.reproducibility_v15 import ARTIFACT_TYPE, NODE_TYPE
from reefvision.schemas.reproducibility_v15 import ReproducibilityPin
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.reproducibility_lineage_v15 import project_proofs


def reproducibility_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type=NODE_TYPE,
        display_name="Research reproducibility package",
        category="Scientific analysis",
        description="Replay exact frozen study, review, and model comparison proof.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project",
                display_name="Project",
                accepted_types=["project_reference"],
            ),
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="proof",
                display_name="Reproducibility proof",
                accepted_types=[ARTIFACT_TYPE],
            ),
        ],
        required_parameters=["proof_sha256"],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Reopens the verified portable proof even when original weights were omitted."
        ],
    )


def execute_reproducibility(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Research proof requires its owning project reference")
    try:
        pin = ReproducibilityPin.model_validate(
            {key: value for key, value in parameters.items() if not key.startswith("__workflow_")},
        )
    except SchemaError as exc:
        raise ValidationError("Select a verified reproducibility proof in the project") from exc
    proof = next(
        (
            proof
            for proof in project_proofs(session, project_id)
            if proof.proof_sha256 == pin.proof_sha256
        ),
        None,
    )
    if proof is None:
        raise ValidationError("The pinned reproducibility proof is not present in this project")
    return [
        {"port_id": "proof", "data_type": ARTIFACT_TYPE, "payload": proof.model_dump(mode="json")}
    ]
