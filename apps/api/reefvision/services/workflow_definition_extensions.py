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

    # The unified scientific measurement node supports coral masks plus optional aligned
    # depth maps, and calibrated video-track 3D analysis. Individual runtime modes enforce
    # their own required inputs so the graph can expose one stable measurement primitive
    # instead of creating a second executor-specific node family.
    measurement = workflow_service.NODE_DEFINITIONS.get("measurement")
    if measurement is not None:
        measurement_inputs = dict(measurement.inputs)
        if "masks" in measurement_inputs:
            mask_type, _required = measurement_inputs["masks"]
            measurement_inputs["masks"] = (mask_type, False)
        measurement_inputs.setdefault("depth_maps", ("depth_maps", False))
        measurement_inputs.setdefault("video", ("video", False))
        measurement_inputs.setdefault("tracks", ("tracks", False))
        workflow_service.NODE_DEFINITIONS["measurement"] = workflow_service._NodeDefinition(
            display_name="Scientific measurement",
            inputs=measurement_inputs,
            outputs=dict(measurement.outputs),
            model_tasks=measurement.model_tasks,
        )

    # Active learning needs both model uncertainty and representation-space diversity.
    # Predictions remain required; embeddings are optional so pure uncertainty strategies
    # still work, while k-center/clustering/Pareto strategies can consume an embedding node
    # directly without copying embedding IDs into JSON configuration.
    active_learning = workflow_service.NODE_DEFINITIONS.get("active_learning")
    if active_learning is not None and "embeddings" not in active_learning.inputs:
        workflow_service.NODE_DEFINITIONS["active_learning"] = workflow_service._NodeDefinition(
            display_name=active_learning.display_name,
            inputs={**active_learning.inputs, "embeddings": ("embeddings", False)},
            outputs=dict(active_learning.outputs),
            model_tasks=active_learning.model_tasks,
        )

    workflow_service.COMPATIBLE_SOURCE_TYPES.setdefault("artifact", set()).update(
        {"depth_maps", "embeddings", "artifact"}
    )


install_workflow_definition_extensions()