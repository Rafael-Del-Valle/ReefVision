"""Confidence selection is valid for live predictions, not frozen dataset QC."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ReviewQueue, ReviewQueueItem
from reefvision.services.workflow_review_queue_integrity import validate_saved_queue_snapshot
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _run_frozen_graph,
    _study,
)


def test_frozen_confidence_filter_fails_before_any_queue_or_review_write(
    client: TestClient,
) -> None:
    project_id, _, version_id, _ = _study(client)
    url = f"/api/v1/dataset-versions/{version_id}/review-queues"
    invalid = client.post(url, json={"review_below_confidence": 0.5})
    assert invalid.status_code == 422, invalid.text
    assert "do not snapshot pending predictions" in invalid.text
    listing = client.get(url)
    assert listing.status_code == 200, listing.text
    assert listing.json() == []

    # The same threshold is meaningful for a live project, even when this
    # fixture has no pending model proposals to select.
    live = client.post(
        f"/api/v1/projects/{project_id}/review-queues",
        json={"review_below_confidence": 0.5},
    )
    assert live.status_code == 201, live.text
    assert live.json()["scope_type"] == "project"
    assert live.json()["item_count"] == 0


def test_saved_frozen_graph_plan_rejects_inapplicable_confidence_gate(
    client: TestClient,
) -> None:
    project_id, _, version_id, _ = _study(client)
    graph = _frozen_graph(version_id)
    graph["nodes"][-1]["parameters"] = {"review_below_confidence": 0.5}

    invalid = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph
    )
    assert invalid.status_code == 200, invalid.text
    plan = invalid.json()
    assert plan["valid"] is False
    assert plan["executable"] is False
    assert any(
        item["code"] == "unsupported_frozen_qc_confidence_filter"
        and item["node_id"] == "qc"
        for item in plan["issues"]
    )

    # A normal version-scoped graph remains executable and preserves a
    # dimensionless, checksummed queue awaiting explicit researcher review.
    valid_graph = _frozen_graph(version_id)
    checked = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=valid_graph
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["valid"] and checked.json()["executable"]
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": valid_graph}
    )
    assert saved.status_code == 201, saved.text
    _, output = _run_frozen_graph(client, project_id, saved.json()["id"])
    assert output["review_status"] == "requires_researcher_review"
    assert output["priority_score_unit"] == "dimensionless"
    assert output["dataset_version_id"] == version_id

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        queue = session.get(ReviewQueue, output["queue_id"])
        assert queue is not None
        items = session.scalars(
            select(ReviewQueueItem).where(
                ReviewQueueItem.review_queue_id == queue.id
            )
        ).all()
        assert len(items) == 1
        assert items[0].review_state == "pending"
        validate_saved_queue_snapshot(queue, items)
