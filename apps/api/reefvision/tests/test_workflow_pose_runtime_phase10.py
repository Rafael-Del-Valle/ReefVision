from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.video_tracking as tracking_job_module
from reefvision.db.models import Job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_provider_backends import (
    _FakeCanonicalPoseVideoProvider,
    _import_pose_video,
    _pose_model,
)


def test_phase10_pose_workflow_executes_production_pose_temporal_and_al(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Phase 10 pose runtime",
    )

    video = _import_pose_video(
        client,
        str(project["id"]),
        monkeypatch,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    model_id = _pose_model(
        client,
        project,
        app,
        with_schema=True,
    )

    monkeypatch.setattr(
        tracking_job_module,
        "video_tracking_provider_for_name",
        lambda _name: _FakeCanonicalPoseVideoProvider(),
    )

    graph = {
        "graph_id": "phase10-pose-runtime",
        "name": "Phase 10 pose runtime",
        "nodes": [
            {
                "node_id": "project",
                "node_type": "project_source",
            },
            {
                "node_id": "video",
                "node_type": "project_video_source",
                "parameters": {
                    "video_id": video["id"],
                },
            },
            {
                "node_id": "model",
                "node_type": "registered_model_source",
                "parameters": {
                    "model_id": model_id,
                },
            },
            {
                "node_id": "pose",
                "node_type": "pose_inference",
                "parameters": {
                    "device": "cpu",
                },
            },
            {
                "node_id": "temporal",
                "node_type": ("pose_temporal_association"),
            },
            {
                "node_id": "active_learning",
                "node_type": "pose_active_learning",
                "parameters": {
                    "requested_size": 1,
                    "diversity_balance": False,
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-video",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "video",
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
                "edge_id": "video-pose",
                "source_node_id": "video",
                "source_port_id": "video",
                "target_node_id": "pose",
                "target_port_id": "video",
            },
            {
                "edge_id": "model-pose",
                "source_node_id": "model",
                "source_port_id": "model",
                "target_node_id": "pose",
                "target_port_id": "model",
            },
            {
                "edge_id": "pose-temporal",
                "source_node_id": "pose",
                "source_port_id": "poses",
                "target_node_id": "temporal",
                "target_port_id": "poses",
            },
            {
                "edge_id": "temporal-al",
                "source_node_id": "temporal",
                "source_port_id": "tracks",
                "target_node_id": "active_learning",
                "target_port_id": "tracks",
            },
        ],
    }

    plan = client.post(
        (f"/api/v1/projects/{project['id']}/workflow-graphs/plan"),
        json=graph,
    )

    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True
    assert plan.json()["execution_blocker"] is None

    saved = client.post(
        (f"/api/v1/projects/{project['id']}/workflow-graphs"),
        json={
            "graph": graph,
            "create_new_revision": True,
        },
    )

    assert saved.status_code == 201, saved.text

    queued = client.post(
        (f"/api/v1/projects/{project['id']}/workflow-runs"),
        json={
            "graph_record_id": saved.json()["id"],
        },
    )

    assert queued.status_code == 202, queued.text

    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is True
    )

    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")

    assert detail.status_code == 200, detail.text

    payload = detail.json()

    assert payload["run"]["status"] == "succeeded"

    artifacts = {item["data_type"]: item for item in payload["artifacts"]}

    assert {
        "pose_tracks",
        "pose_temporal_tracks",
        "pose_active_learning_round",
    }.issubset(artifacts)

    pose_payload = artifacts["pose_tracks"]["payload_json"]

    temporal_payload = artifacts["pose_temporal_tracks"]["payload_json"]

    al_payload = artifacts["pose_active_learning_round"]["payload_json"]

    assert pose_payload["count"] == 1
    assert len(pose_payload["track_ids"]) == 1

    assert temporal_payload["track_ids"] == (pose_payload["track_ids"])

    assert temporal_payload["builds"][0]["created_observations"] > 0

    assert al_payload["candidate_count"] == 1
    assert al_payload["status"] == "open"

    with app.state.session_factory() as session:
        child_job = session.get(
            Job,
            pose_payload["tracking_job_id"],
        )

        assert child_job is not None
        assert child_job.request_json["build_pose_temporal_associations"] is False

    temporal = client.get(f"/api/v1/video-tracks/{pose_payload['track_ids'][0]}/pose-temporal")

    assert temporal.status_code == 200, temporal.text
    assert len(temporal.json()["observations"]) > 0
