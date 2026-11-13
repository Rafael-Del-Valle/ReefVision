from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

import reefvision.jobs.video_tracking as tracking_job_module
from reefvision.db.models import Job, ModelRegistration, PoseLandmarkSchemaRevision
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.pose_schemas import definition_for_revision
from reefvision.services.workflow_pose import POSE_WORKFLOW_RUNTIME_NODE_TYPES
from reefvision.services.workflow_review import REVIEW_GATE_NODE_TYPES
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_provider_backends import (
    _FakeCanonicalPoseVideoProvider,
    _import_pose_video,
    _pose_model,
)

PHASE5_NODES = {
    "anatomical_measurement",
    "biological_event_detection",
    "biological_event_review_gate",
    "biological_movement_export",
}


def test_phase5_nodes_are_typed_executable_and_reviewable(client: TestClient) -> None:
    response = client.get("/api/v1/workflow-graphs/node-registry")
    assert response.status_code == 200, response.text
    registry = {item["node_type"]: item for item in response.json()}
    assert registry.keys() >= PHASE5_NODES
    assert POSE_WORKFLOW_RUNTIME_NODE_TYPES >= PHASE5_NODES
    assert "biological_event_review_gate" in REVIEW_GATE_NODE_TYPES
    assert registry["anatomical_measurement"]["input_ports"][0]["accepted_types"] == [
        "reviewed_pose_identity_tracks"
    ]
    assert registry["anatomical_measurement"]["output_ports"][0]["accepted_types"] == [
        "pose_measurement_series"
    ]
    assert registry["biological_event_detection"]["output_ports"][0]["accepted_types"] == [
        "pose_event_candidates"
    ]
    assert registry["biological_event_review_gate"]["output_ports"][0]["accepted_types"] == [
        "reviewed_pose_events"
    ]
    assert registry["biological_movement_export"]["output_ports"][0]["accepted_types"] == [
        "biological_movement_package"
    ]
    assert all(registry[node]["executable"] for node in PHASE5_NODES)


def test_phase5_graph_rejects_unreviewed_identity_input(client: TestClient) -> None:
    graph = {
        "graph_id": "phase5-type-safety",
        "name": "Phase 5 type safety",
        "nodes": [
            {"node_id": "associate", "node_type": "pose_identity_association"},
            {
                "node_id": "measure",
                "node_type": "anatomical_measurement",
                "parameters": {
                    "definitions": [
                        {
                            "id": "gape",
                            "name": "Gape",
                            "kind": "distance",
                            "landmark_ids": ["upper", "lower"],
                        }
                    ]
                },
            },
        ],
        "edges": [
            {
                "edge_id": "unsafe",
                "source_node_id": "associate",
                "source_port_id": "tracks",
                "target_node_id": "measure",
                "target_port_id": "tracks",
            }
        ],
    }
    response = client.post("/api/v1/projects/missing/workflow-graphs/validate", json=graph)
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is False
    assert any(issue["code"] == "incompatible_port_types" for issue in response.json()["issues"])


