"""Signed-coordinate mesh centroid regression across API and persisted workflows."""

from __future__ import annotations

from math import fsum
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project


def test_signed_vertex_cancellation_preserves_centroid_in_saved_workflow(
    client: TestClient,
) -> None:
    """A source-coordinate value below another vertex's ULP must survive."""
    # Ordinary left-to-right sum(1e9, 1e-8, -1e9) loses the 1e-8
    # contribution. Its exact floating-point input is still representable
    # and changes the reconstructed triangle's surface centroid.
    params = {
        "vertices": [[1e9, 0.0, 0.0], [1e-8, 1.0, 0.0], [-1e9, 0.0, 1.0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic coordinates; scale not independently verified",
        "relative_scale_uncertainty": 0.05,
    }
    expected_x_m = fsum([1e9, 1e-8, -1e9]) / 3 * 0.01
    assert expected_x_m > 0
    direct = measure_mesh_preview(**params)
    assert direct["area_weighted_surface_centroid_m"][0] == pytest.approx(
        expected_x_m, rel=1e-12, abs=1e-17
    )
    assert direct["edge_connected_patch_area_weighted_surface_centroids_m"] == [
        direct["area_weighted_surface_centroid_m"]
    ]
    assert direct["measurement_status"] == "caller_supplied_unverified"
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Signed centroid vertex cancellation")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    for field in (
        "area_weighted_surface_centroid_m",
        "edge_connected_patch_area_weighted_surface_centroids_m",
        "area_weighted_centroid_scale_uncertainty_m",
        "edge_connected_patch_centroid_scale_uncertainties_m",
        "surface_area_m2",
        "qc_warnings",
    ):
        assert standalone[field] == direct[field]
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "signed-mesh-centroid-v14",
        "name": "Signed mesh surface centroid",
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    artifact_hashes: list[str] = []
    for _ in range(2):
        run = client.post(
            f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]}
        )
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifact = next(
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        )
        for field in (
            "area_weighted_surface_centroid_m",
            "edge_connected_patch_area_weighted_surface_centroids_m",
            "area_weighted_centroid_scale_uncertainty_m",
            "edge_connected_patch_centroid_scale_uncertainties_m",
            "surface_area_m2",
            "qc_warnings",
            "provenance",
        ):
            assert artifact["payload_json"][field] == standalone[field]
        artifact_hashes.append(artifact["payload_sha256"])
    assert len(set(artifact_hashes)) == 1
