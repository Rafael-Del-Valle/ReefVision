"""Unified segmentation workflow presets for CoralVision 1.0."""

from __future__ import annotations

from reefvision.schemas.workflows import (
    WorkflowEdge,
    WorkflowNode,
    WorkflowTemplate,
    WorkflowValidationRequest,
)


def detector_guided_prompt_assist_template() -> WorkflowTemplate:
    """Convert detector boxes into reviewable SAM-family mask proposals."""

    return WorkflowTemplate(
        template_id="detector-guided-prompt-assist-segmentation",
        name="Detector-guided Prompt Assist segmentation",
        description=(
            "Detect candidate objects, use each detection box to prompt a registered SAM, "
            "SAM 2, MobileSAM, FastSAM, or compatible assist model, and export pending mask "
            "proposals for explicit human review before they can become annotations."
        ),
        workflow=WorkflowValidationRequest(
            name="Detector-guided Prompt Assist segmentation",
            nodes=[
                WorkflowNode(id="images", node_type="image_input"),
                WorkflowNode(
                    id="detect",
                    node_type="detector",
                    configuration={"model_id": "<select-detector>"},
                ),
                WorkflowNode(
                    id="assist",
                    node_type="segmenter",
                    configuration={
                        "model_id": "<select-assist-segmenter>",
                        "device": "auto",
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
                    target_node_id="assist",
                    target_port="images",
                ),
                WorkflowEdge(
                    source_node_id="detect",
                    source_port="detections",
                    target_node_id="assist",
                    target_port="prompts",
                ),
                WorkflowEdge(
                    source_node_id="assist",
                    source_port="masks",
                    target_node_id="export",
                    target_port="artifact",
                ),
            ],
        ),
    )


def unified_segmentation_templates() -> list[WorkflowTemplate]:
    return [detector_guided_prompt_assist_template()]
