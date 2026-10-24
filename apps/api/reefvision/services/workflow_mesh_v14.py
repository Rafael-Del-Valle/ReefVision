"""1.4 mesh preview integration with the existing saved Workflow Builder."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.schemas.spatial_point_cloud_v14 import PointCloudPreviewRequest
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services import workflow_runtime_adapters as runtime_adapters
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.services.spatial_point_cloud_v14 import preview_point_cloud_from_request

NODE_TYPE = "mesh_surface_preview"
POINT_NODE_TYPE = "point_cloud_preview"


def extend_mesh_registry(
    base: Callable[[], dict[str, WorkflowNodeDefinitionResponse]],
) -> Callable[[], dict[str, WorkflowNodeDefinitionResponse]]:
    def registry() -> dict[str, WorkflowNodeDefinitionResponse]:
        nodes = dict(base())
        nodes[NODE_TYPE] = WorkflowNodeDefinitionResponse(
            node_type=NODE_TYPE,
            display_name="3D Mesh Surface Preview",
            category="Scientific analysis",
            description=("Measure caller-supplied 3D triangles with unverified scale evidence."),
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
                "ply_text": None,
                "glb_base64": None,
                "vertices": None,
                "faces": None,
                "relative_scale_uncertainty": None,
                "source_label": None,
                "specimen_id": None,
                "observation_id": None,
                "observed_at_utc": None,
                "surface_path_vertex_pairs": None,
            },
            execution_state="executable_analysis",
            executable=True,
            implementation_notes=[
                "Uses the same bounded preview engine as the standalone API.",
                "Geometry and calibration remain caller_supplied_unverified.",
                "This is not a persistent 3D asset importer or full mesh viewer.",
                "Optional edge routes are not biologically verified branch lengths.",
            ],
        )
        nodes[POINT_NODE_TYPE] = WorkflowNodeDefinitionResponse(
            node_type=POINT_NODE_TYPE,
            display_name="3D Point Cloud Preview",
            category="Scientific analysis",
            description="Calibrated point extents without inferred surface or branch length.",
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
                    display_name="Unverified point-cloud measurement",
                    accepted_types=["point_cloud_measurement_preview"],
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
                "ply_text": None,
                "points": None,
                "point_index_pairs": None,
                "preserve_axis_extrema_in_preview": False,
                "relative_scale_uncertainty": None,
                "source_label": None,
                "specimen_id": None,
                "observation_id": None,
                "observed_at_utc": None,
            },
            execution_state="executable_analysis",
            executable=True,
            implementation_notes=[
                "Same bounded point-cloud engine as standalone API.",
                "Calibration and coordinate registration remain unverified.",
                "No surface area or biological branch length is inferred.",
                "Selected point-pair chords are not biological branch lengths.",
                "Not a persistent asset importer or interactive viewer.",
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
    if len(artifacts) != 1 or (artifacts[0].payload_json or {}).get("project_id") != project_id:
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


def execute_point_cloud_preview(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del session, settings
    artifacts = inputs.get("project", [])
    if len(artifacts) != 1 or (artifacts[0].payload_json or {}).get("project_id") != project_id:
        raise ValidationError("Point-cloud preview requires the current project reference")
    try:
        request = PointCloudPreviewRequest.model_validate(parameters)
        result = preview_point_cloud_from_request(request)
    except (PydanticValidationError, ValueError) as exc:
        raise ValidationError(f"Invalid point-cloud preview: {exc}") from exc
    result["project_id"] = project_id
    return [
        {
            "port_id": "measurement",
            "data_type": "point_cloud_measurement_preview",
            "payload": result,
        }
    ]


def register_mesh_adapter() -> None:
    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.add(NODE_TYPE)
    runtime_adapters._ADAPTERS[NODE_TYPE] = execute_mesh_preview
    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.add(POINT_NODE_TYPE)
    runtime_adapters._ADAPTERS[POINT_NODE_TYPE] = execute_point_cloud_preview
