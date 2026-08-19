from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from reefvision.jobs import workflow_runs
from reefvision.jobs.workflow_cache_runtime import (
    _artifact_cache_eligible,
    _node_cache_eligible,
    _select_cached_source_artifacts,
    _stable_copy_cached_outputs,
)
from reefvision.jobs.workflow_segmentation_review_runtime import _review_summary
from reefvision.jobs.workflow_segmentation_runtime import _assist_provider
from reefvision.ml.catalog_expansion import UnifiedSegmentAnythingAssistProvider
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


def test_segment_anything_uses_checkpoint_aware_smart_mask_provider() -> None:
    provider = _assist_provider("segment_anything")

    assert isinstance(provider, UnifiedSegmentAnythingAssistProvider)


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


def test_review_dependent_measurements_are_recomputed_not_cached() -> None:
    reviewed_measurement = SimpleNamespace(
        artifact_type="measurements",
        payload_json={
            "segmentation_review": {"review_resolved": True},
            "_cache_key": "measurement-key",
        },
    )
    ordinary_measurement = SimpleNamespace(
        artifact_type="measurements",
        payload_json={"_cache_key": "measurement-key"},
    )
    segmentation = SimpleNamespace(
        artifact_type="masks",
        payload_json={"_cache_key": "segment-key"},
    )

    assert _artifact_cache_eligible(cast(Any, reviewed_measurement)) is False
    assert _artifact_cache_eligible(cast(Any, ordinary_measurement)) is True
    assert _artifact_cache_eligible(cast(Any, segmentation)) is True


def test_cache_selects_complete_output_set_from_one_newest_source_run() -> None:
    newest = SimpleNamespace(
        id="run-newest",
        status="failed",
        node_state_json={"segment": {"status": "succeeded"}},
    )
    older = SimpleNamespace(
        id="run-older",
        status="succeeded",
        node_state_json={},
    )
    rows = [
        (
            SimpleNamespace(
                id="new-masks",
                port_name="masks",
                artifact_type="masks",
                payload_json={"_cache_key": "same-key"},
            ),
            newest,
        ),
        (
            SimpleNamespace(
                id="new-qc",
                port_name="qc",
                artifact_type="artifact",
                payload_json={"_cache_key": "same-key"},
            ),
            newest,
        ),
        (
            SimpleNamespace(
                id="old-masks",
                port_name="masks",
                artifact_type="masks",
                payload_json={"_cache_key": "same-key"},
            ),
            older,
        ),
    ]

    selected = _select_cached_source_artifacts(
        cast(Any, rows),
        current_run_id="current",
        node_id="segment",
        cache_key="same-key",
    )

    assert [artifact.id for artifact in selected] == ["new-masks", "new-qc"]


def test_cached_artifact_copy_preserves_exact_semantic_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_payload = {
        "prediction_ids": ["proposal-1"],
        "_cache_key": "stable-key",
    }
    cached = SimpleNamespace(
        port_name="detections",
        artifact_type="detections",
        payload_json=dict(original_payload),
        managed_path=None,
        size_bytes=None,
    )
    captured: list[dict[str, Any]] = []

    def fake_save_artifact(_session: Any, **kwargs: Any) -> Any:
        captured.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(workflow_runs, "_save_artifact", fake_save_artifact)

    _stable_copy_cached_outputs(
        cast(Any, object()),
        run=cast(Any, SimpleNamespace(id="new-run")),
        node_id="detect",
        cached=[cast(Any, cached)],
    )

    assert captured[0]["payload"] == original_payload
    assert "_reused_from_artifact_id" not in captured[0]["payload"]
