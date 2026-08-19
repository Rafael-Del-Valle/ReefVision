from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from reefvision.jobs.workflow_cache_runtime import _node_cache_eligible
from reefvision.jobs.workflow_segmentation_review_runtime import _review_summary
from reefvision.services.workflow_definition_extensions import (
    install_workflow_definition_extensions,
)
from reefvision.services.workflow_segmentation_templates import (
    detector_guided_prompt_assist_template,
)
from reefvision.services.workflows import NODE_DEFINITIONS


def test_unified_segmenter_exposes_instance_semantic_and_assist_tasks() -> None:
    install_workflow_definition_extensions()

    segmenter = NODE_DEFINITIONS["segmenter"]

    assert segmenter.display_name == "Unified segmenter"
    assert set(segmenter.model_tasks) == {
        "segment",
        "semantic_segment",
        "assist_segmentation",
    }
    assert segmenter.inputs["images"] == ("images", True)
    assert segmenter.inputs["prompts"] == ("detections", False)


def test_prompt_assist_template_connects_detector_boxes_to_segmenter_prompts() -> None:
    template = detector_guided_prompt_assist_template()
    nodes = {node.id: node for node in template.workflow.nodes}

    assert nodes["detect"].node_type == "detector"
    assert nodes["assist"].node_type == "segmenter"
    assert any(
        edge.source_node_id == "detect"
        and edge.source_port == "detections"
        and edge.target_node_id == "assist"
        and edge.target_port == "prompts"
        for edge in template.workflow.edges
    )
    assert any(
        edge.source_node_id == "assist"
        and edge.source_port == "masks"
        and edge.target_node_id == "export"
        for edge in template.workflow.edges
    )


def test_review_summary_separates_accepted_rejected_and_pending_masks() -> None:
    proposals = [
        SimpleNamespace(
            id="accepted",
            review_status="accepted",
            accepted_mask_annotation_id="mask-1",
        ),
        SimpleNamespace(
            id="rejected",
            review_status="rejected",
            accepted_mask_annotation_id=None,
        ),
        SimpleNamespace(
            id="pending",
            review_status="pending",
            accepted_mask_annotation_id=None,
        ),
    ]

    summary = _review_summary(cast(list[Any], proposals))

    assert summary["proposal_count"] == 3
    assert summary["accepted_count"] == 1
    assert summary["rejected_count"] == 1
    assert summary["unresolved_count"] == 1
    assert summary["accepted_mask_annotation_ids"] == ["mask-1"]
    assert summary["rejected_prediction_ids"] == ["rejected"]
    assert summary["unresolved_prediction_ids"] == ["pending"]


def test_failed_run_cache_reuses_only_nodes_recorded_as_succeeded() -> None:
    reusable = SimpleNamespace(
        status="failed",
        node_state_json={"segment": {"status": "succeeded"}},
    )
    failed_node = SimpleNamespace(
        status="failed",
        node_state_json={"segment": {"status": "failed"}},
    )
    succeeded_run = SimpleNamespace(status="succeeded", node_state_json={})

    assert _node_cache_eligible(cast(Any, reusable), "segment") is True
    assert _node_cache_eligible(cast(Any, failed_node), "segment") is False
    assert _node_cache_eligible(cast(Any, succeeded_run), "segment") is True
