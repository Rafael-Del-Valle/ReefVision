"""Workflow templates for two multi-model segmentation consensus strategies."""

from __future__ import annotations

from reefvision.schemas.workflows import (
    WorkflowEdge,
    WorkflowNode,
    WorkflowTemplate,
    WorkflowValidationRequest,
)


def _workflow(segment_node: WorkflowNode, *, name: str) -> WorkflowValidationRequest:
    return WorkflowValidationRequest(
        name=name,
        nodes=[
            WorkflowNode(id="images", node_type="image_input"),
            segment_node,
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
                target_node_id=segment_node.id,
                target_port="images",
            ),
            WorkflowEdge(
                source_node_id=segment_node.id,
                source_port="masks",
                target_node_id="export",
                target_port="artifact",
            ),
        ],
    )


def multi_model_auto_labeling_template() -> WorkflowTemplate:
    """Cheaper semantic-review mode: one generated mask and two independent reviews."""

    name = "SAM 3 mask with Gemini and GPT review"
    return WorkflowTemplate(
        template_id="multi-model-segmentation-auto-labeling",
        name=name,
        description=(
            "Run a registered SAM 3-compatible primary segmenter, ask Gemini and GPT "
            "to review every candidate mask, and promote only masks receiving at least "
            "two accepted votes. This mode transmits image crops only after explicit opt-in."
        ),
        workflow=_workflow(
            WorkflowNode(
                id="segment-and-vote",
                node_type="segmenter",
                label="Segment and require semantic 2-of-3 review",
                configuration={
                    "model_id": "<select-sam3-segmenter>",
                    "confidence": 0.25,
                    "iou_threshold": 0.45,
                    "multi_model_consensus": {
                        "enabled": True,
                        "mode": "semantic_voters",
                        "required_primary_provider": "sam3_sidecar",
                        "prompt": "octocoral colony or fragment",
                        "required_votes": 2,
                        "sam_vote_threshold": 0.35,
                        "minimum_reviewer_confidence": 0.60,
                        "gemini_model": "gemini-2.5-flash",
                        "openai_model": "gpt-5-mini",
                        "crop_padding_fraction": 0.10,
                        "allow_remote_review": False,
                        "auto_accept": False,
                        "fail_closed": True,
                    },
                },
            ),
            name=name,
        ),
    )


def independent_mask_auto_labeling_template() -> WorkflowTemplate:
    """Roboflow-style mode: three independently generated masks and pixel consensus."""

    name = "SAM 3 + Gemini/SAM 2 + GPT/SAM 2 mask consensus"
    return WorkflowTemplate(
        template_id="independent-mask-segmentation-auto-labeling",
        name=name,
        description=(
            "Generate masks independently with SAM 3, Gemini detections refined by SAM 2, "
            "and GPT detections refined by SAM 2. Match same-class instances one-to-one and "
            "retain only groups receiving the configured number of independent votes."
        ),
        workflow=_workflow(
            WorkflowNode(
                id="independent-mask-consensus",
                node_type="segmenter",
                label="Generate and aggregate three independent mask branches",
                configuration={
                    "model_id": "<select-sam3-segmenter>",
                    "confidence": 0.25,
                    "iou_threshold": 0.45,
                    "multi_model_consensus": {
                        "enabled": True,
                        "mode": "independent_masks",
                        "required_primary_provider": "sam3_sidecar",
                        "sam2_model_id": "<select-registered-sam2-assist-model>",
                        "label_class_id": "<select-project-class>",
                        "predicted_label": "octocoral colony or fragment",
                        "prompt": "octocoral colony or fragment",
                        "required_votes": 2,
                        "iou_threshold": 0.30,
                        "aggregation": "pixel_majority",
                        "minimum_vlm_confidence": 0.25,
                        "gemini_model": "gemini-2.5-flash",
                        "openai_model": "gpt-5-mini",
                        "sam2_device": "auto",
                        "allow_remote_review": False,
                        "auto_accept": False,
                        "fail_closed": True,
                    },
                },
            ),
            name=name,
        ),
    )
