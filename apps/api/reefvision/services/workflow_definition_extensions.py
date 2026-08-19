"""Register workflow nodes and ports whose execution handlers already exist."""

from __future__ import annotations

from reefvision.services import workflows as workflow_service


def install_workflow_definition_extensions() -> None:
    """Keep validation, the graph editor, and worker dispatch in sync."""

    workflow_service.NODE_DEFINITIONS.setdefault(
        "depth_estimation",
        workflow_service._NodeDefinition(
            display_name="Depth estimation",
            inputs={"images": ("images", True)},
            outputs={"depth_maps": "depth_maps"},
        ),
    )
    workflow_service.NODE_DEFINITIONS.setdefault(
        "embedding_generation",
        workflow_service._NodeDefinition(
            display_name="Image embedding generation",
            inputs={"images": ("images", True)},
            outputs={"embeddings": "embeddings"},
        ),
    )
    workflow_service.NODE_DEFINITIONS.setdefault(
        "filter",
        workflow_service._NodeDefinition(
            display_name="Artifact filter",
            inputs={"artifact": ("artifact", True)},
            outputs={"artifact": "artifact"},
        ),
    )

    # Full 1.0 measurements can combine a segmentation mask with an aligned depth map.
    # Preserve the existing required mask and optional detection ports while adding a
    # typed optional RGB-D input that can come directly from depth_estimation.
    measurement = workflow_service.NODE_DEFINITIONS.get("measurement")
    if measurement is not None and "depth_maps" not in measurement.inputs:
        workflow_service.NODE_DEFINITIONS["measurement"] = workflow_service._NodeDefinition(
            display_name=measurement.display_name,
            inputs={**measurement.inputs, "depth_maps": ("depth_maps", False)},
            outputs=dict(measurement.outputs),
            model_tasks=measurement.model_tasks,
        )

    workflow_service.COMPATIBLE_SOURCE_TYPES.setdefault("artifact", set()).update(
        {"depth_maps", "embeddings", "artifact"}
    )


install_workflow_definition_extensions()
