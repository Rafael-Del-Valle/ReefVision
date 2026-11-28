"""Invalid local prediction evidence must not become QC priority or saved workflow truth."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    Job,
    ModelRegistration,
    PredictionProposal,
    ReviewQueue,
    ReviewQueueItem,
)
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review_queue_integrity import validate_saved_queue_snapshot
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_review_queue_annotation_evidence_16 import (
    _queue_item,
    _saved_workflow_queue,
)


def _local_prediction(client: TestClient, *, additional_pending: bool = False) -> tuple[str, str]:
    project = create_project(client, "Imported model confidence scientific QC")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="confidence-coral.png")
    image_id = imported["successful"][0]["image_id"]
    model_id, job_id, prediction_id = (str(uuid4()) for _ in range(3))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=project_id,
                purpose="detection",
                display_name="Synthetic locally registered model",
                source_filename="synthetic.pt",
                managed_path=f"models/synthetic-{model_id}.pt",
                sha256="d" * 64,
                file_size_bytes=0,
                framework="test",
                task="detect",
                provider_name="local_test",
                provider_version="1",
                class_map_json={},
            )
        )
        session.add(
            Job(
                id=job_id,
                project_id=project_id,
                job_type="inference",
                status="succeeded",
                request_json={},
            )
        )
        session.flush()
        prediction_ids = [prediction_id]
        if additional_pending:
            prediction_ids.append(str(uuid4()))
        for current_prediction_id in prediction_ids:
            session.add(
                PredictionProposal(
                    id=current_prediction_id,
                    project_id=project_id,
                    image_id=image_id,
                    model_id=model_id,
                    inference_job_id=job_id,
                    model_checksum="d" * 64,
                    label_class_id=project["label_classes"][0]["id"],
                    predicted_label="Octocoral polyp",
                    predicted_index=0,
                    confidence=0.75,
                    x_min=5,
                    y_min=5,
                    x_max=20,
                    y_max=20,
                    review_status="pending",
                    was_edited=False,
                    provenance_json={"source": "local_fixture"},
                )
            )
        session.commit()
    return project_id, prediction_id


def _foreign_image_id(client: TestClient) -> str:
    foreign_project = create_project(client, "Independent QC project")
    imported = import_one(client, foreign_project["id"], filename="foreign-coral.png")
    return str(imported["successful"][0]["image_id"])


def _expected_error(bad_evidence: float | str) -> str:
    if bad_evidence == "foreign_image":
        return "inconsistent project/image scope"
    if isinstance(bad_evidence, str):
        return "invalid review status"
    return "confidence must be finite and within"


@pytest.mark.parametrize(
    "bad_evidence",
    [-0.01, 1.01, float("inf"), float("-inf"), "approved", "Pending", "", "foreign_image"],
)
def test_standalone_qc_rejects_corrupt_model_confidence_without_writes(
    client: TestClient, bad_evidence: float | str
) -> None:
    project_id, prediction_id = _local_prediction(client)
    url = f"/api/v1/projects/{project_id}/review-queues"
    original = client.post(url, json={})
    assert original.status_code == 201, original.text
    original_item = _queue_item(client, original.json()["id"])
    assert original_item["review_state"] == "pending"

    app = cast(FastAPI, client.app)
    foreign_image_id = _foreign_image_id(client) if bad_evidence == "foreign_image" else None
    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, prediction_id)
        assert proposal is not None
        if foreign_image_id is not None:
            proposal.image_id = foreign_image_id
        elif isinstance(bad_evidence, str):
            proposal.review_status = bad_evidence
        else:
            proposal.confidence = bad_evidence
        session.commit()

    invalid = client.post(url, json={})
    assert invalid.status_code == 400, invalid.text
    expected_error = _expected_error(bad_evidence)
    assert expected_error in invalid.text
    if isinstance(bad_evidence, str):
        filtered = client.post(url, json={"review_below_confidence": 1.0})
        assert filtered.status_code == 400, filtered.text
        assert expected_error in filtered.text
    queues = client.get(url)
    assert queues.status_code == 200, queues.text
    assert len(queues.json()) == 1
    assert (
        _queue_item(client, original.json()["id"])["input_checksum"]
        == original_item["input_checksum"]
    )


@pytest.mark.parametrize(
    "bad_evidence",
    [-0.01, 1.01, float("inf"), float("-inf"), "approved", "Pending", "", "foreign_image"],
)
def test_saved_workflow_qc_rejects_corrupt_confidence_then_recovers_without_approval(
    client: TestClient, bad_evidence: float | str
) -> None:
    project_id, prediction_id = _local_prediction(client)
    baseline_id = _saved_workflow_queue(client, project_id, f"qc-finite-before-{uuid4()}")
    baseline = _queue_item(client, baseline_id)
    assert baseline["review_state"] == "pending"
    app = cast(FastAPI, client.app)

    graph = {
        "graph_id": f"qc-finite-recovery-{uuid4()}",
        "name": "Offline QC prediction-confidence safeguard",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "qc", "node_type": "qc_review_queue"},
        ],
        "edges": [
            {
                "edge_id": "project-qc",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "qc",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text

    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, prediction_id)
        assert proposal is not None
        original_image_id = proposal.image_id

    foreign_image_id = _foreign_image_id(client) if bad_evidence == "foreign_image" else None
    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, prediction_id)
        assert proposal is not None
        if foreign_image_id is not None:
            proposal.image_id = foreign_image_id
        elif isinstance(bad_evidence, str):
            proposal.review_status = bad_evidence
        else:
            proposal.confidence = bad_evidence
        session.commit()

    endpoint = f"/api/v1/projects/{project_id}/workflow-runs"
    queued = client.post(endpoint, json={"graph_record_id": saved.json()["id"]})
    assert queued.status_code == 202, queued.text
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    failed = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert failed.status_code == 200, failed.text
    # A run-detail response wraps status under "run"; a failed QC node must
    # not produce a review-queue artifact or implicitly approve predictions.
    failed_detail = failed.json()
    assert failed_detail["run"]["status"] == "failed"
    expected_error = _expected_error(bad_evidence)
    assert expected_error in (failed_detail["run"]["error_message"] or "")
    assert any(
        node["node_type"] == "qc_review_queue" and node["status"] == "failed"
        for node in failed_detail["nodes"]
    )
    assert not [
        artifact
        for artifact in failed_detail["artifacts"]
        if artifact["data_type"] == "review_queue_reference"
    ]
    with app.state.session_factory() as session:
        assert (
            session.scalar(select(ReviewQueue).where(ReviewQueue.project_id == project_id))
            is not None
        )
        assert (
            len(
                session.scalars(
                    select(ReviewQueue).where(ReviewQueue.project_id == project_id)
                ).all()
            )
            == 1
        )

        proposal = session.get(PredictionProposal, prediction_id)
        assert proposal is not None
        proposal.confidence = 0.75
        proposal.review_status = "pending"
        proposal.image_id = original_image_id
        session.commit()

    recovered = client.post(endpoint, json={"graph_record_id": saved.json()["id"]})
    assert recovered.status_code == 202, recovered.text
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(recovered.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{recovered.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    assert not detail.json()["run"]["error_message"]
    artifacts = [
        artifact
        for artifact in detail.json()["artifacts"]
        if artifact["data_type"] == "review_queue_reference"
    ]
    assert len(artifacts) == 1
    output = artifacts[0]["payload_json"]
    assert output["priority_score_unit"] == "dimensionless"
    assert output["review_status"] == "requires_researcher_review"
    current = _queue_item(client, output["queue_id"])
    assert current["input_checksum"] == baseline["input_checksum"]
    assert current["review_state"] == "pending"
    with app.state.session_factory() as session:
        # Only the baseline and the explicitly retried saved run may own QC
        # queues; the failed run must not leave a ghost review artifact.
        assert (
            len(
                session.scalars(
                    select(ReviewQueue).where(ReviewQueue.project_id == project_id)
                ).all()
            )
            == 2
        )
        queue = session.get(ReviewQueue, baseline_id)
        assert queue is not None
        items = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.review_queue_id == baseline_id)
        ).all()
        validate_saved_queue_snapshot(queue, items)
        assert items[0].review_state == "pending"
