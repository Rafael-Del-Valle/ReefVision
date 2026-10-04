from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import reefvision.jobs.video_tracking as tracking_job_module
from reefvision.db.models import Job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_provider_backends import (
    _FakeCanonicalPoseVideoProvider,
    _import_pose_video,
    _pose_model,
)


def _tracking_job_count(
    app: FastAPI,
    project_id: str,
) -> int:
    with app.state.session_factory() as session:
        return int(
            session.scalar(
                select(func.count(Job.id)).where(
                    Job.project_id == project_id,
                    Job.job_type == "video_tracking",
                )
            )
            or 0
        )


def _save_and_queue(
    client: TestClient,
    project_id: str,
    graph: dict[str, object],
) -> tuple[str, str]:
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={
            "graph": graph,
            "create_new_revision": True,
        },
    )

    assert saved.status_code == 201, saved.text

    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={
            "graph_record_id": saved.json()["id"],
        },
    )

    assert queued.status_code == 202, queued.text

    return (
        str(queued.json()["id"]),
        str(queued.json()["job_id"]),
    )


def _review_temporal_blockers(
    client: TestClient,
    track_id: str,
) -> None:
    summary_response = client.get(f"/api/v1/video-tracks/{track_id}/pose-temporal")

    assert summary_response.status_code == 200, summary_response.text

    summary = summary_response.json()

    latest: dict[str, dict[str, object]] = {}

    for decision in summary["association_decisions"]:
        observation_id = str(decision["observation_id"])

        previous = latest.get(observation_id)

        if previous is None or int(decision["decision_revision"]) > int(
            previous["decision_revision"]
        ):
            latest[observation_id] = decision

    for observation_id, decision in latest.items():
        if decision["verification_state"] == "unreviewed" and decision["association_state"] in {
            "unresolved",
            "identity_break",
        }:
            corrected = client.post(
                (f"/api/v1/pose-landmark-observations/{observation_id}/association-corrections"),
                json={
                    "selected_landmark_track_id": None,
                    "association_state": (decision["association_state"]),
                    "reason_code": ("scientist_reviewed_workflow_identity"),
                    "note": ("Reviewed at the Phase 10 workflow pose gate."),
                },
            )

            assert corrected.status_code == 200, corrected.text

    refreshed = client.get(f"/api/v1/video-tracks/{track_id}/pose-temporal")

    assert refreshed.status_code == 200, refreshed.text

    for identity_break in refreshed.json()["identity_breaks"]:
        if identity_break["human_verified"]:
            continue

        reviewed = client.post(
            (f"/api/v1/pose-landmark-identity-breaks/{identity_break['id']}/review"),
            json={
                "reason_code": ("scientist_reviewed_workflow_break"),
                "note": ("Reviewed at the Phase 10 workflow pose gate."),
            },
        )

        assert reviewed.status_code == 200, reviewed.text


def test_phase10_pose_review_pauses_and_resumes_without_rerunning_pose(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Phase 10 pose review resume",
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
        "graph_id": "phase10-pose-review-resume",
        "name": "Phase 10 pose review resume",
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
                "node_type": "pose_temporal_association",
            },
            {
                "node_id": "review",
                "node_type": "pose_review_gate",
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
                "edge_id": "temporal-review",
                "source_node_id": "temporal",
                "source_port_id": "tracks",
                "target_node_id": "review",
                "target_port_id": "tracks",
            },
        ],
    }

    plan = client.post(
        (f"/api/v1/projects/{project['id']}/workflow-graphs/plan"),
        json=graph,
    )

    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True

    run_id, job_id = _save_and_queue(
        client,
        str(project["id"]),
        graph,
    )

    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    paused = client.get(f"/api/v1/workflow-runs/{run_id}")

    assert paused.status_code == 200, paused.text

    paused_payload = paused.json()

    assert paused_payload["run"]["status"] == "waiting_for_review"

    nodes_before = {node["node_id"]: node for node in paused_payload["nodes"]}

    assert nodes_before["pose"]["status"] == "succeeded"
    assert nodes_before["temporal"]["status"] == "succeeded"
    assert nodes_before["review"]["status"] == "waiting_for_review"

    artifacts = {item["data_type"]: item for item in paused_payload["artifacts"]}

    pose_artifact = artifacts["pose_tracks"]

    temporal_artifact = artifacts["pose_temporal_tracks"]

    tracking_jobs_before = _tracking_job_count(
        app,
        str(project["id"]),
    )

    for track_id in pose_artifact["payload_json"]["track_ids"]:
        _review_temporal_blockers(
            client,
            str(track_id),
        )

    resumed = client.post(
        (f"/api/v1/workflow-node-runs/{nodes_before['review']['id']}/resume-review"),
        json={
            "reviewed_by": "scientist",
            "note": ("Temporal pose identities reviewed."),
        },
    )

    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["status"] == "queued"

    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    finished = client.get(f"/api/v1/workflow-runs/{run_id}")

    assert finished.status_code == 200, finished.text

    final_payload = finished.json()

    assert final_payload["run"]["status"] == "succeeded"

    nodes_after = {node["node_id"]: node for node in final_payload["nodes"]}

    assert (
        nodes_after["pose"]["output_artifact_ids_json"]
        == nodes_before["pose"]["output_artifact_ids_json"]
    )

    assert (
        nodes_after["temporal"]["output_artifact_ids_json"]
        == nodes_before["temporal"]["output_artifact_ids_json"]
    )

    assert (
        _tracking_job_count(
            app,
            str(project["id"]),
        )
        == tracking_jobs_before
    )

    final_artifacts = {item["data_type"]: item for item in final_payload["artifacts"]}

    reviewed = final_artifacts["reviewed_pose_tracks"]["payload_json"]

    assert reviewed["source_temporal_artifact_id"] == temporal_artifact["id"]

    assert reviewed["truth_status"] == "scientist_reviewed"

    assert reviewed["review_readiness"]["ready"] is True


