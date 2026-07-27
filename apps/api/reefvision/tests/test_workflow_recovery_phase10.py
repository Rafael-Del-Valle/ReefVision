from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, WorkflowArtifact, WorkflowRun
from reefvision.tests.test_annotations import create_project


def _workflow_payload() -> dict[str, object]:
    return {
        "name": "Recoverable workflow",
        "nodes": [
            {"id": "images", "node_type": "image_input", "configuration": {}},
            {"id": "filter", "node_type": "filter", "configuration": {}},
            {"id": "export", "node_type": "export", "configuration": {}},
        ],
        "edges": [
            {
                "source_node_id": "images",
                "source_port": "images",
                "target_node_id": "filter",
                "target_port": "artifact",
            },
            {
                "source_node_id": "filter",
                "source_port": "artifact",
                "target_node_id": "export",
                "target_port": "artifact",
            },
        ],
    }


def _create_run(client: TestClient) -> tuple[str, str]:
    project = create_project(client, "Workflow recovery")
    project_id = str(project["id"])
    workflow = client.post(
        f"/api/v1/projects/{project_id}/workflows",
        json={
            "name": "Recoverable workflow",
            "workflow": _workflow_payload(),
        },
    )
    assert workflow.status_code == 201, workflow.text
    workflow_id = str(workflow.json()["workflow"]["id"])
    queued = client.post(
        f"/api/v1/workflows/{workflow_id}/runs",
        json={"inputs": {"image_ids": ["image-1"]}, "use_cache": True},
    )
    assert queued.status_code == 202, queued.text
    return workflow_id, str(queued.json()["run"]["id"])


def test_failed_workflow_retry_reuses_only_successful_upstream_artifacts(
    client: TestClient,
) -> None:
    workflow_id, source_run_id = _create_run(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        source = session.get(WorkflowRun, source_run_id)
        assert source is not None
        source.status = "failed"
        source.stage = "failed"
        source.current_node_id = "filter"
        source.error_message = "Synthetic filter failure"
        source.node_state_json = {
            "images": {"status": "succeeded", "artifact_ids": ["source-images"]},
            "filter": {"status": "failed", "error": "Synthetic filter failure"},
            "export": {"status": "queued"},
        }
        job = session.get(Job, source.job_id)
        assert job is not None
        job.status = "failed"
        session.add(
            WorkflowArtifact(
                workflow_run_id=source.id,
                node_id="images",
                port_name="images",
                artifact_type="images",
                checksum="a" * 64,
                payload_json={"image_ids": ["image-1"]},
                managed_path=None,
                size_bytes=None,
            )
        )
        session.commit()

    retried = client.post(
        f"/api/v1/workflow-runs/{source_run_id}/retry",
        json={},
    )
    assert retried.status_code == 202, retried.text
    run = retried.json()["run"]
    assert run["id"] != source_run_id
    assert run["workflow_id"] == workflow_id
    assert run["result_json"]["retry_of_run_id"] == source_run_id
    assert run["result_json"]["rerun_from_node_id"] == "filter"
    assert run["node_state_json"]["images"]["status"] == "succeeded"
    assert run["node_state_json"]["filter"] == {"status": "queued"}
    assert run["node_state_json"]["export"] == {"status": "queued"}

    artifacts = client.get(f"/api/v1/workflow-runs/{run['id']}/artifacts")
    assert artifacts.status_code == 200, artifacts.text
    assert len(artifacts.json()) == 1
    copied = artifacts.json()[0]
    assert copied["node_id"] == "images"
    assert copied["payload_json"]["_reused_from_workflow_run_id"] == source_run_id


def test_successful_run_requires_an_explicit_partial_rerun_node(
    client: TestClient,
) -> None:
    _, source_run_id = _create_run(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        source = session.get(WorkflowRun, source_run_id)
        assert source is not None
        source.status = "succeeded"
        source.stage = "completed"
        source.node_state_json = {
            "images": {"status": "succeeded"},
            "filter": {"status": "succeeded"},
            "export": {"status": "succeeded"},
        }
        job = session.get(Job, source.job_id)
        assert job is not None
        job.status = "succeeded"
        for node_id, port_name, artifact_type in (
            ("images", "images", "images"),
            ("filter", "artifact", "images"),
        ):
            session.add(
                WorkflowArtifact(
                    workflow_run_id=source.id,
                    node_id=node_id,
                    port_name=port_name,
                    artifact_type=artifact_type,
                    checksum=("b" if node_id == "images" else "c") * 64,
                    payload_json={"image_ids": ["image-1"]},
                )
            )
        session.commit()

    missing_node = client.post(
        f"/api/v1/workflow-runs/{source_run_id}/retry",
        json={},
    )
    assert missing_node.status_code == 400, missing_node.text
    assert "choose a node" in missing_node.text.lower()

    partial = client.post(
        f"/api/v1/workflow-runs/{source_run_id}/retry",
        json={"from_node_id": "export", "use_cache": False},
    )
    assert partial.status_code == 202, partial.text
    run = partial.json()["run"]
    assert run["result_json"]["rerun_from_node_id"] == "export"
    assert run["result_json"]["use_cache"] is False
    assert run["node_state_json"]["images"]["status"] == "succeeded"
    assert run["node_state_json"]["filter"]["status"] == "succeeded"
    assert run["node_state_json"]["export"] == {"status": "queued"}
