"""Install ReefVision 1.0 workflow extensions without forking the M10 engine."""

from __future__ import annotations

from reefvision.services import workflow_graphs
from reefvision.services.workflow_graphs import install_workflow_node_registry
from reefvision.services.workflow_mesh_v14 import extend_mesh_registry, register_mesh_adapter
from reefvision.services.workflow_node_registry_v1 import workflow_node_registry


def install_workflow_v1_extensions() -> None:
    """Make the extended registry visible to the existing validator/planner service."""

    register_mesh_adapter()
    install_workflow_node_registry(extend_mesh_registry(workflow_node_registry))
    workflow_graphs._ACTIONS["mesh_surface_preview"] = (
        "Calculate an unverified, bounded 3D triangle surface preview."
    )
    workflow_graphs._ACTIONS["point_cloud_preview"] = (
        "Calculate unverified calibrated XYZ point-cloud extents."
    )
    workflow_graphs._ACTIONS["mesh_longitudinal_comparison"] = (
        "Compare two unverified 3D mesh observations with scale-only uncertainty bounds."
    )
