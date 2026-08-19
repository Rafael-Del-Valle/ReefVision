"""Register full-platform workflow ports and mode-aware validation rules."""

from __future__ import annotations

from reefvision.schemas.workflows import (
    WorkflowValidationIssue,
    WorkflowValidationRequest,
    WorkflowValidationResponse,
)
from reefvision.services import workflows as workflow_service

_ORIGINAL_VALIDATE = workflow_service.WorkflowService.validate


def _issue_sort_key(issue: WorkflowValidationIssue) -> tuple[int, str, int, str]:
    return (
        0 if issue.severity == "error" else 1,
        issue.node_id or "",
        issue.edge_index if issue.edge_index is not None else -1,
        issue.code,
    )


def _mode_aware_validate(
    self: workflow_service.WorkflowService,
    project_id: str,
    request: WorkflowValidationRequest,
) -> WorkflowValidationResponse:
    """Restore mode-specific required inputs hidden by the shared measurement primitive."""

    response = _ORIGINAL_VALIDATE(self, project_id, request)
    issues = list(response.issues)
    connected_ports: dict[str, set[str]] = {node.id: set() for node in request.nodes}
    for edge in request.edges:
        if edge.target_node_id in connected_ports:
            connected_ports[edge.target_node_id].add(edge.target_port)

    for node in request.nodes:
        if node.node_type != "measurement":
            continue
        mode = str(node.configuration.get("measurement_mode", "coral_mask")).strip().casefold()
        ports = connected_ports[node.id]
        if mode == "video_depth_3d":
            required_ports = ("video", "tracks")
        elif mode == "coral_metric_surface":
            required_ports = ("masks", "depth_maps")
        else:
            required_ports = ("masks",)
        for port_name in required_ports:
            if port_name in ports:
                continue
            issues.append(
                WorkflowValidationIssue(
                    severity="error",
                    code="measurement_mode_input_missing",
                    node_id=node.id,
                    message=(
                        f"Scientific measurement mode {mode!r} requires input "
                        f"{port_name!r} to be connected."
                    ),
                )
            )

    return response.model_copy(
        update={
            "valid": not any(issue.severity == "error" for issue in issues),
            "issues": sorted(issues, key=_issue_sort_key),
        }
    )


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
    # depth maps, and calibrated video-track 3D analysis. The generic ports are optional
    # here because required inputs depend on measurement_mode; _mode_aware_validate restores
    # the appropriate hard requirements before a workflow can execute.
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

    if workflow_service.WorkflowService.validate is not _mode_aware_validate:
        setattr(workflow_service.WorkflowService, "validate", _mode_aware_validate)


install_workflow_definition_extensions()
