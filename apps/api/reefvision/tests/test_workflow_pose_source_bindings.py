from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import VideoAsset
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_provider_backends import _import_pose_video, _pose_model
from reefvision.tests.test_workflow_pose_review_resume_phase10 import _save_and_queue
from reefvision.tests.test_workflow_pose_training_phase10 import _frozen_dataset


def _edge(left: str, out_port: str, right: str, in_port: str) -> dict[str, str]:
    return {
        "edge_id": f"{left}-{right}-{in_port}",
        "source_node_id": left,
        "source_port_id": out_port,
        "target_node_id": right,
        "target_port_id": in_port,
    }


def test_plans_explicit_pose_dataset_and_video_pins(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, frozen = _frozen_dataset(client, monkeypatch)
    project_id = project["id"]
    video = client.get(f"/api/v1/projects/{project_id}/videos").json()[0]
    dataset = {
        "node_id": "dataset",
        "node_type": "pose_training_dataset",
        "parameters": {"dataset_id": frozen["id"], "manifest_sha256": frozen["manifest_sha256"]},
    }
    recording = {
        "node_id": "recording",
        "node_type": "project_video_source",
        "parameters": {"video_id": video["id"], "video_sha256": video["sha256"]},
    }
    graph = {
        "graph_id": "frozen-source-pins",
        "name": "Frozen source pins",
        "nodes": [{"node_id": "project", "node_type": "project_source"}, dataset, recording],
        "edges": [
            {
                "edge_id": "project-recording",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "recording",
                "target_port_id": "project",
            }
        ],
    }
    path = f"/api/v1/projects/{project_id}/workflow-graphs"
    assert client.post(f"{path}/plan", json=graph).json()["executable"]
    for source, field, expected_code in (
        (dataset, "manifest_sha256", "invalid_pose_dataset_source"),
        (recording, "video_sha256", "video_source_stale"),
    ):
        parameters = source["parameters"]
        assert isinstance(parameters, dict)
        original = parameters[field]
        parameters[field] = "0" * 64
        result = client.post(f"{path}/plan", json=graph)
        assert result.status_code == 200, result.text
        planned = result.json()
        assert planned["executable"] is False, planned
        assert any(
            issue["node_id"] == source["node_id"] and issue["code"] == expected_code
            for issue in planned["issues"]
        )
        parameters[field] = original

    # Older persisted graphs carry IDs without pins.
    dataset["parameters"] = {"dataset_id": frozen["id"]}
    recording["parameters"] = {"video_id": video["id"]}
    assert client.post(f"{path}/plan", json=graph).json()["executable"]


def test_new_guided_plan_refuses_reused_frozen_source_and_recording(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    video = client.get(f"/api/v1/projects/{project['id']}/videos").json()[0]
    video_id = video["id"]
    pin = {"dataset_id": dataset["id"], "manifest_sha256": dataset["manifest_sha256"]}
    graph = {
        "graph_id": "overlapping-frozen-source",
        "name": "Overlapping frozen source",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "training_data", "node_type": "pose_training_dataset", "parameters": pin},
            {"node_id": "validation_data", "node_type": "pose_training_dataset", "parameters": pin},
            {
                "node_id": "train",
                "node_type": "pose_model_training",
                "parameters": {"require_validation_dataset": True},
            },
            {"node_id": "register", "node_type": "register_trained_model"},
            {
                "node_id": "recording",
                "node_type": "project_video_source",
                "parameters": {"video_id": video_id, "video_sha256": video["sha256"]},
            },
            {
                "node_id": "infer",
                "node_type": "pose_inference",
                "parameters": {"require_held_out_recording": True},
            },
        ],
        "edges": [
            _edge("project", "project", "recording", "project"),
            _edge("training_data", "dataset", "train", "dataset"),
            _edge("validation_data", "dataset", "train", "validation_dataset"),
            _edge("train", "training", "register", "training"),
            _edge("register", "model", "infer", "model"),
            _edge("recording", "video", "infer", "video"),
        ],
    }
    planned = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert planned.status_code == 200, planned.text
    assert planned.json()["executable"] is False
    issues = planned.json()["issues"]
    assert any(
        issue["code"] == "invalid_frozen_pose_split" and issue["node_id"] == "train"
        for issue in issues
    )
    assert any(
        issue["code"] == "invalid_pose_held_out_recording" and issue["node_id"] == "infer"
        for issue in issues
    )


def test_pinned_pose_video_checks_original_bytes_before_provider_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Pinned pose original")
    project_id = str(project["id"])
    video = _import_pose_video(client, project_id, monkeypatch)
    app = cast(FastAPI, client.app)
    model_id = _pose_model(client, project, app, with_schema=True)
    graph = {
        "graph_id": "pose-source-bytes",
        "name": "Pinned pose source bytes",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "video",
                "node_type": "project_video_source",
                "parameters": {"video_id": video["id"], "video_sha256": video["sha256"]},
            },
            {
                "node_id": "model",
                "node_type": "registered_model_source",
                "parameters": {"model_id": model_id},
            },
            {"node_id": "pose", "node_type": "pose_inference", "parameters": {"device": "cpu"}},
        ],
        "edges": [
            _edge("project", "project", "video", "project"),
            _edge("project", "project", "model", "project"),
            _edge("video", "video", "pose", "video"),
            _edge("model", "model", "pose", "model"),
        ],
    }
    run_id, job_id = _save_and_queue(client, project_id, graph)
    with app.state.session_factory() as session:
        asset = session.get(VideoAsset, video["id"])
        assert asset is not None
        managed = resolve_managed_project_path(app.state.settings, asset.managed_path)
        managed.write_bytes(b"changed generated video")
    process_workflow_run_job(app.state.settings, app.state.session_factory, job_id)
    detail = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert detail["run"]["status"] == "failed"
    assert "Pinned video original changed" in detail["run"]["error_message"]
    assert client.get(f"/api/v1/videos/{video['id']}/tracks").json() == []
