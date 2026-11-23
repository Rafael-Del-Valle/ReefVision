"""Saved Workflow Builder review must not approve vanished or altered evidence."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    Job,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
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
        "duplicate_producer_output",
        "nonstring_producer_output",
        "empty_producer_output",
        "whitespace_producer_output",
        "missing_additional_producer_output",
        "foreign_additional_producer_output",
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
        elif corruption in {
            "duplicate_producer_output",
            "nonstring_producer_output",
            "empty_producer_output",
            "whitespace_producer_output",
            "missing_additional_producer_output",
            "foreign_additional_producer_output",
        }:
            producer = session.get(WorkflowNodeRun, artifact.producer_node_run_id)
            assert producer is not None
            if corruption == "duplicate_producer_output":
                producer.output_artifact_ids_json = [artifact_id, artifact_id]
            elif corruption == "nonstring_producer_output":
                producer.output_artifact_ids_json = cast(list[str], [artifact_id, 7])
            elif corruption == "empty_producer_output":
                producer.output_artifact_ids_json = [artifact_id, ""]
            elif corruption == "whitespace_producer_output":
                producer.output_artifact_ids_json = [artifact_id, "  "]
            elif corruption == "missing_additional_producer_output":
                producer.output_artifact_ids_json = [artifact_id, "deleted-producer-output"]
            else:
                other_output = session.scalar(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.workflow_run_id == run_id,
                        WorkflowArtifact.producer_node_run_id != producer.id,
                    )
                )
                assert other_output is not None
                producer.output_artifact_ids_json = [artifact_id, other_output.id]
        elif corruption == "duplicate_identifiers":
            # A consensus producer cannot emit detection proposals, even if
            # the payload checksum is deliberately recomputed.
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

    if corruption in {
        "duplicate_producer_output",
        "nonstring_producer_output",
        "empty_producer_output",
        "whitespace_producer_output",
        "missing_additional_producer_output",
        "foreign_additional_producer_output",
    }:
        # A direct consumer must refuse the same damaged producer manifest
        # before the normal saved-workflow HTTP approval endpoint is called.
        with app.state.session_factory() as session:
            review = session.get(WorkflowNodeRun, review_id)
            assert review is not None
            with pytest.raises(ValidationError, match="producer output"):
                _input_artifacts(session, review, project_id=str(project["id"]))

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
        "duplicate_producer_output": "producer output identifiers are invalid or duplicated",
        "nonstring_producer_output": "producer output identifiers are invalid or duplicated",
        "empty_producer_output": "producer output identifiers are invalid or duplicated",
        "whitespace_producer_output": "producer output identifiers are invalid or duplicated",
        "missing_additional_producer_output": "producer output manifest references missing or foreign artifacts",
        "foreign_additional_producer_output": "producer output manifest references missing or foreign artifacts",
        "missing_prediction": "violates saved typed port contract",
        "missing_classification": "invalid run or scientific data type",
        "duplicate_identifiers": "violates saved typed port contract",
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


@pytest.mark.parametrize(
    ("proposal_ids", "expected_refusal"),
    [
        (["missing-research-observation"], "missing or foreign prediction proposals"),
        (["same-prediction", "same-prediction"], "duplicate prediction identifiers"),
    ],
)
def test_saved_typed_detection_review_rejects_invalid_prediction_evidence(
    client: TestClient, proposal_ids: list[str], expected_refusal: str
) -> None:
    """Exercise the prediction checks behind a *valid* detect-to-review port."""
    project, run_id, job_id = _queue_seeded_review_run(client, proposals_only=True)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id)
    paused = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert paused["run"]["status"] == "waiting_for_review"
    review_id = next(node["id"] for node in paused["nodes"] if node["node_id"] == "review")

    with app.state.session_factory() as session:
        review = session.get(WorkflowNodeRun, review_id)
        assert review is not None
        artifact = session.get(WorkflowArtifact, review.input_artifact_ids_json[0])
        assert artifact is not None
        assert artifact.data_type == "detection_proposals"
        producer = session.get(WorkflowNodeRun, artifact.producer_node_run_id)
        assert producer is not None and producer.node_id == "detect"
        artifact.payload_json = {"project_id": project["id"], "proposal_ids": proposal_ids}
        artifact.payload_sha256 = canonical_json_sha256(artifact.payload_json)
        session.commit()

    # Direct service and persisted HTTP execution must pass typed provenance
    # first, then refuse missing or repeated biological prediction identities.
    with app.state.session_factory() as session:
        review = session.get(WorkflowNodeRun, review_id)
        assert review is not None
        typed_inputs = _input_artifacts(session, review, project_id=str(project["id"]))
        assert len(typed_inputs) == 1
        with pytest.raises(ValidationError, match=expected_refusal):
            _pending_review_count(session, typed_inputs, project_id=str(project["id"]))

    resumed = client.post(
        f"/api/v1/workflow-node-runs/{review_id}/resume-review",
        json={"reviewed_by": "scientist", "note": "Invalid research evidence"},
    )
    assert resumed.status_code == 400, resumed.text
    assert expected_refusal in resumed.json()["detail"]
    after = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert after["run"]["status"] == "waiting_for_review"
    node = next(node for node in after["nodes"] if node["id"] == review_id)
    assert node["status"] == "waiting_for_review"
    assert "review_approval" not in (node["result_json"] or {})
    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None and job.status == "waiting_for_review"


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
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="duplicate prediction identifiers"),
    ):
        _pending_review_count(session, [artifact], project_id="synthetic-project")


@pytest.mark.parametrize(
    ("alteration", "error_text"),
    [
        ("foreign_same_run_producer", "not connected to its saved graph edge"),
        ("wrong_output_port", "not connected to its saved graph edge"),
        ("wrong_producer_type", "node or producer differs from saved graph"),
        ("changed_graph_without_hash", "saved graph provenance failed validation"),
        ("changed_run_graph_hash", "saved graph provenance failed validation"),
        ("rewired_target_port", "violates saved typed port contract"),
        ("rewired_source_port", "violates saved typed port contract"),
        ("incompatible_produced_type", "violates saved typed port contract"),
    ],
)
def test_saved_review_rejects_rebound_graph_or_borrowed_producer(
    client: TestClient, alteration: str, error_text: str
) -> None:
    """Standalone and persisted workflow review cannot approve rewired biological input."""
    project, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id)
    paused = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert paused["run"]["status"] == "waiting_for_review"
    review_id = next(node["id"] for node in paused["nodes"] if node["node_id"] == "review")

    with app.state.session_factory() as session:
        run = session.get(WorkflowRun, run_id)
        review = session.get(WorkflowNodeRun, review_id)
        assert run is not None and review is not None
        artifact = session.get(WorkflowArtifact, review.input_artifact_ids_json[0])
        assert artifact is not None
        producer = session.get(WorkflowNodeRun, artifact.producer_node_run_id)
        assert producer is not None
        graph = session.get(WorkflowGraphRecord, run.workflow_graph_record_id)
        assert graph is not None
        if alteration == "foreign_same_run_producer":
            # A different succeeded node can claim the intact, correctly hashed
            # artifact and publish it as its own output. Only the saved edge
            # proves that the review gate was supposed to consume consensus.
            unrelated = session.scalar(
                select(WorkflowNodeRun).where(
                    WorkflowNodeRun.workflow_run_id == run_id,
                    WorkflowNodeRun.node_id == "detect",
                )
            )
            assert unrelated is not None and unrelated.status == "succeeded"
            producer.output_artifact_ids_json = []
            unrelated.output_artifact_ids_json = [artifact.id]
            artifact.producer_node_run_id = unrelated.id
        elif alteration == "wrong_output_port":
            artifact.producer_port_id = "unconnected-output"
        elif alteration == "wrong_producer_type":
            producer.node_type = "detection_inference"
        elif alteration == "incompatible_produced_type":
            # A consensus producer can never output detection_proposals.
            # The review gate accepts both types, so the node type alone
            # cannot establish the actual output-port contract.
            artifact.data_type = "detection_proposals"
        elif alteration in {"rewired_target_port", "rewired_source_port"}:
            # Rehash the entire saved graph and its run provenance to prove
            # that checksum agreement alone cannot authorize a forged port.
            key = "target_port_id" if alteration == "rewired_target_port" else "source_port_id"
            forged_port = "invented-scientific-port"
            changed = dict(graph.graph_json)
            changed["edges"] = [
                {**edge, key: forged_port} if edge.get("target_node_id") == "review" else edge
                for edge in changed["edges"]
            ]
            graph.graph_json = changed
            graph.graph_sha256 = canonical_json_sha256(changed)
            run.graph_sha256 = graph.graph_sha256
            if alteration == "rewired_source_port":
                artifact.producer_port_id = forged_port
        elif alteration == "changed_graph_without_hash":
            graph.graph_json = {**graph.graph_json, "name": "Unreviewed replacement graph"}
        else:
            run.graph_sha256 = "f" * 64
        session.commit()

    # Direct service caller and normal executable, persisted review endpoint
    # must reach the same fail-closed result.
    with app.state.session_factory() as session:
        review = session.get(WorkflowNodeRun, review_id)
        assert review is not None
        with pytest.raises(ValidationError, match=error_text):
            _input_artifacts(session, review, project_id=str(project["id"]))

    resumed = client.post(
        f"/api/v1/workflow-node-runs/{review_id}/resume-review",
        json={"reviewed_by": "scientist", "note": "Do not approve changed source"},
    )
    assert resumed.status_code == 400, resumed.text
    assert error_text in resumed.json()["detail"]
    after = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert after["run"]["status"] == "waiting_for_review"
    review_status = next(node for node in after["nodes"] if node["id"] == review_id)
    assert review_status["status"] == "waiting_for_review"
    assert "review_approval" not in (review_status["result_json"] or {})
    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None and job.status == "waiting_for_review"
