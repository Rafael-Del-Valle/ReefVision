"""Saved pose Active Learning approvals must match the originally selected cohort."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

import reefvision.jobs.video_tracking as tracking_job_module
from reefvision.db.models import Job, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.pose_active_learning import PoseActiveLearningService
from reefvision.services.workflow_review import pose_active_learning_review_status
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_provider_backends import (
    _FakeCanonicalPoseVideoProvider,
    _import_pose_video,
    _pose_model,
)
from reefvision.tests.test_workflow_pose_review_resume_phase10 import _save_and_queue


def _round_payload() -> dict[str, object]:
    return {
        "schema_version": "pose-active-learning-workflow-0001",
        "project_id": "project-one",
        "video_id": "video-one",
        "round_id": "round-one",
        "status": "open",
        "selection_sha256": "a" * 64,
        "candidate_ids": ["candidate-one", "candidate-two"],
        "candidate_count": 2,
        "selected_count": 2,
        "source_track_ids": ["track-one"],
        "source_model_ids": ["model-one"],
    }


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("video", "video lineage"),
        ("selection", "selection lineage"),
        ("missing_candidate", "candidate cohort"),
        ("duplicate_candidate", "candidate cohort"),
        ("foreign_candidate", "candidate cohort"),
        ("missing_count", "candidate counts"),
        ("boolean_count", "candidate counts"),
        ("wrong_selected_count", "candidate counts"),
        ("invalid_round", "missing round_id"),
        ("foreign_project_type", "another project"),
    ],
)
def test_pose_al_standalone_review_rejects_changed_selection_evidence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    message: str,
) -> None:
    payload = _round_payload()
    if corruption == "video":
        payload["video_id"] = "video-two"
    elif corruption == "selection":
        payload["selection_sha256"] = "b" * 64
    elif corruption == "missing_candidate":
        payload["candidate_ids"] = ["candidate-one"]
    elif corruption == "duplicate_candidate":
        payload["candidate_ids"] = ["candidate-one", "candidate-one"]
    elif corruption == "foreign_candidate":
        payload["candidate_ids"] = ["candidate-one", "candidate-foreign"]
    elif corruption == "missing_count":
        payload.pop("candidate_count")
    elif corruption == "boolean_count":
        payload["candidate_count"] = True
    elif corruption == "wrong_selected_count":
        payload["selected_count"] = 1
    elif corruption == "invalid_round":
        payload["round_id"] = True
    else:
        payload["project_id"] = []

    manifest = SimpleNamespace(
        project_id="project-one",
        video_id="video-one",
        round_id="round-one",
        selection_sha256="a" * 64,
        status="complete",
        retraining_ready=True,
        candidates=[
            {"candidate_id": "candidate-one"},
            {"candidate_id": "candidate-two"},
        ],
    )
    monkeypatch.setattr(
        PoseActiveLearningService,
        "export_manifest",
        lambda _self, _round_id: manifest,
    )
    artifact = WorkflowArtifact(
        workflow_run_id="synthetic-run",
        producer_node_run_id="synthetic-producer",
        producer_port_id="round",
        data_type="pose_active_learning_round",
        payload_json=payload,
        payload_sha256=canonical_json_sha256(payload),
    )
    app = cast(FastAPI, client.app)
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match=message),
    ):
        pose_active_learning_review_status(session, artifact, project_id="project-one")


def test_pose_al_standalone_accepts_same_candidates_in_different_order(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _round_payload()
    manifest = SimpleNamespace(
        project_id="project-one",
        video_id="video-one",
        round_id="round-one",
        selection_sha256="a" * 64,
        status="complete",
        retraining_ready=True,
        selection_algorithm="pose_uncertainty",
        selection_algorithm_version="0003",
        verified_candidate_count=1,
        pending_candidate_count=0,
        skipped_candidate_count=1,
        candidates=[
            {"candidate_id": "candidate-two"},
            {"candidate_id": "candidate-one"},
        ],
    )
    monkeypatch.setattr(
        PoseActiveLearningService,
        "export_manifest",
        lambda _self, _round_id: manifest,
    )
    artifact = WorkflowArtifact(
        workflow_run_id="synthetic-run",
        producer_node_run_id="synthetic-producer",
        producer_port_id="round",
        data_type="pose_active_learning_round",
        payload_json=payload,
        payload_sha256=canonical_json_sha256(payload),
    )
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        result = pose_active_learning_review_status(
            session, artifact, project_id="project-one"
        )
    assert result["ready"] is True
    assert result["selection_sha256"] == "a" * 64
    assert result["verified_candidate_count"] == 1


def _paused_saved_pose_al_workflow(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[FastAPI, str, str, str, str]:
    project = create_project(client, "Pose AL saved cohort review")
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
            "parameters": {"requested_size": 1, "diversity_balance": False},
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
        "graph_id": "saved-pose-al-cohort-integrity-16",
        "name": "Saved pose AL cohort integrity",
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
    plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    run_id, job_id = _save_and_queue(client, project_id, graph)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, job_id
    )
    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "waiting_for_review"
    review_id = next(
        node["id"]
        for node in detail.json()["nodes"]
        if node["node_id"] == "review"
    )
    round_artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "pose_active_learning_round"
    )
    assert round_artifact["payload_json"]["candidate_count"] == 1
    for candidate_id in round_artifact["payload_json"]["candidate_ids"]:
        verified = client.put(
            f"/api/v1/pose-active-learning-candidates/{candidate_id}/review",
            json={
                "action": "verify",
                "reviewed_by": "scientist",
                "note": "Validated a biological pose before cohort approval.",
            },
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["review_status"] == "verified"
    return app, run_id, job_id, review_id, project_id


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("selection", "selection lineage"),
        ("video", "video lineage"),
        ("candidate", "candidate cohort"),
        ("count", "candidate counts"),
    ],
)
def test_saved_executable_pose_al_review_refuses_resigned_foreign_selection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    message: str,
) -> None:
    app, run_id, job_id, review_id, project_id = _paused_saved_pose_al_workflow(
        client, monkeypatch
    )
    with app.state.session_factory() as session:
        review = session.get(WorkflowNodeRun, review_id)
        assert review is not None
        artifact = session.get(WorkflowArtifact, review.input_artifact_ids_json[0])
        assert artifact is not None
        assert artifact.data_type == "pose_active_learning_round"
        payload = deepcopy(artifact.payload_json)
        assert payload["project_id"] == project_id
        if corruption == "selection":
            payload["selection_sha256"] = "f" * 64
        elif corruption == "video":
            payload["video_id"] = "foreign-video"
        elif corruption == "candidate":
            payload["candidate_ids"] = ["foreign-candidate"]
        else:
            payload["candidate_count"] = 0
        artifact.payload_json = payload
        artifact.payload_sha256 = canonical_json_sha256(payload)
        session.commit()

    refused = client.post(
        f"/api/v1/workflow-node-runs/{review_id}/resume-review",
        json={"reviewed_by": "scientist", "note": "Verify original cohort evidence."},
    )
    assert refused.status_code == 400, refused.text
    assert message in refused.json()["detail"]

    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "waiting_for_review"
    node = next(
        item for item in detail.json()["nodes"] if item["id"] == review_id
    )
    assert node["status"] == "waiting_for_review"
    assert "review_approval" not in (node["result_json"] or {})
    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "waiting_for_review"
        assert session.scalar(
            select(WorkflowNodeRun.status).where(WorkflowNodeRun.id == review_id)
        ) == "waiting_for_review"
