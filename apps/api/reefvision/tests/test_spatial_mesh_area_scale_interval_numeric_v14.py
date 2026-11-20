"""Scale-only surface-area intervals must not invent a zero lower bound."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

TINY_TRIANGLE = [
    [0.0, 0.0, 0.0],
    [1e-142, 0.0, 0.0],
    [0.0, 1e-142, 0.0],
]
TINY_FACE = [[0, 1, 2]]


def _request(uncertainty: float | None) -> dict:
    return {
        "vertices": TINY_TRIANGLE,
        "faces": TINY_FACE,
        "meters_per_unit": 1e-19,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified synthetic scale (not coral field evidence)",
        "relative_scale_uncertainty": uncertainty,
    }


@pytest.mark.parametrize(
    "uncertainty",
    [None, 0.1, 0.8, 1.0, 1e-17],
    ids=[
        "unspecified-does-not-invent-interval",
        "representable-positive-lower-bound",
        "positive-lower-bound-underflow",
        "mathematical-zero-lower-bound",
        "positive-uncertainty-below-binary64-area-resolution",
    ],
)
def test_area_bounds_standalone_and_saved_graph_replay(
    client: TestClient, uncertainty: float | None
) -> None:
    """Subnormal nominal area may be measured, but its uncertainty may not."""
    direct = measure_mesh_preview(**_request(uncertainty))
    params = {
        **_request(uncertainty),
        "specimen_id": "synthetic-area-underflow",
        "observation_id": "unverified-area-timepoint",
        "coordinate_frame_id": "unregistered-import-frame",
    }
    project_id = str(create_project(client, "Synthetic provisional surface area")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    nominal = standalone["surface_area_m2"]
    assert nominal is not None and 0 < nominal < 1e-320
    assert nominal == direct["surface_area_m2"]
    assert standalone["edge_connected_patch_surface_areas_m2"] == [nominal]
    assert standalone["preview_sampled_surface_area_m2"] == nominal
    warning = "surface_area_scale_interval_numeric_unrepresentable"
    if uncertainty is None:
        expected = None
    elif uncertainty == 0.8:
        assert nominal * (1 - uncertainty) ** 2 == 0.0
        expected = None
    elif uncertainty == 1e-17:
        assert nominal * (1 - uncertainty) ** 2 == nominal
        assert nominal * (1 + uncertainty) ** 2 == nominal
        expected = None
    else:
        expected = [
            nominal * (1 - uncertainty) ** 2,
            nominal * (1 + uncertainty) ** 2,
        ]
        assert expected[0] > 0 or uncertainty == 1.0
    assert standalone["surface_area_scale_interval_m2"] == expected
    assert standalone["edge_connected_patch_area_scale_intervals_m2"] == (
        None if uncertainty is None else [expected]
    )
    assert direct["surface_area_scale_interval_m2"] == expected
    assert (warning in standalone["qc_warnings"]) is (uncertainty in (0.8, 1e-17))
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False
    assert standalone["provenance"]["coordinate_registration_verified"] is False
    assert standalone["provenance"]["specimen_identity_verified"] is False
    assert standalone["confidence_interval"] is None

    graph = {
        "graph_id": "tiny-area-scale-interval-v14",
        "name": "Subnormal coral area scale uncertainty review",
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


def test_tiny_patch_interval_withheld_without_discarding_valid_global_interval(
    client: TestClient,
) -> None:
    """A valid large-patch interval survives a tiny patch in saved workflow results."""
    vertices = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [2e-140, 0.0, 0.0],
        [2e-140 + 1e-142, 0.0, 0.0],
        [2e-140, 1e-142, 0.0],
    ]
    mesh = {
        **_request(0.8),
        "vertices": vertices,
        "faces": [[0, 1, 2], [3, 4, 5]],
    }
    result = measure_mesh_preview(**mesh)
    nominal_patch_areas = result["edge_connected_patch_surface_areas_m2"]
    assert len(nominal_patch_areas) == 2
    assert nominal_patch_areas[0] > nominal_patch_areas[1] > 0
    assert result["surface_area_scale_interval_m2"] is not None
    patch_bounds = result["edge_connected_patch_area_scale_intervals_m2"]
    assert patch_bounds is not None
    assert patch_bounds[0] is not None
    assert patch_bounds[1] is None
    assert "surface_area_scale_interval_numeric_unrepresentable" in result["qc_warnings"]

    params = {
        **mesh,
        "specimen_id": "synthetic-disconnected-patches",
        "observation_id": "unverified-two-patch-timepoint",
        "coordinate_frame_id": "unregistered-patch-frame",
    }
    project_id = str(create_project(client, "Disconnected provisional coral patches")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["surface_area_scale_interval_m2"] == result["surface_area_scale_interval_m2"]
    assert standalone["edge_connected_patch_area_scale_intervals_m2"] == patch_bounds
    assert standalone["provenance"]["calibration_verified"] is False
    assert standalone["provenance"]["specimen_identity_verified"] is False
    assert standalone["provenance"]["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "disconnected-area-patch-interval-v14",
        "name": "Independent surface-area patch uncertainty review",
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


def test_true_zero_area_preserves_valid_zero_uncertainty_interval() -> None:
    """Zero from collinear points is not numeric loss of positive area."""
    result = measure_mesh_preview(
        **{
            **_request(0.8),
            "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        }
    )
    assert result["surface_area_m2"] == 0
    assert result["surface_area_scale_interval_m2"] == [0, 0]
    assert result["edge_connected_patch_area_scale_intervals_m2"] == [[0, 0]]
    assert "surface_area_scale_interval_numeric_unrepresentable" not in result["qc_warnings"]


def test_positive_area_with_subresolution_uncertainty_is_not_falsely_exact() -> None:
    """An ordinary mesh area must not acquire equal bounds from roundoff."""
    request = {
        **_request(1e-17),
        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        "meters_per_unit": 0.01,
    }
    result = measure_mesh_preview(**request)
    assert result["surface_area_m2"] == pytest.approx(5e-5)
    assert result["surface_area_scale_interval_m2"] is None
    assert result["edge_connected_patch_area_scale_intervals_m2"] == [None]
    assert "surface_area_scale_interval_numeric_unrepresentable" in result["qc_warnings"]
    assert result["confidence_interval"] is None
    assert result["provenance"]["calibration_verified"] is False

    # Equal bounds at explicitly zero uncertainty remain mathematically valid.
    exact = measure_mesh_preview(**{**request, "relative_scale_uncertainty": 0.0})
    assert exact["surface_area_scale_interval_m2"] == [5e-5, 5e-5]
    assert "surface_area_scale_interval_numeric_unrepresentable" not in exact["qc_warnings"]

    # A true zero lower limit at 100% uncertainty must not be mistaken for
    # numerical underflow, and a missing uncertainty does not assert precision.
    full = measure_mesh_preview(**{**request, "relative_scale_uncertainty": 1.0})
    assert full["surface_area_scale_interval_m2"] == pytest.approx([0.0, 2e-4])
    assert "surface_area_scale_interval_numeric_unrepresentable" not in full["qc_warnings"]
    unknown = measure_mesh_preview(**{**request, "relative_scale_uncertainty": None})
    assert unknown["surface_area_scale_interval_m2"] is None
    assert "surface_area_scale_interval_numeric_unrepresentable" not in unknown["qc_warnings"]
