"""Workflow template for 2-of-3 segmentation auto-labeling."""

from __future__ import annotations

from reefvision.schemas.workflows import (
    WorkflowEdge,
    WorkflowNode,
    WorkflowTemplate,
    WorkflowValidationRequest,
)


def multi_model_auto_labeling_template() -> WorkflowTemplate:
    return WorkflowTemplate(
        template_id="multi-model-segmentation-auto-labeling",
        name="SAM 3 + Gemini + GPT auto-labeling",
        description=(
            "Run a registered SAM 3-compatible primary segmenter, ask Gemini and GPT "
            "to review every candidate mask, and promote only masks receiving at least "
            "two accepted votes. Remote image review is opt-in and fully provenance-tracked."
        ),
        workflow=WorkflowValidationRequest(
            name="SAM 3 + Gemini + GPT auto-labeling",
            nodes=[
                WorkflowNode(id="images", node_type="image_input"),
                WorkflowNode(
                    id="segment-and-vote",
                    node_type="segmenter",
                    label="Segment and require 2-of-3 consensus",
                    configuration={
                        "model_id": "<select-sam3-segmenter>",
                        "confidence": 0.25,
                        "iou_threshold": 0.45,
                        "multi_model_consensus": {
                            "enabled": True,
                            "required_primary_provider": "sam3_sidecar",
                            "prompt": "octocoral colony or fragment",
                            "required_votes": 2,
                            "sam_vote_threshold": 0.35,
                            "minimum_reviewer_confidence": 0.60,
                            "gemini_model": "gemini-2.5-flash",
                            "openai_model": "gpt-5-mini",
                            "crop_padding_fraction": 0.10,
                            "allow_remote_review": False,
                            "auto_accept": True,
                            "fail_closed": True,
                        },
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
                    target_node_id="segment-and-vote",
                    target_port="images",
                ),
                WorkflowEdge(
                    source_node_id="segment-and-vote",
                    source_port="masks",
                    target_node_id="export",
                    target_port="artifact",
                ),
            ],
        ),
    )
