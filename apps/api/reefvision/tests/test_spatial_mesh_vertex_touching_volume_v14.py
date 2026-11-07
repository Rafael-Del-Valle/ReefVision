"""Vertex-touching closed patches must not imply a single enclosed surface."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

TETRA_FACES = [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]
TETRA_VERTICES = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]


@pytest.mark.parametrize("case", ["shared-index", "coincident-coordinate", "disjoint"])
def test_closed_patch_union_volume_standalone_and_saved_workflow(
    client: TestClient, case: str
) -> None:
    if case == "shared-index":
        vertices = [*TETRA_VERTICES, [-1, 0, 0], [0, -1, 0], [0, 0, -1]]
        second_faces = [[0 if index == 0 else index + 3 for index in face] for face in TETRA_FACES]
    elif case == "coincident-coordinate":
        # The second tetrahedron has a separate vertex ID at the same origin.
        # Edge-only and index-only topology would incorrectly accept the sum.
        vertices = [*TETRA_VERTICES, [0, 0, 0], [-1, 0, 0], [0, -1, 0], [0, 0, -1]]
        second_faces = [[index + 4 for index in face] for face in TETRA_FACES]
    else:
        vertices = [
            *TETRA_VERTICES,
            [3, 0, 0],
            [4, 0, 0],
            [3, 1, 0],
            [3, 0, 1],
        ]
        second_faces = [[index + 4 for index in face] for face in TETRA_FACES]
    params = {
        "vertices": vertices,
        "faces": [*TETRA_FACES, *second_faces],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Provisional scale awaiting independent review",
        "relative_scale_uncertainty": 0.1,
    }
    direct = measure_mesh_preview(**params)
    individual_volume = 0.01**3 / 6
    assert direct["edge_connected_patch_count"] == 2
    assert direct["edge_connected_patch_enclosed_volumes_m3"] == pytest.approx(
        [individual_volume, individual_volume]
    )
    assert direct["vertex_touching_patch_vertex_count"] == int(case == "shared-index")
    assert direct["coincident_patch_coordinate_count"] == int(case == "coincident-coordinate")
    if case != "disjoint":
        assert direct["enclosed_volume_m3"] is None
        assert direct["enclosed_volume_scale_interval_m3"] is None
        if case == "shared-index":
            assert "vertex_touching_mesh_patches" in direct["qc_warnings"]
            assert "enclosed_volume_vertex_touching_patches" in direct["qc_warnings"]
        else:
            assert "coincident_mesh_patch_coordinates" in direct["qc_warnings"]
            assert "enclosed_volume_coincident_patch_coordinates" in direct["qc_warnings"]
            assert "vertex_touching_mesh_patches" not in direct["qc_warnings"]
    else:
        assert direct["enclosed_volume_m3"] == pytest.approx(2 * individual_volume)
        assert direct["enclosed_volume_scale_interval_m3"] == pytest.approx(
            [2 * individual_volume * 0.9**3, 2 * individual_volume * 1.1**3]
        )
        assert "vertex_touching_mesh_patches" not in direct["qc_warnings"]
    assert direct["measurement_status"] == "caller_supplied_unverified"
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Vertex-touching volume QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    graph = {
        "graph_id": "vertex-touching-volume-v14",
        "name": "Vertex-touching mesh volume QC",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": params},
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
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    for key in (
        "vertex_touching_patch_vertex_count",
        "coincident_patch_coordinate_count",
        "enclosed_volume_m3",
        "enclosed_volume_scale_interval_m3",
        "edge_connected_patch_enclosed_volumes_m3",
        "edge_connected_patch_enclosed_volume_scale_intervals_m3",
        "qc_warnings",
    ):
        assert artifact[key] == standalone.json()[key]
    assert artifact["provenance"]["calibration_verified"] is False
    assert artifact["measurement_status"] == "caller_supplied_unverified"
