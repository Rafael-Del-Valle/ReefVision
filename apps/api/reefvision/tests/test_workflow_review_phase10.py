from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    ModelRegistration,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project


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
        for node_id in ("project", "images", "model", "detect", "consensus"):
            nodes[node_id].status = "succeeded"
        artifact = WorkflowArtifact(
            workflow_run_id=run_id,
            producer_node_run_id=nodes["consensus"].id,
            producer_port_id="consensus",
            data_type="detection_consensus",
            payload_json=consensus_payload,
            payload_sha256=canonical_json_sha256(consensus_payload),
        )
        session.add(artifact)
        session.flush()
        nodes["consensus"].output_artifact_ids_json = [artifact.id]
        session.commit()

    return project, run_id, job_id


def test_workflow_pauses_at_review_and_resumes_without_rerunning_upstream(
    client: TestClient,
) -> None:
    project, run_id, job_id = _queue_seeded_review_run(client)
    app = cast(FastAPI, client.app)

    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    ) is True

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

    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    ) is True

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
    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    ) is True

    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    detail = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert detail["run"]["status"] == "cancelled"
    review_node = next(node for node in detail["nodes"] if node["node_id"] == "review")
    assert review_node["status"] == "cancelled"
