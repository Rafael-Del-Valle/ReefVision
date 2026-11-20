"""Install ReefVision 1.0 workflow extensions without forking the M10 engine."""

from __future__ import annotations

from reefvision.services import workflow_graphs
from reefvision.services.workflow_condition_v14 import (
    extend_condition_registry,
    register_condition_adapter,
)
from reefvision.services.workflow_graphs import install_workflow_node_registry
from reefvision.services.workflow_mesh_v14 import extend_mesh_registry, register_mesh_adapter
from reefvision.services.workflow_model_runtime_v15 import (
    extend_model_runtime_registry,
    register_model_runtime_adapter,
)
from reefvision.services.workflow_node_registry_v1 import workflow_node_registry
from reefvision.services.workflow_provider_manifests_v15 import (
    extend_provider_manifest_registry,
    register_provider_manifest_adapter,
)
from reefvision.services.workflow_reviewer_lab_v15 import (
    NODE_TYPE as REVIEWER_LAB_NODE_TYPE,
)
from reefvision.services.workflow_reviewer_lab_v15 import (
    extend_reviewer_lab_registry,
    register_reviewer_lab_adapter,
)


def install_workflow_v1_extensions() -> None:
    """Make the extended registry visible to the existing validator/planner service."""

    register_mesh_adapter()
    register_condition_adapter()
    register_provider_manifest_adapter()
    register_model_runtime_adapter()
    register_reviewer_lab_adapter()
    registry = extend_condition_registry(extend_mesh_registry(workflow_node_registry))
    registry = extend_model_runtime_registry(extend_provider_manifest_registry(registry))
    install_workflow_node_registry(extend_reviewer_lab_registry(registry))
    workflow_graphs._ACTIONS["reviewed_model_runtime"] = (
        "Verify and use a reviewed local model configuration."
    )
    workflow_graphs._ACTIONS[REVIEWER_LAB_NODE_TYPE] = (
        "Replay an immutable local reviewer agreement report."
    )
    workflow_graphs._ACTIONS["spatial_condition_report"] = (
        "Replay a pinned biological condition review report."
    )
    workflow_graphs._ACTIONS["mesh_surface_preview"] = (
        "Calculate an unverified, bounded 3D triangle surface preview."
    )
    workflow_graphs._ACTIONS["point_cloud_preview"] = (
        "Calculate unverified calibrated XYZ point-cloud extents."
    )
    workflow_graphs._ACTIONS["mesh_longitudinal_comparison"] = (
        "Compare two unverified 3D mesh observations with scale-only uncertainty bounds."
    )
    workflow_graphs._ACTIONS["provider_manifest_snapshot"] = (
        "Snapshot one inspect-only local provider manifest without loading provider code."
    )
