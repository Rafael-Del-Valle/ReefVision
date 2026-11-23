"""Saved pose workflows must not approve incomplete or ambiguous temporal lineage."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

import reefvision.jobs.video_tracking as tracking_job_module
from reefvision.db.models import Job, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review import pose_temporal_review_status
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_provider_backends import (
    _FakeCanonicalPoseVideoProvider,
    _import_pose_video,
    _pose_model,
)
from reefvision.tests.test_workflow_pose_review_resume_phase10 import _save_and_queue


def _valid_temporal_payload() -> dict[str, object]:
    return {
        "schema_version": "pose-temporal-workflow-0001",
        "project_id": "project",
        "track_ids": ["track-one"],
        "count": 1,
        "builds": [
            {
                "schema_version": "pose-temporal-build-0001",
                "parent_video_track_id": "track-one",
                "source_track_revision": 1,
            }
        ],
    }


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("duplicate_tracks", "invalid or duplicate track identifiers"),
        ("blank_track", "invalid or duplicate track identifiers"),
        ("nonstring_track", "invalid or duplicate track identifiers"),
        ("missing_builds", "one saved temporal build per track"),
        ("missing_build", "one saved temporal build per track"),
        ("wrong_build_parent", "missing or ambiguous temporal build lineage"),
        ("duplicate_build_parent", "missing or ambiguous temporal build lineage"),
        ("missing_revision", "missing or ambiguous temporal build lineage"),
        ("boolean_revision", "missing or ambiguous temporal build lineage"),
        ("zero_revision", "missing or ambiguous temporal build lineage"),
        ("boolean_count", "source track count"),
        ("wrong_count", "source track count"),
    ],
)
def test_standalone_pose_review_rejects_ambiguous_track_lineage(
    client: TestClient, corruption: str, message: str
) -> None:
    payload = _valid_temporal_payload()
    tracks = cast(list[str], payload["track_ids"])
    builds = cast(list[dict[str, object]], payload["builds"])
    if corruption == "duplicate_tracks":
        tracks.append("track-one")
        payload["count"] = 2
    elif corruption == "blank_track":
        tracks[0] = ""
    elif corruption == "nonstring_track":
        tracks[0] = cast(str, 7)
    elif corruption == "missing_builds":
        payload.pop("builds")
    elif corruption == "missing_build":
        builds.clear()
    elif corruption == "wrong_build_parent":
        builds[0]["parent_video_track_id"] = "foreign-track"
    elif corruption == "duplicate_build_parent":
        tracks.append("track-two")
        payload["count"] = 2
        builds.append(dict(builds[0]))
    elif corruption == "missing_revision":
        builds[0].pop("source_track_revision")
    elif corruption == "boolean_revision":
        builds[0]["source_track_revision"] = True
    elif corruption == "zero_revision":
        builds[0]["source_track_revision"] = 0
    elif corruption == "boolean_count":
        payload["count"] = True
    elif corruption == "wrong_count":
        payload["count"] = 2

    artifact = WorkflowArtifact(
        workflow_run_id="synthetic-run",
        producer_node_run_id="synthetic-producer",
        producer_port_id="tracks",
        data_type="pose_temporal_tracks",
        payload_json=payload,
        payload_sha256=canonical_json_sha256(payload),
    )
    app = cast(FastAPI, client.app)
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match=message),
    ):
        pose_temporal_review_status(session, artifact, project_id="project")


def _paused_real_pose_workflow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[FastAPI, str, str, str, str]:
    project = create_project(client, "Pose lineage acceptance")
    video = _import_pose_video(client, str(project["id"]), monkeypatch)
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
        {"node_id": "review", "node_type": "pose_review_gate"},
    ]
    links = [
        ("project", "project", "video", "project"),
        ("project", "project", "model", "project"),
        ("video", "video", "pose", "video"),
        ("model", "model", "pose", "model"),
        ("pose", "poses", "temporal", "poses"),
        ("temporal", "tracks", "review", "tracks"),
    ]
    edges = [
        {
            "edge_id": f"{source_node}-{target_node}",
            "source_node_id": source_node,
            "source_port_id": source_port,
            "target_node_id": target_node,
            "target_port_id": target_port,
        }
        for source_node, source_port, target_node, target_port in links
    ]
    graph = {
        "graph_id": "saved-pose-temporal-lineage-16",
        "name": "Saved pose temporal lineage",
        "nodes": nodes,
        "edges": edges,
    }
    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    run_id, job_id = _save_and_queue(client, str(project["id"]), graph)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, job_id)
    response = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert response.status_code == 200, response.text
    assert response.json()["run"]["status"] == "waiting_for_review"
    review_id = next(
        item["id"] for item in response.json()["nodes"] if item["node_id"] == "review"
    )
    return app, run_id, job_id, review_id, str(project["id"])


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("missing_builds", "one saved temporal build per track"),
        ("duplicate_tracks", "invalid or duplicate track identifiers"),
        ("wrong_revision", "missing or ambiguous temporal build lineage"),
    ],
)
def test_saved_executable_pose_review_refuses_resigned_incomplete_lineage(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, corruption: str, message: str
) -> None:
    app, run_id, job_id, review_id, project_id = _paused_real_pose_workflow(
        client, monkeypatch
    )
    with app.state.session_factory() as session:
        review = session.get(WorkflowNodeRun, review_id)
        assert review is not None
        artifact = session.get(WorkflowArtifact, review.input_artifact_ids_json[0])
        assert artifact is not None
        assert artifact.data_type == "pose_temporal_tracks"
        payload = deepcopy(artifact.payload_json)
        assert payload["project_id"] == project_id
        if corruption == "missing_builds":
            payload.pop("builds")
        elif corruption == "duplicate_tracks":
            payload["track_ids"].append(payload["track_ids"][0])
            payload["count"] += 1
        else:
            payload["builds"][0]["source_track_revision"] = True
        artifact.payload_json = payload
        artifact.payload_sha256 = canonical_json_sha256(payload)
        session.commit()

    refused = client.post(
        f"/api/v1/workflow-node-runs/{review_id}/resume-review",
        json={"reviewed_by": "scientist", "note": "Science evidence verification"},
    )
    assert refused.status_code == 400, refused.text
    assert message in refused.json()["detail"]

    detail = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert detail["run"]["status"] == "waiting_for_review"
    review = next(item for item in detail["nodes"] if item["id"] == review_id)
    assert review["status"] == "waiting_for_review"
    assert "review_approval" not in (review["result_json"] or {})
    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "waiting_for_review"
        assert (
            session.scalar(select(WorkflowNodeRun.status).where(WorkflowNodeRun.id == review_id))
            == "waiting_for_review"
        )
