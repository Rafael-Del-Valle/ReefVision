from __future__ import annotations

import hashlib
import json
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.video_tracking as tracking_job_module
from reefvision.db.models import Job, ModelRegistration, WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_pose import execute_pose_identity_export_adapter
from reefvision.services.workflow_review import REVIEW_GATE_NODE_TYPES
from reefvision.services.workflow_runtime_adapters import RUNTIME_ADAPTER_NODE_TYPES
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_provider_backends import (
    _FakeCanonicalPoseVideoProvider,
    _import_pose_video,
    _pose_model,
)

PHASE4_NODES = {
    "pose_identity_association",
    "pose_identity_review_gate",
    "pose_identity_evaluation",
    "pose_identity_export",
}


def test_phase4_identity_nodes_are_typed_executable_and_reviewable(client: TestClient) -> None:
    response = client.get("/api/v1/workflow-graphs/node-registry")
    assert response.status_code == 200, response.text
    registry = {item["node_type"]: item for item in response.json()}

    assert registry.keys() >= PHASE4_NODES
    assert PHASE4_NODES <= RUNTIME_ADAPTER_NODE_TYPES
    assert "pose_identity_review_gate" in REVIEW_GATE_NODE_TYPES
    assert registry["pose_identity_association"]["input_ports"][0]["accepted_types"] == [
        "pose_tracks"
    ]
    assert registry["pose_identity_association"]["output_ports"][0]["accepted_types"] == [
        "pose_identity_tracks"
    ]
    assert registry["pose_identity_review_gate"]["output_ports"][0]["accepted_types"] == [
        "reviewed_pose_identity_tracks"
    ]
    assert registry["pose_identity_evaluation"]["required_parameters"] == ["truth_dataset_id"]
    assert registry["pose_identity_export"]["output_ports"][0]["accepted_types"] == [
        "pose_identity_package"
    ]
    assert all(registry[node]["executable"] for node in PHASE4_NODES)


def test_phase4_evaluation_rejects_unreviewed_identity_artifacts(client: TestClient) -> None:
    project = create_project(client, "Phase 4 identity type safety")
    graph = {
        "graph_id": "phase4-identity-type-safety",
        "name": "Phase 4 identity type safety",
        "nodes": [
            {"node_id": "associate", "node_type": "pose_identity_association"},
            {
                "node_id": "evaluate",
                "node_type": "pose_identity_evaluation",
                "parameters": {"truth_dataset_id": "truth"},
            },
        ],
        "edges": [
            {
                "edge_id": "unreviewed-evaluate",
                "source_node_id": "associate",
                "source_port_id": "tracks",
                "target_node_id": "evaluate",
                "target_port_id": "tracks",
            }
        ],
    }
    response = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/validate", json=graph)
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is False
    assert any(item["code"] == "incompatible_port_types" for item in response.json()["issues"])


