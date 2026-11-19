"""Tiny but representable calibrated coral volume must survive cubic scaling."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

LARGE_TETRA_VERTICES = [
    [0.0, 0.0, 0.0],
    [1e8, 0.0, 0.0],
    [0.0, 1e8, 0.0],
    [0.0, 0.0, 1e8],
]
CLOSED_FACES = [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]


def _params(scale: float) -> dict:
    return {
        "vertices": LARGE_TETRA_VERTICES,
        "faces": CLOSED_FACES,
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic scale; not independently verified",
        "relative_scale_uncertainty": 0.1,
    }


def test_representable_tiny_volume_preserves_exact_cubic_scale_bounds() -> None:
    scale = 1e-110
    assert scale**3 == 0.0  # Regression: applying this intermediate drops all volume.
    result = measure_mesh_preview(**_params(scale))
    expected = (1e24 / 6) * scale * scale * scale
    assert expected > 0
    assert result["surface_area_m2"] > 0
    assert result["enclosed_volume_m3"] == pytest.approx(expected, rel=1e-12, abs=0)
    assert result["edge_connected_patch_enclosed_volumes_m3"] == pytest.approx(
        [expected], rel=1e-12, abs=0
    )
    assert result["enclosed_volume_scale_interval_m3"] == pytest.approx(
        [expected * 0.9**3, expected * 1.1**3], rel=1e-12, abs=0
    )
    assert result["edge_connected_patch_enclosed_volume_scale_intervals_m3"][0] == (
        pytest.approx([expected * 0.9**3, expected * 1.1**3], rel=1e-12, abs=0)
    )
    assert result["surface_to_enclosed_volume_ratio_per_m"] is not None
    assert "enclosed_volume_zero_or_underflow" not in result["qc_warnings"]
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_genuinely_unrepresentable_cubic_volume_remains_withheld() -> None:
    # Surface area and dimensions still survive; the physical volume does not.
    result = measure_mesh_preview(**_params(1e-150))
    assert result["surface_area_m2"] > 0
    assert all(dimension > 0 for dimension in result["axis_aligned_dimensions_m"])
    assert result["enclosed_volume_m3"] is None
    assert result["edge_connected_patch_enclosed_volumes_m3"] == [None]
    assert result["enclosed_volume_scale_interval_m3"] is None
    assert "enclosed_volume_zero_or_underflow" in result["qc_warnings"]


def test_tiny_volume_standalone_and_replayed_saved_graph_preserve_provenance(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Small provisional enclosed volume")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **_params(1e-110),
        "specimen_id": "synthetic-unverified-coral",
        "observation_id": "tiny-volume-survey-1",
        "coordinate_frame_id": "imported-unregistered",
    }
    standalone_response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone_response.status_code == 200, standalone_response.text
    standalone = standalone_response.json()
    assert standalone["enclosed_volume_m3"] > 0
    assert standalone["provenance"]["calibration_verified"] is False
    assert standalone["provenance"]["specimen_identity_verified"] is False
    assert standalone["provenance"]["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "tiny-calibrated-volume-v14",
        "name": "Preserve representable provisional cubic volumes",
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
