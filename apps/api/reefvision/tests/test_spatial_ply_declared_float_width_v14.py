"""Declared ASCII PLY float widths in mesh/point standalone and saved analyses."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_ply_v14 import parse_ply_triangles
from reefvision.services.spatial_point_cloud_v14 import parse_ascii_ply_points
from reefvision.tests.test_annotations import create_project

MESH_PLY = (
    "ply\nformat ascii 1.0\nelement vertex 3\n"
    "property float x\nproperty float y\nproperty float z\n"
    "element face 1\nproperty list uchar int vertex_indices\n"
    "end_header\n0 0 0\n2 0 0\n0 3 0\n3 0 1 2\n"
)
POINT_PLY = (
    "ply\nformat ascii 1.0\nelement vertex 2\n"
    "property float x\nproperty float y\nproperty float z\n"
    "end_header\n0 0 0\n1 2 3\n"
)
PARAMS = {
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Synthetic ruler, unverified",
    "relative_scale_uncertainty": 0.05,
}


def _source(kind: str, declared: str, scalar: str) -> str:
    original = MESH_PLY if kind == "mesh" else POINT_PLY
    vertex = "2 0 0" if kind == "mesh" else "1 2 3"
    suffix = " 0 0" if kind == "mesh" else " 2 3"
    return original.replace("property float x", f"property {declared} x").replace(
        vertex, f"{scalar}{suffix}"
    )


def _graph(kind: str, params: dict) -> dict:
    node_type = "mesh_surface_preview" if kind == "mesh" else "point_cloud_preview"
    return {
        "graph_id": f"declared-ply-width-{kind}-v14",
        "name": "Declared PLY coordinate-width integrity",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": node_type, "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "m",
                "target_port_id": "project",
            }
        ],
    }


def _execute(client: TestClient, project_id: str, saved_id: str) -> dict:
    base = f"/api/v1/projects/{project_id}"
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved_id})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    return detail.json()


@pytest.mark.parametrize("kind", ["mesh", "point_cloud"])
@pytest.mark.parametrize(
    ("declared", "scalar", "accepted"),
    [
        ("float", "1e-50", False),
        ("float32", "1e40", False),
        ("float", "1e-40", True),
        ("double", "1e-50", True),
    ],
)
def test_ply_declared_float_width_across_saved_workflow(
    client: TestClient, kind: str, declared: str, scalar: str, accepted: bool
) -> None:
    ply = _source(kind, declared, scalar)
    if accepted:
        coordinates = parse_ply_triangles(ply)[0] if kind == "mesh" else parse_ascii_ply_points(ply)
        assert coordinates[1][0] > 0.0
    else:
        with pytest.raises(ValueError, match="PLY float32"):
            if kind == "mesh":
                parse_ply_triangles(ply)
            else:
                parse_ascii_ply_points(ply)

    project_id = str(create_project(client, "PLY declared coordinate width")["id"])
    base = f"/api/v1/projects/{project_id}"
    route = "mesh-preview" if kind == "mesh" else "point-cloud-preview"
    params = {**PARAMS, "ply_text": ply}
    standalone = client.post(f"{base}/spatial/{route}", json=params)
    if accepted:
        assert standalone.status_code == 200, standalone.text
        expected = standalone.json()
        size_key = "surface_area_m2" if kind == "mesh" else "axis_aligned_dimensions_m"
        if kind == "mesh":
            assert expected[size_key] > 0.0
        else:
            assert expected[size_key][0] > 0.0
        assert expected["provenance"]["calibration_verified"] is False
    else:
        assert standalone.status_code in {400, 422}, standalone.text
        assert "float32" in str(standalone.json()).lower()

    graph = _graph(kind, params)
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    artifact_type = (
        "mesh_measurement_preview" if kind == "mesh" else "point_cloud_measurement_preview"
    )
    sha_values: list[str] = []
    for _ in range(2 if accepted else 1):
        detail = _execute(client, project_id, str(saved.json()["id"]))
        matching = [entry for entry in detail["artifacts"] if entry["data_type"] == artifact_type]
        if not accepted:
            assert detail["run"]["status"] == "failed"
            assert not matching
            continue
        assert detail["run"]["status"] == "succeeded"
        assert len(matching) == 1
        assert matching[0]["payload_json"] == expected
        assert len(matching[0]["payload_sha256"]) == 64
        sha_values.append(matching[0]["payload_sha256"])
    if accepted:
        assert len(sha_values) == 2
        assert sha_values[0] == sha_values[1]
