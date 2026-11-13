from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    Job,
    ModelRegistration,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_execution import WorkflowArtifactSpec, WorkflowExecutionService
from reefvision.services.workflow_review import WorkflowReviewRequired
from reefvision.tests.test_annotations import create_project
from reefvision.tests.workflow_review_test_support import seed_review_upstream_artifacts


def _review_graph(model_id: str) -> dict[str, object]:
    return {
        "graph_id": "review-resume-consensus",
        "name": "Consensus human review",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "images", "node_type": "project_images"},
            {
                "node_id": "model",
                "node_type": "registered_model_source",
                "parameters": {"model_id": model_id},
            },
            {"node_id": "detect", "node_type": "detection_inference"},
            {
                "node_id": "consensus",
                "node_type": "detection_consensus",
                "parameters": {"required_votes": 1},
            },
            {"node_id": "review", "node_type": "detection_review_gate"},
        ],
        "edges": [
            {
                "edge_id": "project-images",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "images",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-model",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "model",
                "target_port_id": "project",
            },
            {
                "edge_id": "images-detect",
                "source_node_id": "images",
                "source_port_id": "images",
                "target_node_id": "detect",
                "target_port_id": "images",
            },
            {
                "edge_id": "model-detect",
                "source_node_id": "model",
                "source_port_id": "model",
                "target_node_id": "detect",
                "target_port_id": "model",
            },
            {
                "edge_id": "detect-consensus",
                "source_node_id": "detect",
                "source_port_id": "proposals",
                "target_node_id": "consensus",
                "target_port_id": "predictions",
            },
            {
                "edge_id": "consensus-review",
                "source_node_id": "consensus",
                "source_port_id": "consensus",
                "target_node_id": "review",
                "target_port_id": "proposals",
            },
        ],
    }


def _queue_seeded_review_run(client: TestClient) -> tuple[dict[str, object], str, str]:
    project = create_project(client, "Workflow review lifecycle")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project["id"],
            purpose="detector",
            display_name="Review lifecycle detector",
            source_filename="detector.pt",
            managed_path=f"projects/{project['id']}/models/detector.pt",
            sha256="a" * 64,
            file_size_bytes=10,
            framework="test",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            input_size_json={"width": 640, "height": 640},
            metadata_json={},
        )
        session.add(model)
        session.commit()
        model_id = model.id

    save = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": _review_graph(model_id)},
    )
    assert save.status_code == 201, save.text
    queued = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": save.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    run_id = str(queued.json()["id"])
    job_id = str(queued.json()["job_id"])

    consensus_payload = {
        "schema_version": "detection-consensus-0001",
        "project_id": project["id"],
        "source_ids": [model_id],
        "source_count": 1,
        "required_votes": 1,
        "iou_threshold": 0.5,
        "confidence_threshold": 0.0,
        "class_aware": True,
        "box_strategy": "mean",
        "count": 1,
        "detections": [
            {
                "consensus_id": "consensus-1",
                "image_id": "synthetic-image",
                "predicted_label": "open",
                "vote_count": 1,
                "source_ids": [model_id],
                "box": {"x_min": 1.0, "y_min": 2.0, "x_max": 10.0, "y_max": 12.0},
            }
        ],
    }
    with app.state.session_factory() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None
        nodes = {
            node.node_id: node
            for node in session.scalars(
                select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
            )
        }
        seed_review_upstream_artifacts(
            session,
            run_id=run_id,
            nodes=nodes,
            project_id=str(project["id"]),
            model_id=model_id,
            consensus_payload=consensus_payload,
        )
        session.commit()

    return project, run_id, job_id


def test_workflow_pauses_at_review_and_resumes_without_rerunning_upstream(
    client: TestClient,
) -> None:
    project, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)

    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            job_id,
        )
        is True
    )

    paused = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert paused.status_code == 200, paused.text
    paused_payload = paused.json()
    assert paused_payload["run"]["status"] == "waiting_for_review"
    review_node = next(node for node in paused_payload["nodes"] if node["node_id"] == "review")
    assert review_node["status"] == "waiting_for_review"
    assert paused_payload["run"]["result_json"]["completed_nodes"] == 5

    resumed = client.post(
        f"/api/v1/workflow-node-runs/{review_node['id']}/resume-review",
        json={"reviewed_by": "scientist", "note": "Consensus checked."},
    )
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["status"] == "queued"

    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            job_id,
        )
        is True
    )

    finished = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert finished.status_code == 200, finished.text
    finished_payload = finished.json()
    assert finished_payload["run"]["status"] == "succeeded"
    review_node = next(node for node in finished_payload["nodes"] if node["node_id"] == "review")
    assert review_node["status"] == "succeeded"
    assert review_node["result_json"]["review_approval"]["reviewed_by"] == "scientist"
    reviewed_artifact = next(
        item for item in finished_payload["artifacts"] if item["data_type"] == "reviewed_boxes"
    )
    assert reviewed_artifact["payload_json"]["consensus"] is True
    assert reviewed_artifact["payload_json"]["count"] == 1
    assert reviewed_artifact["payload_json"]["project_id"] == project["id"]


