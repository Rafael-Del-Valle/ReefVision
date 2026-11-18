"""Area-normalized coral mesh centroids preserve tiny source-frame positions."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project


def tiny_triangle(axis: int, sign: int) -> dict:
    """A positive-area triangle whose area-times-centroid underflows binary64."""
    other_axis = (axis + 1) % 3
    second = [0.0, 0.0, 0.0]
    third = [0.0, 0.0, 0.0]
    second[axis] = sign * 1e-110
    third[other_axis] = 1e-110
    return {
        "vertices": [[0.0, 0.0, 0.0], second, third],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 1.0,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic scale; independent review absent",
        "relative_scale_uncertainty": 0.1,
    }


@pytest.mark.parametrize(
    ("axis", "sign"),
    [(0, 1), (0, -1), (1, 1), (1, -1), (2, 1), (2, -1)],
    ids=["x-positive", "x-negative", "y-positive", "y-negative", "z-positive", "z-negative"],
)
def test_representable_subnormal_area_weighted_centroid_replays(
    client: TestClient, axis: int, sign: int
) -> None:
    params = tiny_triangle(axis, sign)
    expected = sign * 1e-110 / 3
    direct = measure_mesh_preview(**params)
    centroid = direct["area_weighted_surface_centroid_m"]
    assert direct["surface_area_m2"] == pytest.approx(5e-221, rel=1e-12, abs=0)
    assert centroid[axis] == pytest.approx(expected, rel=1e-12, abs=0)
    assert centroid[(axis + 1) % 3] == pytest.approx(1e-110 / 3, rel=1e-12, abs=0)
    assert direct["edge_connected_patch_area_weighted_surface_centroids_m"] == [centroid]
    assert direct["area_weighted_centroid_scale_uncertainty_m"][axis] == pytest.approx(
        abs(expected) * 0.1, rel=1e-12, abs=0
    )
    assert direct["measurement_status"] == "caller_supplied_unverified"
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Subnormal mesh centroid evidence")["id"])
    base = f"/api/v1/projects/{project_id}"
    payload = {
        **params,
        "specimen_id": "synthetic-unverified",
        "observation_id": "scan-A",
        "coordinate_frame_id": "unregistered-source-frame",
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=payload)
    assert response.status_code == 200, response.text
    standalone = response.json()
    for key in (
        "area_weighted_surface_centroid_m",
        "edge_connected_patch_area_weighted_surface_centroids_m",
        "area_weighted_centroid_scale_uncertainty_m",
        "surface_area_m2",
    ):
        assert standalone[key] == direct[key]
    assert standalone["provenance"]["specimen_identity_verified"] is False
    assert standalone["provenance"]["coordinate_registration_verified"] is False
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": f"subnormal-centroid-{axis}-{sign}-v14",
        "name": "Unverified mesh centroid numerical integrity",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": payload},
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text

    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == standalone
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


def test_disconnected_small_patch_centroid_does_not_collapse_to_origin() -> None:
    params = tiny_triangle(0, -1)
    params["vertices"] = [
        [10.0, 10.0, 0.0],
        [11.0, 10.0, 0.0],
        [10.0, 11.0, 0.0],
        *params["vertices"],
    ]
    params["faces"] = [[0, 1, 2], [3, 4, 5]]
    result = measure_mesh_preview(**params)
    centroids = result["edge_connected_patch_area_weighted_surface_centroids_m"]
    assert centroids[0][:2] == pytest.approx([10 + 1 / 3, 10 + 1 / 3])
    assert centroids[1][0] == pytest.approx(-1e-110 / 3, rel=1e-12, abs=0)
    assert centroids[1][1] == pytest.approx(1e-110 / 3, rel=1e-12, abs=0)
    assert result["edge_connected_patch_surface_areas_m2"][1] > 0
    assert result["provenance"]["calibration_verified"] is False
