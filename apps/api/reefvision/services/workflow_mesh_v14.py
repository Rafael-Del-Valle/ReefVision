"""1.4 mesh preview integration with the existing saved Workflow Builder."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services import workflow_runtime_adapters as runtime_adapters
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request

NODE_TYPE = "mesh_surface_preview"


def extend_mesh_registry(
    base: Callable[[], dict[str, WorkflowNodeDefinitionResponse]],
) -> Callable[[], dict[str, WorkflowNodeDefinitionResponse]]:
    def registry() -> dict[str, WorkflowNodeDefinitionResponse]:
        nodes = dict(base())
        nodes[NODE_TYPE] = WorkflowNodeDefinitionResponse(
            node_type=NODE_TYPE,
            display_name="3D Mesh Surface Preview",
            category="Scientific analysis",
            description=(
                "Measure caller-supplied 3D triangles with unverified scale evidence."
            ),
            input_ports=[
                WorkflowPortDefinition(
                    port_id="project",
                    display_name="Project",
                    accepted_types=["project_reference"],
                )
            ],
            output_ports=[
                WorkflowPortDefinition(
                    port_id="measurement",
                    display_name="Unverified mesh measurement",
                    accepted_types=["mesh_measurement_preview"],
                    required=False,
                    multiple=True,
                )
            ],
            required_parameters=[
                "meters_per_unit",
                "calibration_method",
                "calibration_evidence",
            ],
            optional_parameters={
                "obj_text": None,
                "vertices": None,
                "faces": None,
                "relative_scale_uncertainty": None,
                "source_label": None,
            },
            execution_state="executable_analysis",
            executable=True,
            implementation_notes=[
                "Uses the same bounded preview engine as the standalone API.",
                "Geometry and calibration remain caller_supplied_unverified.",
                "This is not a persistent 3D asset importer or full mesh viewer.",
            ],
        )
        return nodes

    return registry


def execute_mesh_preview(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del session, settings
    artifacts = inputs.get("project", [])
    if (
        len(artifacts) != 1
        or (artifacts[0].payload_json or {}).get("project_id") != project_id
    ):
        raise ValidationError("Mesh preview requires the current project reference")
    try:
        request = MeshPreviewRequest.model_validate(parameters)
        result = preview_from_request(request)
    except (PydanticValidationError, ValueError) as exc:
        raise ValidationError(f"Invalid mesh preview: {exc}") from exc
    result["project_id"] = project_id
    return [
        {
            "port_id": "measurement",
            "data_type": "mesh_measurement_preview",
            "payload": result,
        }
    ]


def register_mesh_adapter() -> None:
    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.add(NODE_TYPE)
    runtime_adapters._ADAPTERS[NODE_TYPE] = execute_mesh_preview
