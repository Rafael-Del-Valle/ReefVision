from typing import Any
from uuid import UUID

from pydantic import ValidationError as InvalidParameter
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.multispectral import Digest, SpectralModel
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.multispectral import MultispectralService

NODE = "multispectral_index"


class IndexPin(SpectralModel):
    index_id: UUID
    content_sha256: Digest


def multispectral_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type=NODE,
        display_name="Recompute calibrated spectral index",
        category="Scientific analysis",
        description="Verify original bands and repeat a saved two-band reflectance calculation.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="index", display_name="Spectral index", accepted_types=[NODE]
            )
        ],
        required_parameters=["index_id", "content_sha256"],
        optional_parameters={},
        executable=True,
        execution_state="executable",
        implementation_notes=[
            "Uncalibrated or unaligned comparisons retain their withheld result."
        ],
    )


def execute_multispectral(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Recompute a spectral index from its owning project")
    try:
        pin = IndexPin.model_validate(
            {
                k: v
                for k, v in parameters.items()
                if k not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
    except InvalidParameter as exc:
        raise ValidationError("Choose a saved spectral index and its checksum") from exc
    saved, _ = MultispectralService(session, settings).replay(
        project_id, str(pin.index_id), pin.content_sha256
    )
    return [{"port_id": "index", "data_type": NODE, "payload": saved.model_dump(mode="json")}]
