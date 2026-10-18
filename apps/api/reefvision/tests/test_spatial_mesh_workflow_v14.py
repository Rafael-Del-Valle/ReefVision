"""Saved workflow and standalone API regression for ReefVision 1.4 mesh previews."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project

MESH = {
    "obj_text": "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n",
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Known scale bar, unreviewed",
    "relative_scale_uncertainty": 0.05,
}


def test_mesh_preview_api_is_unverified(client: TestClient) -> None:
    project = create_project(client, "Mesh preview API")
    response = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview", json=MESH
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["surface_area_m2"] == pytest.approx(0.0003)
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
    invalid = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview",
        json={**MESH, "obj_text": "v 0 0 0\nf 1 2 3"},
    )
    assert invalid.status_code == 400


def test_saved_mesh_workflow_roundtrip(client: TestClient) -> None:
    project = create_project(client, "Mesh workflow")
    project_id = str(project["id"])
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200
    node = next(
        item for item in registry.json() if item["node_type"] == "mesh_surface_preview"
    )
    assert node["executable"] is True
    assert node["output_ports"][0]["accepted_types"] == ["mesh_measurement_preview"]
    graph = {
        "graph_id": "mesh-preview-v14",
        "name": "Calibrated triangle preview",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": MESH},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph}
    )
    assert saved.status_code == 201, saved.text
    record = saved.json()
    assert record["graph_json"]["nodes"][1]["parameters"]["obj_text"] == MESH["obj_text"]
    run = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": record["id"]},
    )
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    ) is True
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"]["surface_area_m2"] == pytest.approx(0.0003)
    assert artifact["payload_json"]["project_id"] == project_id
    assert artifact["payload_json"]["measurement_status"] == "caller_supplied_unverified"
    assert len(artifact["payload_sha256"]) == 64


def test_unverified_mesh_artifact_cannot_feed_project_input(client: TestClient) -> None:
    project = create_project(client, "Mesh typing")
    graph = {
        "graph_id": "mesh-bad-edge",
        "name": "Prevent mesh preview as project",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": MESH},
            {"node_id": "images", "node_type": "project_images"},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            },
            {
                "edge_id": "bad",
                "source_node_id": "mesh",
                "source_port_id": "measurement",
                "target_node_id": "images",
                "target_port_id": "project",
            },
        ],
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/validate", json=graph
    )
    assert response.status_code == 200
    assert any(
        issue["code"] == "incompatible_port_types"
        for issue in response.json()["issues"]
    )