def test_phase4_saved_workflow_executes_review_evaluation_export_and_replay(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Phase 4 identity workflow runtime")
    video = _import_pose_video(client, str(project["id"]), monkeypatch)
    app = cast(FastAPI, client.app)
    model_id = _pose_model(client, project, app, with_schema=True)
    monkeypatch.setattr(
        tracking_job_module,
        "video_tracking_provider_for_name",
        lambda _name: _FakeCanonicalPoseVideoProvider(),
    )
    with app.state.session_factory() as session:
        model = session.get(ModelRegistration, model_id)
        assert model is not None
        schema = dict((model.metadata_json or {})["pose_landmark_schema"])

    truth = client.post(
        f"/api/v1/projects/{project['id']}/pose-identity-truth-datasets",
        json={
            "name": "Phase 4 workflow synthetic truth",
            "video_id": video["id"],
            "pose_schema_id": schema["schema_id"],
            "pose_schema_revision": schema["schema_revision"],
            "pose_schema_content_hash": schema["content_hash"],
            "scientific_context": "synthetic_engineering",
            "verified_by": "workflow-fixture",
            "observations": [
                {"identity_id": "truth-jelly", "frame_index": 0, "bbox": [10, 10, 40, 30]},
                {"identity_id": "truth-jelly", "frame_index": 1, "bbox": [11, 10, 40, 30]},
            ],
        },
    )
    assert truth.status_code == 201, truth.text
    graph = {
        "graph_id": "phase4-identity-runtime",
        "name": "Phase 4 identity runtime",
        "nodes": [
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
            {
                "node_id": "pose",
                "node_type": "pose_inference",
                "parameters": {"device": "cpu"},
            },
            {
                "node_id": "associate",
                "node_type": "pose_identity_association",
                "parameters": {
                    "max_normalized_distance": 4.0,
                    "acceptance_threshold": 2.0,
                },
            },
            {"node_id": "review", "node_type": "pose_identity_review_gate"},
            {
                "node_id": "evaluate",
                "node_type": "pose_identity_evaluation",
                "parameters": {"truth_dataset_id": truth.json()["id"]},
            },
            {
                "node_id": "export",
                "node_type": "pose_identity_export",
                "parameters": {"format": "json"},
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
                "edge_id": "pose-associate",
                "source_node_id": "pose",
                "source_port_id": "poses",
                "target_node_id": "associate",
                "target_port_id": "poses",
            },
            {
                "edge_id": "associate-review",
                "source_node_id": "associate",
                "source_port_id": "tracks",
                "target_node_id": "review",
                "target_port_id": "tracks",
            },
            {
                "edge_id": "review-evaluate",
                "source_node_id": "review",
                "source_port_id": "tracks",
                "target_node_id": "evaluate",
                "target_port_id": "tracks",
            },
            {
                "edge_id": "evaluate-export",
                "source_node_id": "evaluate",
                "source_port_id": "evaluation",
                "target_node_id": "export",
                "target_port_id": "evaluation",
            },
        ],
    }
    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True and plan.json()["executable"] is True
    saved = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text

    def execute_saved_workflow() -> dict[str, object]:
        queued = client.post(
            f"/api/v1/projects/{project['id']}/workflow-runs",
            json={"graph_record_id": saved.json()["id"]},
        )
        assert queued.status_code == 202, queued.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        paused = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json()
        assert paused["run"]["status"] == "waiting_for_review"
        artifacts = {item["data_type"]: item for item in paused["artifacts"]}
        identity_payload = artifacts["pose_identity_tracks"]["payload_json"]
        with app.state.session_factory() as session:
            child = session.get(Job, identity_payload["association_job_id"])
            assert child is not None
            assert child.request_json["workflow_run_id"] == queued.json()["id"]
        identities = client.get(
            f"/api/v1/pose-identity-runs/{identity_payload['run_id']}/identities"
        ).json()
        for identity in identities:
            accepted = client.post(
                f"/api/v1/pose-identity-runs/{identity_payload['run_id']}/corrections",
                json={
                    "action": "accept",
                    "target_type": "identity",
                    "target_id": identity["id"],
                    "actor": "workflow-scientist",
                },
            )
            assert accepted.status_code == 201, accepted.text
        nodes = {item["node_id"]: item for item in paused["nodes"]}
        resumed = client.post(
            f"/api/v1/workflow-node-runs/{nodes['review']['id']}/resume-review",
            json={"reviewed_by": "workflow-scientist", "note": "Identity audit complete"},
        )
        assert resumed.status_code == 202, resumed.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        finished = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json()
        assert finished["run"]["status"] == "succeeded"
        return finished

    first = execute_saved_workflow()
    first_artifacts = {item["data_type"]: item for item in first["artifacts"]}
    assert first_artifacts["pose_identity_evaluation"]["payload_json"]["metrics"]["id_f1"] == 1.0
    package = first_artifacts["pose_identity_package"]["payload_json"]
    assert package["evaluation_result_sha256"]
    package_path = resolve_managed_project_path(app.state.settings, package["managed_path"])
    assert package_path.is_file()
    assert package["content_sha256"] == hashlib.sha256(package_path.read_bytes()).hexdigest()
    exported_json = json.loads(package_path.read_text(encoding="utf-8"))
    assert exported_json["schema_version"] == "pose-identity-evaluated-export-0001"
    assert exported_json["evaluation"]["result_sha256"] == package["evaluation_result_sha256"]
    assert exported_json["identity_results"]["association_run"]["id"] == package["run_id"]

    evaluation_artifact_id = first_artifacts["pose_identity_evaluation"]["id"]
    identities = client.get(f"/api/v1/pose-identity-runs/{package['run_id']}/identities").json()
    revised = client.post(
        f"/api/v1/pose-identity-runs/{package['run_id']}/corrections",
        json={
            "action": "accept",
            "target_type": "identity",
            "target_id": identities[0]["id"],
            "actor": "post-evaluation-reviewer",
        },
    )
    assert revised.status_code == 201, revised.text
    with app.state.session_factory() as session:
        evaluation_artifact = session.get(WorkflowArtifact, evaluation_artifact_id)
        assert evaluation_artifact is not None
        with pytest.raises(ValidationError, match="evaluation is stale"):
            execute_pose_identity_export_adapter(
                session,
                app.state.settings,
                str(project["id"]),
                {"format": "json"},
                {"evaluation": [evaluation_artifact]},
            )

    replay = execute_saved_workflow()
    replay_artifacts = {item["data_type"]: item for item in replay["artifacts"]}
    assert replay_artifacts["pose_identity_evaluation"]["payload_json"]["metrics"]["id_f1"] == 1.0