def test_saved_phase5_workflow_executes_jobs_review_and_export(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Phase 5 workflow runtime")
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
        model.class_map_json = {
            "labels": ["jellyfish"],
            "mapping": {"jellyfish": str(project["label_classes"][0]["id"])},
        }
        schema = dict((model.metadata_json or {})["pose_landmark_schema"])
        revision = session.scalar(
            select(PoseLandmarkSchemaRevision).where(
                PoseLandmarkSchemaRevision.schema_id == schema["schema_id"],
                PoseLandmarkSchemaRevision.revision == schema["schema_revision"],
            )
        )
        assert revision is not None
        landmarks = definition_for_revision(revision)["landmarks"]
        measurement_landmark_ids = [landmarks[0]["id"], landmarks[1]["id"]]
        session.commit()

    graph = {
        "graph_id": "phase5-runtime",
        "name": "Phase 5 runtime",
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
            {"node_id": "pose", "node_type": "pose_inference", "parameters": {"device": "cpu"}},
            {"node_id": "associate", "node_type": "pose_identity_association"},
            {"node_id": "identity_review", "node_type": "pose_identity_review_gate"},
            {
                "node_id": "measure",
                "node_type": "anatomical_measurement",
                "parameters": {
                    "definitions": [
                        {
                            "id": "bell-tentacle",
                            "name": "Bell to tentacle",
                            "kind": "distance",
                            "landmark_ids": measurement_landmark_ids,
                        }
                    ]
                },
            },
            {
                "node_id": "detect",
                "node_type": "biological_event_detection",
                "parameters": {
                    "cycles": [
                        {
                            "measurement_definition_id": "bell-tentacle",
                            "open_threshold": 0.1,
                            "close_threshold": 0,
                        }
                    ]
                },
            },
            {"node_id": "event_review", "node_type": "biological_event_review_gate"},
            {
                "node_id": "export",
                "node_type": "biological_movement_export",
                "parameters": {"format": "json"},
            },
        ],
        "edges": [
            {
                "edge_id": "p-v",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "video",
                "target_port_id": "project",
            },
            {
                "edge_id": "p-m",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "model",
                "target_port_id": "project",
            },
            {
                "edge_id": "v-p",
                "source_node_id": "video",
                "source_port_id": "video",
                "target_node_id": "pose",
                "target_port_id": "video",
            },
            {
                "edge_id": "m-p",
                "source_node_id": "model",
                "source_port_id": "model",
                "target_node_id": "pose",
                "target_port_id": "model",
            },
            {
                "edge_id": "p-a",
                "source_node_id": "pose",
                "source_port_id": "poses",
                "target_node_id": "associate",
                "target_port_id": "poses",
            },
            {
                "edge_id": "a-r",
                "source_node_id": "associate",
                "source_port_id": "tracks",
                "target_node_id": "identity_review",
                "target_port_id": "tracks",
            },
            {
                "edge_id": "r-m",
                "source_node_id": "identity_review",
                "source_port_id": "tracks",
                "target_node_id": "measure",
                "target_port_id": "tracks",
            },
            {
                "edge_id": "m-d",
                "source_node_id": "measure",
                "source_port_id": "measurements",
                "target_node_id": "detect",
                "target_port_id": "measurements",
            },
            {
                "edge_id": "d-r",
                "source_node_id": "detect",
                "source_port_id": "events",
                "target_node_id": "event_review",
                "target_port_id": "events",
            },
            {
                "edge_id": "r-e",
                "source_node_id": "event_review",
                "source_port_id": "events",
                "target_node_id": "export",
                "target_port_id": "events",
            },
        ],
    }
    saved = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
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
    identities = client.get(
        f"/api/v1/pose-identity-runs/{identity_payload['run_id']}/identities"
    ).json()
    for identity in identities:
        response = client.post(
            f"/api/v1/pose-identity-runs/{identity_payload['run_id']}/corrections",
            json={
                "action": "accept",
                "target_type": "identity",
                "target_id": identity["id"],
                "actor": "phase5-workflow-test",
            },
        )
        assert response.status_code == 201, response.text
    nodes = {item["node_id"]: item for item in paused["nodes"]}
    resumed = client.post(
        f"/api/v1/workflow-node-runs/{nodes['identity_review']['id']}/resume-review",
        json={"reviewed_by": "phase5-workflow-test"},
    )
    assert resumed.status_code == 202, resumed.text
    resumed_execution = process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    resumed_detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json()
    assert resumed_execution, (
        resumed_detail["run"],
        [
            (node["node_id"], node["status"], node["error_message"])
            for node in resumed_detail["nodes"]
        ],
    )
    event_pause = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json()
    assert event_pause["run"]["status"] == "waiting_for_review"
    artifacts = {item["data_type"]: item for item in event_pause["artifacts"]}
    event_payload = artifacts["pose_event_candidates"]["payload_json"]
    measurement_payload = artifacts["pose_measurement_series"]["payload_json"]
    measured_samples = client.get(
        f"/api/v1/pose-measurement-series/{measurement_payload['series'][0]['id']}/samples"
    ).json()
    source_observations = client.get(
        f"/api/v1/pose-identity-runs/{identity_payload['run_id']}/observations"
    ).json()
    events = client.get(f"/api/v1/pose-event-runs/{event_payload['event_run_id']}/events").json()
    assert len(events) == 1 and events[0]["cycle_state"] == "partial_start", (
        measured_samples,
        source_observations[0]["landmarks_json"],
        measurement_landmark_ids,
    )
    rejected = client.post(
        f"/api/v1/pose-biological-events/{events[0]['id']}/corrections",
        json={
            "action": "reject",
            "reason": "Synthetic partial is not a confirmed observation",
            "actor": "phase5-workflow-test",
        },
    )
    assert rejected.status_code == 201, rejected.text
    nodes = {item["node_id"]: item for item in event_pause["nodes"]}
    resumed = client.post(
        f"/api/v1/workflow-node-runs/{nodes['event_review']['id']}/resume-review",
        json={"reviewed_by": "phase5-workflow-test"},
    )
    assert resumed.status_code == 202, resumed.text
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    finished = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json()
    assert finished["run"]["status"] == "succeeded"
    artifacts = {item["data_type"]: item for item in finished["artifacts"]}
    package = artifacts["biological_movement_package"]["payload_json"]
    assert package["truth_status"] == "scientist_reviewed"
    assert resolve_managed_project_path(app.state.settings, package["managed_path"]).is_file()
    with app.state.session_factory() as session:
        measurement_job = session.get(
            Job, artifacts["pose_measurement_series"]["payload_json"]["measurement_job_id"]
        )
        assert measurement_job is not None
        assert measurement_job.request_json["workflow_run_id"] == queued.json()["id"]
