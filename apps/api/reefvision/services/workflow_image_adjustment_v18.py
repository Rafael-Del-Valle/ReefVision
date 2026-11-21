"""Replay one immutable raw-grid rendition as a typed model input."""

from typing import Any, Final
from uuid import UUID

from pydantic import ValidationError as SchemaValidationError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ModelRegistration, WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.image_adjustments_v18 import ImageAdjustmentPin
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.image_adjustments_v18 import (
    ImageAdjustmentService,
    adjusted_inference_binding,
)

NODE = "underwater_adjustment"
ARTIFACT: Final = "adjusted_image_reference"


class AdjustmentNodePin(ImageAdjustmentPin):
    image_id: UUID


def add_underwater_adjustment(registry: dict[str, WorkflowNodeDefinitionResponse]) -> None:
    registry[NODE] = WorkflowNodeDefinitionResponse(
        node_type=NODE,
        display_name="Underwater image adjustment",
        category="sources",
        description="Replay a saved photometric recipe on one hash-pinned still image.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project",
                display_name="Project",
                accepted_types=["project_reference"],
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="images",
                display_name="Adjusted image",
                accepted_types=[ARTIFACT],
                required=False,
                multiple=True,
            )
        ],
        required_parameters=[
            "image_id",
            "recipe_id",
            "content_sha256",
            "original_sha256",
            "rendition_sha256",
        ],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "The saved recipe preserves the original axis order and pixel dimensions.",
            "Connect Adjusted image to detection or segmentation to use the rendition as input.",
        ],
    )
    for node_type in ("detection_inference", "segmentation_inference"):
        node = registry[node_type].model_copy(deep=True)
        for port in node.input_ports:
            if port.port_id == "images":
                port.accepted_types.append(ARTIFACT)
        registry[node_type] = node


def execute_underwater_adjustment(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if (
        len(projects) != 1
        or projects[0].data_type != "project_reference"
        or projects[0].payload_json.get("project_id") != project_id
    ):
        raise ValidationError("Underwater adjustment requires the current project reference")
    try:
        config = AdjustmentNodePin.model_validate(
            {
                key: value
                for key, value in parameters.items()
                if key not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
    except SchemaValidationError as exc:
        raise ValidationError(
            "Choose an adjustment with a valid original, recipe and rendition pin"
        ) from exc
    pin = ImageAdjustmentPin.model_validate(config.model_dump(exclude={"image_id"}))
    _, record = ImageAdjustmentService(session, settings).verified_input(
        project_id, str(config.image_id), pin
    )
    return [
        {
            "port_id": "images",
            "data_type": ARTIFACT,
            "payload": {
                "project_id": project_id,
                "image_ids": [str(config.image_id)],
                "image_adjustment": pin.model_dump(mode="json"),
                "receipt": record.receipt.model_dump(mode="json"),
            },
        }
    ]


def adjusted_workflow_binding(
    session: Session,
    settings: Settings,
    project_id: str,
    image_ids: list[str],
    artifact: WorkflowArtifact,
    model: ModelRegistration,
) -> dict[str, Any]:
    if artifact.data_type != ARTIFACT:
        return {}
    try:
        pin = ImageAdjustmentPin.model_validate(artifact.payload_json.get("image_adjustment"))
    except SchemaValidationError as exc:
        raise ValidationError(
            "The selected adjusted image artifact lacks a valid input pin"
        ) from exc
    return adjusted_inference_binding(session, settings, project_id, image_ids, pin, model)
