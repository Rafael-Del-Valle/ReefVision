"""Exact coincident mesh triangles must not inflate provisional coral area."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project


DUPLICATED: dict[str, Any] = {
    "vertices": [
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
    ],
    "faces": [[0, 1, 2], [3, 5, 4]],
    "meters_per_unit": 1,
    "calibration_method": "ruler",
    "calibration_evidence": "Unreviewed ruler measurement",
    "relative_scale_uncertainty": 0.1,
}


def test_direct_service_rejects_duplicate_triangle_coordinates() -> None:
    with pytest.raises(ValueError, match="Duplicate triangle geometry"):
        measure_mesh_preview(**DUPLICATED)


@pytest.mark.parametrize(
    "geometry",
    [
        {
            "vertices": DUPLICATED["vertices"],
            "faces": DUPLICATED["faces"],
        },
        {
            "obj_text": (
                "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
                "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
                "f 1 2 3\nf 4 6 5\n"
            ),
        },
    ],
    ids=["indexed-triangles", "obj-import"],
)
def test_standalone_rejects_duplicate_geometry(
    client: TestClient, geometry: dict[str, Any]
) -> None:
    project_id = str(create_project(client, "Duplicate triangle guard")["id"])
    params = {
        key: value
        for key, value in DUPLICATED.items()
        if key not in {"vertices", "faces"}
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**params, **geometry},
    )
    assert response.status_code == 400, response.text
    assert "Duplicate triangle geometry" in response.text


def test_saved_workflow_rejects_duplicate_geometry_without_artifact(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Duplicate mesh workflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    graph = {
        "graph_id": "duplicate-mesh-geometry-v14",
        "name": "Reject double-counted triangles",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": DUPLICATED,
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
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(
        f"{base}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        str(run.json()["job_id"]),
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "mesh_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )


def test_distinct_triangles_with_coincident_vertices_keep_area_and_provenance(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Distinct mesh triangles")["id"])
    params = {
        **DUPLICATED,
        "vertices": [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 0],
            [1, 0, 0],
            [0, 0, 1],
        ],
        "faces": [[0, 1, 2], [3, 4, 5]],
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json=params,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["surface_area_m2"] == pytest.approx(1.0)
    assert result["face_count"] == 2
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
    assert len(result["provenance"]["geometry_sha256"]) == 64
