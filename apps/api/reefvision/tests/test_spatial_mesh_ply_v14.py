"""ASCII PLY preview parser, API and saved Workflow Builder integration tests."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_ply_v14 import parse_ply_triangles
from reefvision.tests.test_annotations import create_project

PLY = (
    "ply\nformat ascii 1.0\ncomment reordered XYZ properties\n"
    "element vertex 3\nproperty uchar red\nproperty float z\n"
    "property float x\nproperty float y\nelement face 1\n"
    "property list uchar int vertex_indices\nend_header\n"
    "255 0 0 0\n255 0 2 0\n255 0 0 3\n3 0 1 2\n"
)
MESH = {
    "ply_text": PLY,
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Control target, awaiting scientist verification",
    "relative_scale_uncertainty": 0.05,
}


def test_ascii_ply_with_reordered_xyz_and_extra_scalar_property() -> None:
    vertices, faces = parse_ply_triangles(PLY)
    assert vertices == [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    assert faces == [[0, 1, 2]]


@pytest.mark.parametrize(
    "invalid",
    [
        PLY.replace("ascii", "binary_little_endian"),
        PLY.replace("3 0 1 2", "4 0 1 2 2"),
        PLY.replace("3 0 1 2", "3 0 1 3"),
        PLY.replace("3 0 1 2", "3 0 1 -1"),
        PLY.replace("3 0 1 2", "3 0 1 2\n3 0 1 2"),
        PLY.replace("255 0 0 0", "255 nan 0 0"),
        PLY.replace("255 0 0 0", "255.5 0 0 0"),
        PLY.replace("255 0 0 0", "256 0 0 0"),
        PLY.replace("255 0 0 0", "-1 0 0 0"),
        PLY.replace("property float x", "property int x").replace("255 0 2 0", "255 0 2.5 0"),
        PLY.replace("property float x", "property list uchar int x"),
        PLY.replace("element face 1", "element edge 1"),
        "ply\nformat ascii 1.0\nend_header",
        PLY + ("x" * 256_001),
    ],
)
def test_rejects_unsupported_or_malformed_ply(invalid: str) -> None:
    with pytest.raises(ValueError):
        parse_ply_triangles(invalid)


def test_ply_standalone_api(client: TestClient) -> None:
    project = create_project(client, "PLY preview API")
    url = f"/api/v1/projects/{project['id']}/spatial/mesh-preview"
    response = client.post(url, json=MESH)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["surface_area_m2"] == pytest.approx(0.0003)
    assert result["provenance"]["source_format"] == "ply_ascii"
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert client.post(url, json={**MESH, "obj_text": "v 0 0 0"}).status_code == 422


def test_saved_ply_workflow_roundtrip(client: TestClient) -> None:
    project = create_project(client, "PLY workflow")
    project_id = str(project["id"])
    graph = {
        "graph_id": "ply-preview-v14",
        "name": "Unverified ASCII PLY preview",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": MESH,
            },
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
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    record = saved.json()
    assert record["graph_json"]["nodes"][1]["parameters"]["ply_text"] == PLY
    run = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": record["id"]},
    )
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"]["surface_area_m2"] == pytest.approx(0.0003)
    assert artifact["payload_json"]["provenance"]["source_format"] == "ply_ascii"
    assert artifact["payload_json"]["measurement_status"] == "caller_supplied_unverified"
    assert len(artifact["payload_sha256"]) == 64
