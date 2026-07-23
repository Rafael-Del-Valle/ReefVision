"""Register workflow nodes whose execution handlers already exist."""

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
    workflow_service.COMPATIBLE_SOURCE_TYPES.setdefault("artifact", set()).update(
        {"depth_maps", "embeddings", "artifact"}
    )


install_workflow_definition_extensions()
