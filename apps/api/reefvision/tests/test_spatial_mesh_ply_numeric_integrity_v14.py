"""Scientific numeric grammar and saved-workflow parity for ASCII PLY meshes."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_ply_v14 import parse_ply_triangles
from reefvision.tests.test_annotations import create_project

PLY = (
    "ply\nformat ascii 1.0\nelement vertex 3\n"
    "property float x\nproperty float y\nproperty float z\n"
    "element face 1\nproperty list uchar int vertex_indices\n"
    "end_header\n0 0 0\n2 0 0\n0 3 0\n3 0 1 2\n"
)
PARAMS = {
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unverified field scale target",
    "relative_scale_uncertainty": 0.05,
}


def _graph(ply: str) -> dict:
    return {
        "graph_id": "ply-mesh-numeric-integrity-v14",
        "name": "Reproducible provisional PLY mesh measurement",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": {**PARAMS, "ply_text": ply},
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


def _run_saved_graph(client: TestClient, project_id: str, ply: str) -> dict:
    base = f"/api/v1/projects/{project_id}"
    saved = client.post(f"{base}/workflow-graphs", json={"graph": _graph(ply)})
    assert saved.status_code == 201, saved.text
    run = client.post(
        f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]}
    )
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    return detail.json()


@pytest.mark.parametrize(
    "invalid",
    [
        PLY.replace("element vertex 3", "element vertex 0_3"),
        PLY.replace("element vertex 3", "element vertex +3"),
        PLY.replace("2 0 0", "2_0 0 0"),
        PLY.replace("2 0 0", "1e3_0 0 0"),
        PLY.replace("2 0 0", "1e-9999 0 0"),
        PLY.replace("2 0 0", "1e9999 0 0"),
        PLY.replace("2 0 0", "２ 0 0"),
        PLY.replace("2 0 0", "2\x0b0 0"),
        PLY.replace("2 0 0", "2\x000 0"),
        PLY.replace("3 0 1 2", "3 0 1_0 2"),
    ],
)
def test_invalid_numeric_sources_fail_before_measurement(invalid: str) -> None:
    with pytest.raises(ValueError):
        parse_ply_triangles(invalid)


@pytest.mark.parametrize(
    "invalid",
    [
        PLY.replace("element vertex 3", "element vertex 0_3"),
        PLY.replace("2 0 0", "2_0 0 0"),
        PLY.replace("2 0 0", "1e-9999 0 0"),
        PLY.replace("2 0 0", "2\x0b0 0"),
        PLY.replace("3 0 1 2", "3 0 1_0 2"),
    ],
)
def test_invalid_mesh_rejected_by_api_and_persisted_workflow(
    client: TestClient, invalid: str
) -> None:
    project_id = str(create_project(client, "PLY mesh numeric rejection")["id"])
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "ply_text": invalid},
    )
    assert response.status_code in (400, 422), response.text
    detail = _run_saved_graph(client, project_id, invalid)
    assert detail["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "mesh_measurement_preview"
        for artifact in detail["artifacts"]
    )


def test_standard_decimals_and_true_zero_replay_identically(client: TestClient) -> None:
    valid = (
        PLY.replace("2 0 0", "+2. .0 0.0e-9999")
        .replace("3 0 1 2", "3 +0 1 2")
        .replace("\n", "\r\n")
    )
    vertices, faces = parse_ply_triangles(valid)
    assert vertices == [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    assert faces == [[0, 1, 2]]
    project_id = str(create_project(client, "PLY mesh valid replay")["id"])
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "ply_text": valid},
    )
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["surface_area_m2"] == pytest.approx(0.0003)
    assert expected["measurement_status"] == "caller_supplied_unverified"
    detail = _run_saved_graph(client, project_id, valid)
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        artifact
        for artifact in detail["artifacts"]
        if artifact["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64
