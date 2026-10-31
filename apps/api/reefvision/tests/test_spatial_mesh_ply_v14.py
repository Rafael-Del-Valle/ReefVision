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


@pytest.mark.parametrize(
    "index_type",
    ["int", "uint", "uchar", "uint8", "ushort", "uint16", "short", "int16"],
)
def test_saved_ply_workflow_roundtrip(client: TestClient, index_type: str) -> None:
    ply = PLY.replace(
        "property list uchar int vertex_indices",
        f"property list uchar {index_type} vertex_indices",
    )
    params = {**MESH, "ply_text": ply}
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
                "parameters": params,
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
    assert record["graph_json"]["nodes"][1]["parameters"]["ply_text"] == ply
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
    standalone = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    assert artifact["payload_json"] == standalone.json()
    assert artifact["payload_json"]["surface_area_m2"] == pytest.approx(0.0003)
    assert artifact["payload_json"]["provenance"]["source_format"] == "ply_ascii"
    assert artifact["payload_json"]["measurement_status"] == "caller_supplied_unverified"
    assert len(artifact["payload_sha256"]) == 64


@pytest.mark.parametrize(
    ("index_type", "invalid_index"),
    [
        ("uchar", "256"),
        ("uint8", "-1"),
        ("ushort", "65536"),
        ("uint16", "65536"),
        ("short", "32768"),
        ("int8", "128"),
        ("uint32", "4294967296"),
    ],
)
def test_ply_face_indices_obey_declared_integer_bounds(
    index_type: str, invalid_index: str
) -> None:
    invalid = PLY.replace(
        "property list uchar int vertex_indices",
        f"property list uchar {index_type} vertex_indices",
    ).replace("3 0 1 2", f"3 0 1 {invalid_index}")
    with pytest.raises(ValueError, match="face index outside declared integer type bounds"):
        parse_ply_triangles(invalid)


def test_invalid_ply_face_index_fails_standalone_and_saved_workflow(
    client: TestClient,
) -> None:
    invalid = PLY.replace(
        "property list uchar int vertex_indices",
        "property list uchar uchar vertex_indices",
    ).replace("3 0 1 2", "3 0 1 256")
    params = {**MESH, "ply_text": invalid}
    project_id = str(create_project(client, "PLY face index overflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 400, standalone.text
    graph = {
        "graph_id": "ply-index-width-v14",
        "name": "Reject invalid declared PLY face index",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
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
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "mesh_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )
