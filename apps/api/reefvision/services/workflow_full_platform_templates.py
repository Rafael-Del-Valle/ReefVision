"""Feature-complete CoralVision 1.0 workflow templates.

These templates exercise the advanced runtime paths added after the original Phase 10
planner: probability-only Active Learning and depth-aware coral measurements.
"""

from __future__ import annotations

from reefvision.schemas.workflows import (
    WorkflowEdge,
    WorkflowNode,
    WorkflowTemplate,
    WorkflowValidationRequest,
)


def classification_uncertainty_review_template() -> WorkflowTemplate:
    """Detect regions, classify them, and rank images for human review by entropy."""

    return WorkflowTemplate(
        template_id="classification-uncertainty-review",
        name="Classification uncertainty review",
        description=(
            "Detect regions, classify reviewable crops, then rank the source images by "
            "prediction entropy without requiring a separate embedding model."
        ),
        workflow=WorkflowValidationRequest(
            name="Classification uncertainty review",
            nodes=[
                WorkflowNode(id="images", node_type="image_input"),
                WorkflowNode(
                    id="detect",
                    node_type="detector",
                    configuration={"model_id": "<select-detector>"},
                ),
                WorkflowNode(
                    id="classify",
                    node_type="classifier",
                    configuration={"model_id": "<select-classifier>"},
                ),
                WorkflowNode(
                    id="review",
                    node_type="active_learning",
                    configuration={
                        "strategy": "entropy",
                        "maximum_items": 100,
                    },
                ),
                WorkflowNode(
                    id="export",
                    node_type="export",
                    configuration={"format": "json"},
                ),
            ],
            edges=[
                WorkflowEdge(
                    source_node_id="images",
                    source_port="images",
                    target_node_id="detect",
                    target_port="images",
                ),
                WorkflowEdge(
                    source_node_id="images",
                    source_port="images",
                    target_node_id="classify",
                    target_port="images",
                ),
                WorkflowEdge(
                    source_node_id="detect",
                    source_port="detections",
                    target_node_id="classify",
                    target_port="regions",
                ),
                WorkflowEdge(
                    source_node_id="classify",
                    source_port="classifications",
                    target_node_id="review",
                    target_port="predictions",
                ),
                WorkflowEdge(
                    source_node_id="review",
                    source_port="review_batch",
                    target_node_id="export",
                    target_port="artifact",
                ),
            ],
        ),
    )


def depth_aware_coral_measurement_template() -> WorkflowTemplate:
    """Segment coral and combine masks with aligned depth maps before export."""

    return WorkflowTemplate(
        template_id="depth-aware-coral-measurement",
        name="Depth-aware coral measurement",
        description=(
            "Generate an aligned depth map, segment coral, calculate calibrated 2D and "
            "depth-aware measurements, and export the resulting scientific artifact."
        ),
        workflow=WorkflowValidationRequest(
            name="Depth-aware coral measurement",
            nodes=[
                WorkflowNode(id="images", node_type="image_input"),
                WorkflowNode(
                    id="depth",
                    node_type="depth_estimation",
                    configuration={
                        "provider_id": "depth_anything_v2_relative",
                        "model_id": "depth-anything/Depth-Anything-V2-Small-hf",
                        "depth_kind": "relative",
                        "local_files_only": True,
                    },
                ),
                WorkflowNode(
                    id="segment",
                    node_type="segmenter",
                    configuration={"model_id": "<select-segmenter>"},
                ),
                WorkflowNode(id="measure", node_type="measurement"),
                WorkflowNode(
                    id="export",
                    node_type="export",
                    configuration={"format": "json"},
                ),
            ],
            edges=[
                WorkflowEdge(
                    source_node_id="images",
                    source_port="images",
                    target_node_id="depth",
                    target_port="images",
                ),
                WorkflowEdge(
                    source_node_id="images",
                    source_port="images",
                    target_node_id="segment",
                    target_port="images",
                ),
                WorkflowEdge(
                    source_node_id="segment",
                    source_port="masks",
                    target_node_id="measure",
                    target_port="masks",
                ),
                WorkflowEdge(
                    source_node_id="depth",
                    source_port="depth_maps",
                    target_node_id="measure",
                    target_port="depth_maps",
                ),
                WorkflowEdge(
                    source_node_id="measure",
                    source_port="measurements",
                    target_node_id="export",
                    target_port="artifact",
                ),
            ],
        ),
    )


def full_platform_templates() -> list[WorkflowTemplate]:
    return [
        classification_uncertainty_review_template(),
        depth_aware_coral_measurement_template(),
    ]
