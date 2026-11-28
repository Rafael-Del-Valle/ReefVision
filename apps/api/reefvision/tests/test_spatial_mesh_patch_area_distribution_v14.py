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
    assert result["edge_connected_patch_surface_area_fractions"] == pytest.approx([3 / 13, 10 / 13])
    assert result["largest_surface_patch_index"] == 1
    assert result["largest_surface_patch_area_fraction"] == pytest.approx(10 / 13)
    assert result["edge_connected_patch_area_concentration_index"] == pytest.approx(109 / 169)
    assert result["area_weighted_effective_patch_count"] == pytest.approx(169 / 109)
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
    assert result["edge_connected_patch_surface_area_fractions"] == pytest.approx([3 / 13, 10 / 13])
    assert result["largest_surface_patch_index"] == 1
    assert result["edge_connected_patch_area_concentration_index"] == pytest.approx(109 / 169)
    assert result["area_weighted_effective_patch_count"] == pytest.approx(169 / 109)


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
    assert zero["edge_connected_patch_area_concentration_index"] is None
    assert zero["area_weighted_effective_patch_count"] is None

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
    assert equal["edge_connected_patch_surface_area_fractions"] == pytest.approx([0.5, 0.5])
    assert equal["largest_surface_patch_index"] == 0
    assert equal["edge_connected_patch_area_concentration_index"] == pytest.approx(0.5)
    assert equal["area_weighted_effective_patch_count"] == pytest.approx(2.0)


def test_single_positive_area_patch_has_effective_count_one() -> None:
    result = measure_mesh_preview(
        **{
            **GEOMETRY,
            "faces": [[0, 1, 2]],
            "relative_scale_uncertainty": None,
        }
    )
    assert result["edge_connected_patch_surface_area_fractions"] == [1.0]
    assert result["edge_connected_patch_area_concentration_index"] == 1.0
    assert result["area_weighted_effective_patch_count"] == 1.0
    assert result["provenance"]["relative_scale_uncertainty"] is None
    assert result["measurement_status"] == "caller_supplied_unverified"


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
        "edge_connected_patch_area_concentration_index",
        "area_weighted_effective_patch_count",
    ):
        assert artifact[key] == standalone.json()[key]
    assert (
        artifact["provenance"]["geometry_sha256"]
        == (standalone.json()["provenance"]["geometry_sha256"])
    )
    assert artifact["measurement_status"] == "caller_supplied_unverified"


@pytest.mark.parametrize("small_patch_first", [False, True])
def test_positive_subnormal_area_share_is_flagged_in_saved_scientific_workflow(
    client: TestClient,
    small_patch_first: bool,
) -> None:
    """A positive patch must retain its presence regardless of source-face order."""
    source_faces = [[0, 1, 2], [3, 4, 5]]
    if small_patch_first:
        source_faces.reverse()
    params = {
        **GEOMETRY,
        "vertices": [
            [0.0, 0.0, 0.0],
            [1_000_000_000.0, 0.0, 0.0],
            [0.0, 1_000_000_000.0, 0.0],
            [0.0, 0.0, 1e-160],
            [3e-162, 0.0, 1e-160],
            [0.0, 3e-162, 1e-160],
        ],
        "faces": source_faces,
        "meters_per_unit": 1.0,
    }
    direct = measure_mesh_preview(**params)
    tiny_patch_index = 0 if small_patch_first else 1
    expected_fractions = [0.0, 1.0] if small_patch_first else [1.0, 0.0]
    assert direct["edge_connected_patch_surface_areas_m2"][tiny_patch_index] > 0
    assert direct["edge_connected_patch_surface_area_fractions"] == expected_fractions
    assert direct["largest_surface_patch_index"] == (1 if small_patch_first else 0)
    assert "mesh_patch_area_fraction_underflow" in direct["qc_warnings"]
    assert "mesh_face_area_fraction_underflow" in direct["qc_warnings"]
    assert direct["measurement_status"] == "caller_supplied_unverified"
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Subnormal patch share evidence")["id"])
    base = f"/api/v1/projects/{project_id}"
    payload = {
        **params,
        "specimen_id": "unverified-reconstruction",
        "coordinate_frame_id": "unregistered-import-frame",
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=payload)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["edge_connected_patch_surface_areas_m2"][tiny_patch_index] > 0
    for warning in (
        "mesh_patch_area_fraction_underflow",
        "mesh_face_area_fraction_underflow",
    ):
        assert warning in standalone["qc_warnings"]
    assert standalone["provenance"]["specimen_identity_verified"] is False
    assert standalone["provenance"]["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "positive-subnormal-mesh-area-share-v14",
        "name": "Provisional area share precision diagnostics",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": payload},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
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


def test_genuinely_degenerate_patch_does_not_raise_area_fraction_underflow_warning() -> None:
    params = {
        **GEOMETRY,
        "vertices": [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 10],
            [1, 0, 10],
            [2, 0, 10],
        ],
    }
    result = measure_mesh_preview(**params)
    assert result["edge_connected_patch_surface_areas_m2"][1] == 0
    assert "degenerate_triangles_present" in result["qc_warnings"]
    assert "mesh_face_area_fraction_underflow" not in result["qc_warnings"]
    assert "mesh_patch_area_fraction_underflow" not in result["qc_warnings"]


@pytest.mark.parametrize("small_face_first", [False, True])
def test_connected_tiny_face_warns_without_claiming_an_omitted_patch(
    client: TestClient,
    small_face_first: bool,
) -> None:
    """A representable face may have zero numeric share inside one connected patch."""
    # Both triangles share an indexed edge. The small face is positive but
    # its area share underflows relative to the large face; it is not a
    # separate coral colony, disconnected patch, or missing tissue.
    source_faces = [[0, 1, 2], [1, 0, 3]]
    if small_face_first:
        source_faces.reverse()
    params = {
        **GEOMETRY,
        "vertices": [
            [0.0, 0.0, 0.0],
            [1_000_000_000.0, 0.0, 0.0],
            [0.0, 1_000_000_000.0, 0.0],
            [0.0, 0.0, 1e-320],
        ],
        "faces": source_faces,
        "meters_per_unit": 1.0,
        "specimen_id": "provisional-connected-surface",
        "coordinate_frame_id": "unregistered-source-frame",
    }
    engine_params = {
        key: value
        for key, value in params.items()
        if key not in {"specimen_id", "coordinate_frame_id"}
    }
    direct = measure_mesh_preview(**engine_params)
    assert direct["edge_connected_patch_count"] == 1
    assert direct["edge_connected_patch_surface_area_fractions"] == [1.0]
    assert direct["surface_area_m2"] == pytest.approx(5e17)
    assert "mesh_face_area_fraction_underflow" in direct["qc_warnings"]
    assert "mesh_patch_area_fraction_underflow" not in direct["qc_warnings"]
    assert "disconnected_mesh_patches" not in direct["qc_warnings"]
    assert direct["measurement_status"] == "caller_supplied_unverified"

    project_id = str(create_project(client, "Connected subnormal face QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["qc_warnings"] == direct["qc_warnings"]
    assert standalone["provenance"]["calibration_verified"] is False
    assert standalone["provenance"]["specimen_identity_verified"] is False
    assert standalone["provenance"]["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "connected-subnormal-face-qc-v14",
        "name": "Provisional connected-face precision diagnostics",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
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
