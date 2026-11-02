"""Saved v3 QC workflows must preserve explicit confidence-selection provenance."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ReviewQueue, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.services.workflow_review_queue_integrity import validate_saved_queue_snapshot
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_review_queue_annotation_evidence_16 import _queue_item
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _run_frozen_graph,
    _study,
)
from reefvision.tests.test_workflow_review_queue_integrity_16 import _v3_snapshot, snapshot


def _resign_scoring(queue: Any) -> None:
    """Model an attacker recomputing the digest after changing persisted metadata."""
    checksums = queue.input_checksums_json
    provenance = {
        "formula_id": queue.formula_id,
        "formula_version": queue.formula_version,
        "configuration": queue.configuration_json,
    }
    if checksums.get("integrity_schema_version") == "qc-review-queue-v3":
        provenance["integrity_schema_version"] = "qc-review-queue-v3"
    queue.input_checksums_json = {
        **checksums,
        "scoring_provenance_sha256": canonical_json_sha256(provenance),
    }


def test_v3_missing_confidence_selection_key_fails_closed_even_when_resigned() -> None:
    queue, items = _v3_snapshot()
    validate_saved_queue_snapshot(queue, items)
    items[0].review_state = "in_progress"
    queue.configuration_json.pop("review_below_confidence")
    _resign_scoring(queue)
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)
    assert items[0].review_state == "in_progress"


def test_v2_historical_missing_confidence_selection_key_remains_readable() -> None:
    queue, items = snapshot()
    queue.configuration_json.pop("review_below_confidence")
    _resign_scoring(queue)
    validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize("missing_field", ["review_below_confidence", "ruleset_version"])
def test_saved_frozen_workflow_rejects_resigned_missing_selection_provenance(
    client: TestClient, missing_field: str
) -> None:
    """A saved typed QC run must reject incomplete selection metadata on replay."""
    project_id, _, version_id, _ = _study(client)
    graph = _frozen_graph(version_id)
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run_id, payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    assert payload["review_status"] == "requires_researcher_review"
    assert payload["priority_score_unit"] == "dimensionless"
    original_item = _queue_item(client, payload["queue_id"])

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        node_runs = session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        ).all()
        by_type = {node.node_type: node for node in node_runs}
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
        assert queue is not None
        assert project_artifact is not None and dataset_artifact is not None
        assert queue.configuration_json.get("review_below_confidence") is None
        queue.configuration_json = {
            key: value for key, value in queue.configuration_json.items() if key != missing_field
        }
        _resign_scoring(queue)
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

    after = _queue_item(client, payload["queue_id"])
    assert after["id"] == original_item["id"]
    assert after["review_state"] == original_item["review_state"] == "pending"
    assert after["input_checksum"] == original_item["input_checksum"]
