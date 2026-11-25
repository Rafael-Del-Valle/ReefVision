"""Frozen QC review workflows cannot re-sign mutable chronology as scientific evidence."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ReviewQueue, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.services.workflow_review_queue_integrity import (
    queue_item_evidence_sha256,
    validate_saved_queue_snapshot,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_review_queue_annotation_evidence_16 import _queue_item
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _run_frozen_graph,
    _study,
)
from reefvision.tests.test_workflow_review_queue_integrity_16 import (
    _set_v3_unweighted_signal,
    _v3_human_only_snapshot,
)


@pytest.mark.parametrize("signal_id", ["recent_import", "stale_review_state"])
def test_resigned_v3_frozen_snapshot_rejects_invented_temporal_signal(signal_id: str) -> None:
    """Even matching score/digests cannot add timestamps absent from a frozen version."""
    queue, items = _v3_human_only_snapshot()
    queue.dataset_version_id = "frozen-study"
    queue.scope_type = "dataset_version"
    for item in items:
        item.dataset_version_id = "frozen-study"
    validate_saved_queue_snapshot(queue, items)

    item = items[0]
    item.review_state = "in_progress"
    _set_v3_unweighted_signal(item, signal_id, 0.5)
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)
    assert item.review_state == "in_progress"


@pytest.mark.parametrize(
    "signal_id",
    [
        "recent_import",
        "stale_review_state",
        "model_reference",
        "count_disagreement",
        "class_reference",
        "rare_class_presence",
        "count_disagreement_endpoint",
        "unreviewed_state",
        "missing_group_metadata",
    ],
)
def test_saved_frozen_workflow_rejects_resigned_temporal_evidence(
    client: TestClient, signal_id: str
) -> None:
    """Standalone and saved QC agree; retry rejects forged chronology without a new queue."""
    project_id, _, version_id, _ = _study(client)
    # Zero weights isolate scientific evidence from aggregate-score checks.
    weights = {
        "recent_import": 0.0,
        "stale_review_state": 0.0,
        "count_disagreement": 0.0,
        "rare_class_presence": 0.0,
        "unreviewed_state": 0.0,
        "missing_group_metadata": 0.0,
    }
    standalone = client.post(
        f"/api/v1/dataset-versions/{version_id}/review-queues",
        json={"signal_weights": weights},
    )
    assert standalone.status_code == 201, standalone.text
    standalone_item = _queue_item(client, standalone.json()["id"])

    graph = _frozen_graph(version_id)
    qc_graph_node = next(node for node in graph["nodes"] if node["node_type"] == "qc_review_queue")
    qc_graph_node["parameters"] = {"signal_weights": weights}
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run_id, payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    workflow_item = _queue_item(client, payload["queue_id"])
    for item in (standalone_item, workflow_item):
        assert item["signal_values_json"]["recent_import"] == 0.0
        assert item["signal_values_json"]["stale_review_state"] == 0.0
        assert item["signal_values_json"]["count_disagreement"] == 1.0
        assert item["signal_values_json"]["rare_class_presence"] == 0.0
        assert item["signal_values_json"]["unreviewed_state"] == 0.0
        assert item["signal_values_json"]["missing_group_metadata"] in (0.0, 1.0)
        assert len(item["label_class_ids_json"]) == 1
        assert item["review_state"] == "pending"
    assert workflow_item["signal_values_json"] == standalone_item["signal_values_json"]
    assert workflow_item["score"] == standalone_item["score"]
    assert workflow_item["input_checksum"] == standalone_item["input_checksum"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        nodes = session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        ).all()
        by_type = {node.node_type: node for node in nodes}
        project_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == by_type["project_source"].id,
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        dataset_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == by_type["dataset_version_source"].id,
                WorkflowArtifact.producer_port_id == "dataset",
            )
        )
        queue = session.get(ReviewQueue, payload["queue_id"])
        assert project_artifact is not None and dataset_artifact is not None
        assert queue is not None and len(queue.items) == 1
        item = queue.items[0]
        if signal_id == "model_reference":
            assert item.model_ids_json == []
            item.model_ids_json = ["not-a-frozen-prediction-model"]
        elif signal_id == "class_reference":
            item.label_class_ids_json = ["not-a-frozen-annotation-class"]
        else:
            target = "count_disagreement" if signal_id == "count_disagreement_endpoint" else signal_id
            value = 0.0 if signal_id == "count_disagreement_endpoint" else 0.5
            if signal_id in {"unreviewed_state", "missing_group_metadata"}:
                value = 1.0 - item.signal_values_json[target]
            assert item.weights_json[target] == 0.0
            item.signal_values_json = {**item.signal_values_json, target: value}
            item.normalized_signals_json = {**item.normalized_signals_json, target: value}
            breakdown = [dict(part) for part in item.score_breakdown_json]
            for part in breakdown:
                if part["signal_id"] == target:
                    part["raw_value"] = value
                    part["normalized_value"] = value
            item.score_breakdown_json = breakdown
        queue.input_checksums_json = {
            **queue.input_checksums_json,
            "item_evidence_sha256": queue_item_evidence_sha256(queue.items),
        }
        session.flush()
        qc_node = by_type["qc_review_queue"]
        parameters = {
            **dict(qc_node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": qc_node.id,
        }
        inputs = {"project": [project_artifact], "dataset": [dataset_artifact]}
        expected_error = "snapshot failed integrity"
        if signal_id in {
            "class_reference",
            "rare_class_presence",
            "count_disagreement_endpoint",
            "unreviewed_state",
            "missing_group_metadata",
        }:
            # All internal score and evidence checks still pass. Only the
            # independent frozen annotation census reveals this substitution.
            validate_saved_queue_snapshot(queue, queue.items)
            saved_output = session.get(WorkflowArtifact, qc_node.output_artifact_ids_json[0])
            assert saved_output is not None
            saved_output.payload_json = {
                **saved_output.payload_json,
                "input_checksums": queue.input_checksums_json,
            }
            saved_output.payload_sha256 = canonical_json_sha256(saved_output.payload_json)
            session.flush()
            expected_error = "frozen annotation evidence does not match manifest"
        with pytest.raises(ValidationError, match=expected_error):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, parameters, inputs
            )
        session.rollback()

        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, parameters, inputs
        )
        assert replay[0]["payload"] == payload
        session.rollback()

    assert _queue_item(client, payload["queue_id"])["review_state"] == "pending"


@pytest.mark.parametrize("empty", [False, True])
def test_frozen_snapshot_rejects_resigned_prediction_selection(empty: bool) -> None:
    queue, items = _v3_human_only_snapshot()
    queue.dataset_version_id = "frozen-study"
    queue.scope_type = "dataset_version"
    for item in items:
        item.dataset_version_id = queue.dataset_version_id
    if empty:
        items = []
        queue.item_count = 0
        queue.summary_json = {
            "average_score": 0.0,
            "counts_by_severity": {},
            "counts_by_split": {},
            "top_image_ids": [],
        }
        queue.input_checksums_json["item_count"] = 0
        queue.input_checksums_json["queue_scope_sha256"] = canonical_json_sha256(
            {"image_ids": [], "scores": {}, "source_quality_control_run_id": None}
        )
        queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    validate_saved_queue_snapshot(queue, items)

    queue.configuration_json["review_below_confidence"] = 1.0
    queue.input_checksums_json["scoring_provenance_sha256"] = canonical_json_sha256(
        {
            "formula_id": queue.formula_id,
            "formula_version": queue.formula_version,
            "configuration": queue.configuration_json,
            "integrity_schema_version": "qc-review-queue-v3",
        }
    )
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)


def test_frozen_snapshot_rejects_resigned_prediction_model_reference() -> None:
    queue, items = _v3_human_only_snapshot()
    queue.dataset_version_id = "frozen-study"
    queue.scope_type = "dataset_version"
    for item in items:
        item.dataset_version_id = queue.dataset_version_id
    validate_saved_queue_snapshot(queue, items)

    items[0].model_ids_json = ["not-a-frozen-prediction-model"]
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)
    # The same model reference can be legitimate for a live project queue.
    queue.dataset_version_id = None
    queue.scope_type = "project"
    for item in items:
        item.dataset_version_id = None
    validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize("gap", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_prediction_free_count_gap_replay(gap: float) -> None:
    """Re-sign every weighted field; prediction-free gaps are still binary."""
    queue, items = _v3_human_only_snapshot()
    validate_saved_queue_snapshot(queue, items)
    score = round(gap * 100.0, 2)
    for item in items:
        item.signal_values_json["count_disagreement"] = gap
        item.normalized_signals_json["count_disagreement"] = gap
        part = next(
            part for part in item.score_breakdown_json if part["signal_id"] == "count_disagreement"
        )
        part["raw_value"] = gap
        part["normalized_value"] = gap
        part["contribution"] = score
        item.score_breakdown_json.sort(key=lambda part: (-part["contribution"], part["signal_id"]))
        item.score = score
        item.reason_summary = f"Model-versus-human count gap: +{score:.2f}" if score else None
    queue.summary_json["average_score"] = score
    queue.input_checksums_json["queue_scope_sha256"] = canonical_json_sha256(
        {
            "image_ids": sorted(item.image_id for item in items),
            "scores": {item.image_id: item.score for item in items},
            "source_quality_control_run_id": None,
        }
    )
    queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
    if gap in (0.0, 1.0):
        validate_saved_queue_snapshot(queue, items)
    else:
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
            validate_saved_queue_snapshot(queue, items)
        # Actual prediction references permit fractional disagreement.
        for item in items:
            item.model_ids_json = ["prediction-model"]
        queue.input_checksums_json["item_evidence_sha256"] = queue_item_evidence_sha256(items)
        validate_saved_queue_snapshot(queue, items)
