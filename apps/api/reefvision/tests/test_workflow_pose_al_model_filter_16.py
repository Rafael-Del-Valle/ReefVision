"""Pose Active Learning workflow model filters must never silently change cohort."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

import reefvision.jobs.video_tracking as tracking_job_module
import reefvision.services.workflow_pose as workflow_pose
from reefvision.db.models import Job, PoseActiveLearningRound, WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_provider_backends import (
    _FakeCanonicalPoseVideoProvider,
    _import_pose_video,
    _pose_model,
)
from reefvision.tests.test_workflow_pose_review_resume_phase10 import _save_and_queue


@pytest.mark.parametrize(
    "model_ids",
    [
        "model-one",
        13,
        {"id": "model-one"},
        [3],
        [False],
        [""],
        [" "],
        ["model-one", 5],
        ["model-one", "model-one"],
    ],
)
def test_pose_al_adapter_refuses_malformed_model_filter_before_scientific_reads(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    model_ids: Any,
) -> None:
    """No malformed explicit filter may fall back to automatic model discovery."""
    app = cast(FastAPI, client.app)
    payload = {"project_id": "project-one", "track_ids": ["track-one"]}
    temporal_artifact = WorkflowArtifact(
        workflow_run_id="synthetic-run",
        producer_node_run_id="synthetic-producer",
        producer_port_id="tracks",
        data_type="pose_temporal_tracks",
        payload_json=payload,
        payload_sha256=canonical_json_sha256(payload),
    )

    def no_track_reads(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Invalid acquisition model filters must fail before reading tracks")

    monkeypatch.setattr(workflow_pose, "_scoped_tracks", no_track_reads)
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="unique list of nonempty model IDs"),
    ):
        workflow_pose.execute_pose_active_learning_adapter(
            session,
            app.state.settings,
            "project-one",
            {"model_ids": model_ids},
            {"tracks": [temporal_artifact]},
        )


def test_saved_executable_pose_al_refuses_silently_dropped_model_filter(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persisted typed workflow fails before creating a misleading AL round."""
    project = create_project(client, "Pose AL model-filter integrity")
    project_id = str(project["id"])
    video = _import_pose_video(client, project_id, monkeypatch)
    app = cast(FastAPI, client.app)
    model_id = _pose_model(client, project, app, with_schema=True)
    monkeypatch.setattr(
        tracking_job_module,
        "video_tracking_provider_for_name",
        lambda _name: _FakeCanonicalPoseVideoProvider(),
    )
    nodes = [
        {"node_id": "project", "node_type": "project_source"},
        {
            "node_id": "video",
            "node_type": "project_video_source",
            "parameters": {"video_id": video["id"]},
        },
        {
            "node_id": "model",
            "node_type": "registered_model_source",
            "parameters": {"model_id": model_id},
        },
        {"node_id": "pose", "node_type": "pose_inference", "parameters": {"device": "cpu"}},
        {"node_id": "temporal", "node_type": "pose_temporal_association"},
        {
            "node_id": "al",
            "node_type": "pose_active_learning",
            "parameters": {
                "requested_size": 1,
                "diversity_balance": False,
                "model_ids": [model_id, ""],
            },
        },
        {"node_id": "review", "node_type": "pose_active_learning_review_gate"},
    ]
    links = [
        ("project", "project", "video", "project"),
        ("project", "project", "model", "project"),
        ("video", "video", "pose", "video"),
        ("model", "model", "pose", "model"),
        ("pose", "poses", "temporal", "poses"),
        ("temporal", "tracks", "al", "tracks"),
        ("al", "round", "review", "round"),
    ]
    graph = {
        "graph_id": "saved-pose-al-model-filter-integrity-16",
        "name": "Saved pose AL model-filter integrity",
        "nodes": nodes,
        "edges": [
            {
                "edge_id": f"{source_node}-{target_node}",
                "source_node_id": source_node,
                "source_port_id": source_port,
                "target_node_id": target_node,
                "target_port_id": target_port,
            }
            for source_node, source_port, target_node, target_port in links
        ],
    }
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    run_id, job_id = _save_and_queue(client, project_id, graph)
    assert not process_workflow_run_job(app.state.settings, app.state.session_factory, job_id)

    response = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["run"]["status"] == "failed"
    assert "unique list of nonempty model IDs" in (detail["run"]["error_message"] or "")
    assert any(
        node["node_id"] == "al" and node["status"] == "failed"
        for node in detail["nodes"]
    )
    assert not [
        artifact
        for artifact in detail["artifacts"]
        if artifact["data_type"] in {
            "pose_active_learning_round",
            "verified_pose_active_learning_round",
        }
    ]
    assert all("review_approval" not in (node["result_json"] or {}) for node in detail["nodes"])
    with app.state.session_factory() as session:
        assert session.scalar(
            select(PoseActiveLearningRound.id).where(
                PoseActiveLearningRound.project_id == project_id
            )
        ) is None
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "failed"