def test_phase10_active_learning_review_resume_freezes_verified_truth(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Phase 10 AL review freeze",
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
        "graph_id": "phase10-al-review-freeze",
        "name": "Phase 10 AL review freeze",
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
                "node_type": "pose_temporal_association",
            },
            {
                "node_id": "al",
                "node_type": "pose_active_learning",
                "parameters": {
                    "requested_size": 1,
                    "diversity_balance": False,
                },
            },
            {
                "node_id": "al_review",
                "node_type": ("pose_active_learning_review_gate"),
            },
            {
                "node_id": "freeze",
                "node_type": ("pose_training_dataset_freeze"),
                "parameters": {
                    "name": ("Workflow verified pose dataset"),
                },
            },
            {
                "node_id": "export",
                "node_type": "pose_training_export",
                "parameters": {
                    "format": "native",
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
                "target_node_id": "al",
                "target_port_id": "tracks",
            },
            {
                "edge_id": "al-review",
                "source_node_id": "al",
                "source_port_id": "round",
                "target_node_id": "al_review",
                "target_port_id": "round",
            },
            {
                "edge_id": "review-freeze",
                "source_node_id": "al_review",
                "source_port_id": "verified_round",
                "target_node_id": "freeze",
                "target_port_id": "verified_round",
            },
            {
                "edge_id": "freeze-export",
                "source_node_id": "freeze",
                "source_port_id": "dataset",
                "target_node_id": "export",
                "target_port_id": "dataset",
            },
        ],
    }

    plan = client.post(
        (f"/api/v1/projects/{project['id']}/workflow-graphs/plan"),
        json=graph,
    )

    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True

    run_id, job_id = _save_and_queue(
        client,
        str(project["id"]),
        graph,
    )

    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    paused = client.get(f"/api/v1/workflow-runs/{run_id}")

    assert paused.status_code == 200, paused.text

    paused_payload = paused.json()

    assert paused_payload["run"]["status"] == "waiting_for_review"

    nodes_before = {node["node_id"]: node for node in paused_payload["nodes"]}

    assert nodes_before["al_review"]["status"] == "waiting_for_review"

    artifacts = {item["data_type"]: item for item in paused_payload["artifacts"]}

    round_payload = artifacts["pose_active_learning_round"]["payload_json"]

    tracking_jobs_before = _tracking_job_count(
        app,
        str(project["id"]),
    )

    candidate_ids = list(round_payload["candidate_ids"])

    assert len(candidate_ids) == 1

    for candidate_id in candidate_ids:
        verified = client.put(
            (f"/api/v1/pose-active-learning-candidates/{candidate_id}/review"),
            json={
                "action": "verify",
                "reviewed_by": "scientist",
                "note": ("Verified for workflow retraining."),
            },
        )

        assert verified.status_code == 200, verified.text

        assert verified.json()["review_status"] == "verified"

    resumed = client.post(
        (f"/api/v1/workflow-node-runs/{nodes_before['al_review']['id']}/resume-review"),
        json={
            "reviewed_by": "scientist",
            "note": ("Active Learning round complete."),
        },
    )

    assert resumed.status_code == 202, resumed.text

    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    finished = client.get(f"/api/v1/workflow-runs/{run_id}")

    assert finished.status_code == 200, finished.text

    final_payload = finished.json()

    assert final_payload["run"]["status"] == "succeeded"

    nodes_after = {node["node_id"]: node for node in final_payload["nodes"]}

    for upstream in (
        "pose",
        "temporal",
        "al",
    ):
        assert (
            nodes_after[upstream]["output_artifact_ids_json"]
            == nodes_before[upstream]["output_artifact_ids_json"]
        )

    assert (
        _tracking_job_count(
            app,
            str(project["id"]),
        )
        == tracking_jobs_before
    )

    final_artifacts = {item["data_type"]: item for item in final_payload["artifacts"]}

    assert {
        "verified_pose_active_learning_round",
        "pose_training_dataset",
        "pose_training_package",
    }.issubset(final_artifacts)

    verified_round = final_artifacts["verified_pose_active_learning_round"]["payload_json"]

    dataset = final_artifacts["pose_training_dataset"]["payload_json"]

    package = final_artifacts["pose_training_package"]["payload_json"]

    assert verified_round["retraining_ready"] is True

    assert verified_round["verified_candidate_count"] == 1

    assert dataset["truth_policy"] == "scientist_verified_only"

    assert len(dataset["manifest_sha256"]) == 64

    assert package["export_format"] == "native"
    assert package["lossy"] is False
    assert len(package["bundle_sha256"]) == 64

    # The user-facing export name remains descriptive, while the
    # managed physical path stays compact enough for Windows.
    assert package["filename"].endswith(".reefvision-pose.zip")
    assert package["storage_filename"].startswith("pose-")

    managed_export = resolve_managed_project_path(
        app.state.settings,
        package["managed_path"],
    )

    assert managed_export.is_file()
    assert managed_export.read_bytes()
    assert managed_export.name == package["storage_filename"]
