"""Saved Workflow Builder review must not approve vanished or altered evidence."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import WorkflowArtifact, WorkflowNodeRun
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_workflow_review_phase10 import _queue_seeded_review_run


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_artifact",
        "empty_binding",
        "duplicate_binding",
        "changed_payload",
        "foreign_project",
        "wrong_type",
        "missing_producer_output",
        "missing_prediction",
        "missing_classification",
    ],
)
def test_saved_review_rejects_invalid_or_lost_scientific_input(
    client: TestClient, corruption: str
) -> None:
    project, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, job_id
    ) is True
    before = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert before["run"]["status"] == "waiting_for_review"
    review_id = next(
        node["id"] for node in before["nodes"] if node["node_id"] == "review"
    )

    with app.state.session_factory() as session:
        review = session.get(WorkflowNodeRun, review_id)
        assert review is not None
        artifact_id = review.input_artifact_ids_json[0]
        artifact = session.get(WorkflowArtifact, artifact_id)
        assert artifact is not None
        if corruption == "missing_artifact":
            session.delete(artifact)
        elif corruption == "empty_binding":
            review.input_artifact_ids_json = []
        elif corruption == "duplicate_binding":
            review.input_artifact_ids_json = [artifact_id, artifact_id]
        elif corruption == "changed_payload":
            artifact.payload_json = {**artifact.payload_json, "count": 9000}
        elif corruption == "foreign_project":
            artifact.payload_json = {**artifact.payload_json, "project_id": "foreign"}
            artifact.payload_sha256 = canonical_json_sha256(artifact.payload_json)
        elif corruption == "wrong_type":
            artifact.data_type = "image_collection"
        elif corruption == "missing_producer_output":
            producer = session.get(WorkflowNodeRun, artifact.producer_node_run_id)
            assert producer is not None
            producer.output_artifact_ids_json = []
        elif corruption in {"missing_prediction", "missing_classification"}:
            artifact.data_type = (
                "detection_proposals"
                if corruption == "missing_prediction"
                else "classification_predictions"
            )
            field = (
                "proposal_ids"
                if corruption == "missing_prediction"
                else "prediction_ids"
            )
            artifact.payload_json = {
                "project_id": project["id"],
                field: ["missing-research-observation"],
            }
            artifact.payload_sha256 = canonical_json_sha256(artifact.payload_json)
        session.commit()

    resumed = client.post(
        f"/api/v1/workflow-node-runs/{review_id}/resume-review",
        json={"reviewed_by": "scientist", "note": "Attempted approval"},
    )
    assert resumed.status_code == 422, resumed.text
    after = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert after["run"]["status"] == "waiting_for_review"
    node = next(node for node in after["nodes"] if node["id"] == review_id)
    assert node["status"] == "waiting_for_review"
    assert "review_approval" not in (node["result_json"] or {})
    with app.state.session_factory() as session:
        assert session.scalar(
            select(WorkflowNodeRun.status).where(WorkflowNodeRun.id == review_id)
        ) == "waiting_for_review"