def test_waiting_for_review_workflow_can_be_cancelled(client: TestClient) -> None:
    _, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            job_id,
        )
        is True
    )

    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    detail = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert detail["run"]["status"] == "cancelled"
    review_node = next(node for node in detail["nodes"] if node["node_id"] == "review")
    assert review_node["status"] == "cancelled"


def test_invalid_review_node_identity_fails_persisted_run_instead_of_stranding_it(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        original_artifact_ids = set(
            session.scalars(
                select(WorkflowArtifact.id).where(WorkflowArtifact.workflow_run_id == run_id)
            )
        )
    assert original_artifact_ids

    def malformed_review_pause(
        _service: WorkflowExecutionService,
        **_inputs: object,
    ) -> list[WorkflowArtifactSpec]:
        raise WorkflowReviewRequired(
            "Human review requires a saved node",
            details={"node_run_id": "nonexistent-or-cross-run-review-node"},
        )

    # Execute the actual persisted review workflow. A broken adapter-supplied
    # node identity must not leave its job perpetually marked running.
    monkeypatch.setattr(WorkflowExecutionService, "execute_node", malformed_review_pause)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id) is False

    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        run = session.get(WorkflowRun, run_id)
        review_node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_id == "review",
            )
        )
        assert job is not None and job.status == "failed"
        assert run is not None and run.status == "failed"
        assert review_node is not None and review_node.status == "failed"
        assert "Workflow review pause failed" in (job.error_message or "")
        assert "active node in this run" in (run.error_message or "")
        assert review_node.error_message == job.error_message
        assert (
            set(
                session.scalars(
                    select(WorkflowArtifact.id).where(WorkflowArtifact.workflow_run_id == run_id)
                )
            )
            == original_artifact_ids
        )

    # The project-scoped persisted run remains inspectable after the failure.
    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["project_id"] == project["id"]
    assert detail.json()["run"]["status"] == "failed"


def test_review_resume_rejects_valid_artifact_from_wrong_saved_edge(
    client: TestClient,
) -> None:
    _, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id) is True

    with app.state.session_factory() as session:
        review_node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_id == "review",
            )
        )
        foreign_input = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run_id,
                WorkflowArtifact.data_type == "model_reference",
            )
        )
        assert review_node is not None and foreign_input is not None
        original_input_ids = list(review_node.input_artifact_ids_json or [])
        assert len(original_input_ids) == 1
        review_node_id = review_node.id
        # This model artifact has a valid SHA and is in the same run, but the
        # graph routes the consensus artifact to the human-review node.
        review_node.input_artifact_ids_json = [foreign_input.id]
        session.commit()

    refused = client.post(
        f"/api/v1/workflow-node-runs/{review_node_id}/resume-review",
        json={"reviewed_by": "scientist", "note": "Checked the consensus."},
    )
    assert refused.status_code == 409, refused.text
    assert "inputs do not match saved graph edges" in refused.text

    with app.state.session_factory() as session:
        run = session.get(WorkflowRun, run_id)
        job = session.get(Job, job_id)
        review_node = session.get(WorkflowNodeRun, review_node_id)
        assert run is not None and run.status == "waiting_for_review"
        assert job is not None and job.status == "waiting_for_review"
        assert review_node is not None and review_node.status == "waiting_for_review"
        assert "review_approval" not in (review_node.result_json or {})
        review_node.input_artifact_ids_json = original_input_ids
        session.commit()

    approved = client.post(
        f"/api/v1/workflow-node-runs/{review_node_id}/resume-review",
        json={"reviewed_by": "scientist", "note": "Checked the consensus."},
    )
    assert approved.status_code == 202, approved.text
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id) is True
    finished = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert finished.status_code == 200, finished.text
    assert finished.json()["run"]["status"] == "succeeded"


