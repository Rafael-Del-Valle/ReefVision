"""Saved Workflow Builder review must not approve vanished or altered evidence."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import Job, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review import _input_artifacts, _pending_review_count
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
        "duplicate_identifiers",
    ],
)
def test_saved_review_rejects_invalid_or_lost_scientific_input(
    client: TestClient, corruption: str
) -> None:
    project, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id) is True
    before = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert before["run"]["status"] == "waiting_for_review"
    review_id = next(node["id"] for node in before["nodes"] if node["node_id"] == "review")

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
        elif corruption == "duplicate_identifiers":
            # Persisted, correctly rehashed evidence can still claim the same
            # scientific prediction twice; it must not silently deduplicate.
            artifact.data_type = "detection_proposals"
            artifact.payload_json = {
                "project_id": project["id"],
                "proposal_ids": ["repeated-proposal", "repeated-proposal"],
            }
            artifact.payload_sha256 = canonical_json_sha256(artifact.payload_json)
        elif corruption in {"missing_prediction", "missing_classification"}:
            artifact.data_type = (
                "detection_proposals"
                if corruption == "missing_prediction"
                else "classification_predictions"
            )
            field = "proposal_ids" if corruption == "missing_prediction" else "prediction_ids"
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
    # Domain ValidationError is mapped to HTTP 400, not Pydantic's 422.
    expected_details = {
        "missing_artifact": "no longer exists",
        "empty_binding": "invalid saved input bindings",
        "duplicate_binding": "invalid saved input bindings",
        "changed_payload": "project or checksum validation",
        "foreign_project": "project or checksum validation",
        "wrong_type": "invalid run or scientific data type",
        "missing_producer_output": "producer provenance",
        "missing_prediction": "missing or foreign prediction proposals",
        "missing_classification": "invalid run or scientific data type",
        "duplicate_identifiers": "duplicate prediction identifiers",
    }
    assert resumed.status_code == 400, resumed.text
    assert expected_details[corruption] in resumed.json()["detail"]
    after = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert after["run"]["status"] == "waiting_for_review"
    node = next(node for node in after["nodes"] if node["id"] == review_id)
    assert node["status"] == "waiting_for_review"
    assert "review_approval" not in (node["result_json"] or {})
    with app.state.session_factory() as session:
        assert (
            session.scalar(select(WorkflowNodeRun.status).where(WorkflowNodeRun.id == review_id))
            == "waiting_for_review"
        )
        parent_job = session.get(Job, job_id)
        assert parent_job is not None
        assert parent_job.status == "waiting_for_review"


def test_legacy_nullable_project_scope_stays_bound_to_saved_run(client: TestClient) -> None:
    """Older pose-style artifacts may omit their project hint; run provenance is required."""
    project, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id) is True
    with app.state.session_factory() as session:
        review = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_id == "review",
            )
        )
        assert review is not None
        artifact = session.get(WorkflowArtifact, review.input_artifact_ids_json[0])
        assert artifact is not None
        artifact.payload_json = {**artifact.payload_json, "project_id": None}
        artifact.payload_sha256 = canonical_json_sha256(artifact.payload_json)
        session.commit()

    with app.state.session_factory() as session:
        review = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_id == "review",
            )
        )
        assert review is not None
        artifacts = _input_artifacts(session, review, project_id=project["id"])
        assert len(artifacts) == 1
        assert artifacts[0].payload_json["project_id"] is None
    detail = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert detail["run"]["status"] == "waiting_for_review"


@pytest.mark.parametrize(
    ("data_type", "field"),
    [
        ("detection_proposals", "proposal_ids"),
        ("mask_proposals", "proposal_ids"),
        ("classification_predictions", "prediction_ids"),
    ],
)
def test_standalone_review_rejects_repeated_prediction_evidence(
    client: TestClient, data_type: str, field: str
) -> None:
    """All three typed prediction inputs must reject repeated identifiers."""
    app = cast(FastAPI, client.app)
    artifact = WorkflowArtifact(
        workflow_run_id="synthetic-run",
        producer_node_run_id="synthetic-producer",
        producer_port_id="proposals",
        data_type=data_type,
        payload_json={field: ["same-scientific-prediction", "same-scientific-prediction"]},
        payload_sha256="a" * 64,
    )
    with app.state.session_factory() as session:
        with pytest.raises(ValidationError, match="duplicate prediction identifiers"):
            _pending_review_count(session, [artifact], project_id="synthetic-project")
