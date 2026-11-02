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
    _v3_snapshot,
)


@pytest.mark.parametrize("signal_id", ["recent_import", "stale_review_state"])
def test_resigned_v3_frozen_snapshot_rejects_invented_temporal_signal(signal_id: str) -> None:
    """Even matching score/digests cannot add timestamps absent from a frozen version."""
    queue, items = _v3_snapshot()
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


@pytest.mark.parametrize("signal_id", ["recent_import", "stale_review_state"])
def test_saved_frozen_workflow_rejects_resigned_temporal_evidence(
    client: TestClient, signal_id: str
) -> None:
    """Standalone and saved QC agree; retry rejects forged chronology without a new queue."""
    project_id, _, version_id, _ = _study(client)
    # Zero temporal weights isolate the scientific evidence check from the
    # already-tested aggregate-score and priority-order integrity checks.
    weights = {"recent_import": 0.0, "stale_review_state": 0.0}
    standalone = client.post(
        f"/api/v1/dataset-versions/{version_id}/review-queues",
        json={"signal_weights": weights},
    )
    assert standalone.status_code == 201, standalone.text
    standalone_item = _queue_item(client, standalone.json()["id"])

    graph = _frozen_graph(version_id)
    next(node for node in graph["nodes"] if node["node_type"] == "qc_review_queue")[
        "parameters"
    ] = {"signal_weights": weights}
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
        assert item["review_state"] == "pending"
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
        assert item.weights_json[signal_id] == 0.0
        item.signal_values_json = {**item.signal_values_json, signal_id: 0.5}
        item.normalized_signals_json = {**item.normalized_signals_json, signal_id: 0.5}
        breakdown = [dict(part) for part in item.score_breakdown_json]
        for part in breakdown:
            if part["signal_id"] == signal_id:
                part["raw_value"] = 0.5
                part["normalized_value"] = 0.5
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
        with pytest.raises(ValidationError, match="snapshot failed integrity"):
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