def test_review_resume_rejects_undeclared_and_ambiguous_same_port_outputs(
    client: TestClient,
) -> None:
    # Exercise the actual persisted paused review, not just a helper or
    # fabricated provenance map. A same-producer, same-port artifact can
    # carry a correct checksum while being absent from the saved output IDs.
    _, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id) is True

    with app.state.session_factory() as session:
        review_node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_id == "review",
            )
        )
        assert review_node is not None
        review_node_id = review_node.id
        original_input_ids = list(review_node.input_artifact_ids_json or [])
        assert len(original_input_ids) == 1
        original = session.get(WorkflowArtifact, original_input_ids[0])
        assert original is not None
        duplicate = WorkflowArtifact(
            workflow_run_id=run_id,
            producer_node_run_id=original.producer_node_run_id,
            producer_port_id=original.producer_port_id,
            data_type=original.data_type,
            payload_json=dict(original.payload_json),
            payload_sha256=original.payload_sha256,
        )
        session.add(duplicate)
        session.flush()
        duplicate_id = duplicate.id
        review_node.input_artifact_ids_json = [duplicate_id]
        session.commit()

    endpoint = f"/api/v1/workflow-node-runs/{review_node_id}/resume-review"
    approval = {"reviewed_by": "scientist", "note": "Consensus checked."}
    undeclared = client.post(endpoint, json=approval)
    assert undeclared.status_code == 409, undeclared.text
    assert "not a declared producer output" in undeclared.text

    with app.state.session_factory() as session:
        review_node = session.get(WorkflowNodeRun, review_node_id)
        assert review_node is not None
        review_node.input_artifact_ids_json = original_input_ids
        session.commit()

    ambiguous = client.post(endpoint, json=approval)
    assert ambiguous.status_code == 409, ambiguous.text
    assert "producer output is ambiguous" in ambiguous.text

    with app.state.session_factory() as session:
        run = session.get(WorkflowRun, run_id)
        job = session.get(Job, job_id)
        review_node = session.get(WorkflowNodeRun, review_node_id)
        assert run is not None and run.status == "waiting_for_review"
        assert job is not None and job.status == "waiting_for_review"
        assert review_node is not None and review_node.status == "waiting_for_review"
        assert "review_approval" not in (review_node.result_json or {})
        duplicate = session.get(WorkflowArtifact, duplicate_id)
        assert duplicate is not None
        session.delete(duplicate)
        session.commit()

    approved = client.post(endpoint, json=approval)
    assert approved.status_code == 202, approved.text
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id) is True
    finished = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert finished.status_code == 200, finished.text
    assert finished.json()["run"]["status"] == "succeeded"


def test_review_resume_rejects_post_pause_frozen_parameter_mutation(
    client: TestClient,
) -> None:
    # A persisted, completed upstream node can be modified while a human
    # reviews the output. Approval must not certify altered training/model
    # parameters that differ from the checksum-pinned workflow graph.
    _, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id) is True

    with app.state.session_factory() as session:
        nodes = {
            node.node_id: node
            for node in session.scalars(
                select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
            )
        }
        assert nodes["model"].status == "succeeded"
        assert nodes["review"].status == "waiting_for_review"
        original_parameters = dict(nodes["model"].parameters_json or {})
        assert original_parameters.get("model_id")
        review_node_id = nodes["review"].id
        nodes["model"].parameters_json = {
            **original_parameters,
            "model_id": "tampered-after-review-paused",
        }
        session.commit()

    endpoint = f"/api/v1/workflow-node-runs/{review_node_id}/resume-review"
    approval = {"reviewed_by": "scientist", "note": "I reviewed the consensus."}
    rejected = client.post(endpoint, json=approval)
    assert rejected.status_code == 409, rejected.text
    assert "node lineage does not match saved graph" in rejected.text

    with app.state.session_factory() as session:
        run = session.get(WorkflowRun, run_id)
        job = session.get(Job, job_id)
        model_node = session.get(WorkflowNodeRun, nodes["model"].id)
        review_node = session.get(WorkflowNodeRun, review_node_id)
        assert run is not None and run.status == "waiting_for_review"
        assert job is not None and job.status == "waiting_for_review"
        assert review_node is not None and review_node.status == "waiting_for_review"
        assert "review_approval" not in (review_node.result_json or {})
        assert model_node is not None
        model_node.parameters_json = original_parameters
        session.commit()

    accepted = client.post(endpoint, json=approval)
    assert accepted.status_code == 202, accepted.text
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id) is True
    finished = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert finished.status_code == 200, finished.text
    assert finished.json()["run"]["status"] == "succeeded"
