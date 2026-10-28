"""Full-mesh disconnected-patch area fractions and saved workflow parity."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

GEOMETRY = {
    "vertices": [
        [0, 0, 0],
        [2, 0, 0],
        [0, 3, 0],
        [10, 0, 0],
        [14, 0, 0],
        [10, 5, 0],
    ],
    "faces": [[0, 1, 2], [3, 4, 5]],
    "meters_per_unit": 0.1,
    "calibration_method": "ruler",
    "calibration_evidence": "Unverified field scale",
    "relative_scale_uncertainty": 0.1,
}


def test_patch_area_fractions_use_all_faces_and_preserve_source_patch_order() -> None:
    result = measure_mesh_preview(**GEOMETRY)
    assert result["edge_connected_patch_surface_areas_m2"] == pytest.approx([0.03, 0.1])
    assert result["edge_connected_patch_surface_area_fractions"] == pytest.approx(
        [3 / 13, 10 / 13]
    )
    assert result["largest_surface_patch_index"] == 1
    assert result["largest_surface_patch_area_fraction"] == pytest.approx(10 / 13)
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
    assert "disconnected_mesh_patches" in result["qc_warnings"]


@pytest.mark.parametrize("scale,uncertainty", [(0.01, None), (1.0, 0.0), (2.0, 0.5)])
def test_patch_fractions_are_invariant_to_common_scale(
    scale: float, uncertainty: float | None
) -> None:
    result = measure_mesh_preview(
        **{**GEOMETRY, "meters_per_unit": scale, "relative_scale_uncertainty": uncertainty}
    )
    assert result["edge_connected_patch_surface_area_fractions"] == pytest.approx(
        [3 / 13, 10 / 13]
    )
    assert result["largest_surface_patch_index"] == 1


def test_zero_area_and_equal_area_patches_do_not_invent_dominance() -> None:
    zero = measure_mesh_preview(
        **{
            **GEOMETRY,
            "vertices": [[0, 0, 0], [1, 0, 0], [2, 0, 0]],
            "faces": [[0, 1, 2]],
        }
    )
    assert zero["edge_connected_patch_surface_area_fractions"] is None
    assert zero["largest_surface_patch_index"] is None
    assert zero["largest_surface_patch_area_fraction"] is None

    equal = measure_mesh_preview(
        **{
            **GEOMETRY,
            "vertices": [
                [0, 0, 0],
                [1, 0, 0],
                [0, 1, 0],
                [10, 0, 0],
                [11, 0, 0],
                [10, 1, 0],
            ],
        }
    )
    assert equal["edge_connected_patch_surface_area_fractions"] == pytest.approx(
        [0.5, 0.5]
    )
    assert equal["largest_surface_patch_index"] == 0


def test_patch_area_distribution_survives_saved_typed_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "Mesh patch distribution")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=GEOMETRY)
    assert standalone.status_code == 200, standalone.text
    graph = {
        "graph_id": "mesh-patch-distribution-v14",
        "name": "Unverified surface distribution",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": GEOMETRY},
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
        "edge_connected_patch_surface_area_fractions",
        "largest_surface_patch_index",
        "largest_surface_patch_area_fraction",
    ):
        assert artifact[key] == standalone.json()[key]
    assert artifact["provenance"]["geometry_sha256"] == (
        standalone.json()["provenance"]["geometry_sha256"]
    )
    assert artifact["measurement_status"] == "caller_supplied_unverified"
