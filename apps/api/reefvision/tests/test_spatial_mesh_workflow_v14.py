"""Saved workflow and standalone API regression for ReefVision 1.4 mesh previews."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project

MESH = {
    "obj_text": "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n",
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Known scale bar, unreviewed",
    "relative_scale_uncertainty": 0.05,
}


def test_mesh_preview_api_is_unverified(client: TestClient) -> None:
    project = create_project(client, "Mesh preview API")
    response = client.post(f"/api/v1/projects/{project['id']}/spatial/mesh-preview", json=MESH)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["surface_area_m2"] == pytest.approx(0.0003)
    assert result["surface_area_to_bounding_diagonal_squared_ratio"] == pytest.approx(3 / 13)
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
    homogeneous = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview",
        json={
            **MESH,
            "obj_text": "v 0 0 0 2\nv 4 0 0 2\nv 0 6 0 2\nf 1 2 3\n",
        },
    )
    assert homogeneous.status_code == 200, homogeneous.text
    assert (
        homogeneous.json()["provenance"]["geometry_sha256"]
        == (result["provenance"]["geometry_sha256"])
    )
    assert homogeneous.json()["area_scale_uncertainty_m2"] == pytest.approx(
        result["area_scale_uncertainty_m2"]
    )
    invalid = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview",
        json={**MESH, "obj_text": "v 0 0 0\nf 1 2 3"},
    )
    assert invalid.status_code == 400


@pytest.mark.parametrize("scale", [0.001, 0.01, 10.0])
@pytest.mark.parametrize("uncertainty", [None, 0.0, 0.5])
def test_mesh_shape_ratio_cancels_common_scale_only(
    client: TestClient, scale: float, uncertainty: float | None
) -> None:
    project = create_project(client, "Mesh shape ratio")
    response = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview",
        json={**MESH, "meters_per_unit": scale, "relative_scale_uncertainty": uncertainty},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["surface_area_to_bounding_diagonal_squared_ratio"] == pytest.approx(3 / 13)
    assert result["provenance"]["calibration_verified"] is False


def test_mesh_shape_ratio_withholds_zero_diagonal(client: TestClient) -> None:
    project = create_project(client, "Degenerate mesh shape ratio")
    response = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview",
        json={
            **MESH,
            "obj_text": "v 0 0 0\nv 0 0 0\nv 0 0 0\nf 1 2 3\n",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["surface_area_to_bounding_diagonal_squared_ratio"] is None


@pytest.mark.parametrize(
    ("obj_text", "warning"),
    [
        pytest.param(
            "v 0 0 0\nv 1e-200 0 0\nv 0 1e-200 0\nf 1 2 3\n",
            "mesh_shape_ratio_unavailable_numeric_underflow",
            id="underflow",
        ),
        pytest.param(
            "v 0 0 0\nv 0 0 0\nv 0 0 0\nf 1 2 3\n",
            "mesh_shape_ratio_unavailable_zero_extent",
            id="zero-extent",
        ),
    ],
)
def test_mesh_shape_ratio_unavailable_in_saved_workflow(
    client: TestClient, obj_text: str, warning: str
) -> None:
    project_id = str(create_project(client, "Tiny mesh shape ratio")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **MESH,
        "obj_text": obj_text,
    }
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    measurement = standalone.json()
    assert measurement["surface_area_to_bounding_diagonal_squared_ratio"] is None
    assert warning in measurement["qc_warnings"]
    assert measurement["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "tiny-mesh-shape-ratio-v14",
        "name": "Underflow-safe mesh diagnostic",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": params,
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
    assert artifact["surface_area_to_bounding_diagonal_squared_ratio"] is None
    assert warning in artifact["qc_warnings"]
    expected_sha = measurement["provenance"]["geometry_sha256"]
    assert artifact["provenance"]["geometry_sha256"] == expected_sha


@pytest.mark.parametrize(
    "obj_text",
    [
        pytest.param(MESH["obj_text"], id="cartesian"),
        pytest.param("v 0 0 0 2\nv 4 0 0 2\nv 0 6 0 2\nf 1 2 3\n", id="homogeneous"),
        pytest.param(
            "v 0 0 0 # origin\nv 2 0 0 # x\nv 0 3 0 # y\nf 1 2 3 # face\n",
            id="inline-comments",
        ),
        pytest.param(
            "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1/2 2//3 3/4/5\n",
            id="mixed-face-references",
        ),
    ],
)
def test_saved_mesh_workflow_roundtrip(client: TestClient, obj_text: str) -> None:
    project = create_project(client, "Mesh workflow")
    project_id = str(project["id"])
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200
    node = next(item for item in registry.json() if item["node_type"] == "mesh_surface_preview")
    assert node["executable"] is True
    assert node["output_ports"][0]["accepted_types"] == ["mesh_measurement_preview"]
    graph = {
        "graph_id": "mesh-preview-v14",
        "name": "Calibrated triangle preview",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": {**MESH, "obj_text": obj_text},
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
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    record = saved.json()
    assert record["graph_json"]["nodes"][1]["parameters"]["obj_text"] == obj_text
    run = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": record["id"]},
    )
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"]["surface_area_m2"] == pytest.approx(0.0003)
    shape_ratio = artifact["payload_json"]["surface_area_to_bounding_diagonal_squared_ratio"]
    assert shape_ratio == pytest.approx(3 / 13)
    assert artifact["payload_json"]["project_id"] == project_id
    assert artifact["payload_json"]["measurement_status"] == "caller_supplied_unverified"
    assert len(artifact["payload_sha256"]) == 64
    assert artifact["payload_json"]["area_scale_uncertainty_m2"] == pytest.approx(0.00003)
    assert artifact["payload_json"]["axis_aligned_bounding_box_diagonal_m"] == pytest.approx(
        0.01 * 13**0.5
    )
    measured = artifact["payload_json"]
    assert measured["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx(
        [0.001, 0.0015, 0.0]
    )
    assert artifact["payload_json"]["provenance"]["source_format"] == "obj"
    assert artifact["payload_json"]["provenance"]["calibration_verified"] is False
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**MESH, "obj_text": obj_text},
    )
    assert standalone.status_code == 200, standalone.text
    assert artifact["payload_json"]["surface_area_m2"] == pytest.approx(
        standalone.json()["surface_area_m2"]
    )
    assert (
        artifact["payload_json"]["surface_area_to_bounding_diagonal_squared_ratio"]
        == (standalone.json()["surface_area_to_bounding_diagonal_squared_ratio"])
    )
    assert (
        artifact["payload_json"]["provenance"]["geometry_sha256"]
        == standalone.json()["provenance"]["geometry_sha256"]
    )
    assert (
        artifact["payload_json"]["provenance"]["source_payload_sha256"]
        == standalone.json()["provenance"]["source_payload_sha256"]
    )


def test_unverified_mesh_artifact_cannot_feed_project_input(client: TestClient) -> None:
    project = create_project(client, "Mesh typing")
    graph = {
        "graph_id": "mesh-bad-edge",
        "name": "Prevent mesh preview as project",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": MESH},
            {"node_id": "images", "node_type": "project_images"},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            },
            {
                "edge_id": "bad",
                "source_node_id": "mesh",
                "source_port_id": "measurement",
                "target_node_id": "images",
                "target_port_id": "project",
            },
        ],
    }
    response = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/validate", json=graph)
    assert response.status_code == 200
    assert any(issue["code"] == "incompatible_port_types" for issue in response.json()["issues"])


def test_saved_mesh_workflow_preserves_topology_qc(client: TestClient) -> None:
    project_id = str(create_project(client, "Mesh topology workflow")["id"])
    params = {
        "vertices": [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
            [10, 0, 0],
            [11, 0, 0],
            [10, 1, 0],
            [1000, 1000, 1000],
        ],
        "faces": [[0, 1, 2], [0, 3, 2], [4, 5, 6]],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed control target",
        "relative_scale_uncertainty": 0.05,
    }
    graph = {
        "graph_id": "mesh-topology-qc-v14",
        "name": "Topology QC",
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
    base = f"/api/v1/projects/{project_id}"
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    assert artifact["edge_connected_patch_count"] == 2
    assert artifact["inconsistent_winding_edge_count"] == 1
    assert artifact["unreferenced_vertex_count"] == 1
    assert artifact["axis_aligned_dimensions_m"] == pytest.approx([0.11, 0.01, 0.0])
    assert artifact["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx(
        [0.0055, 0.0005, 0.0]
    )
    assert "unreferenced_mesh_vertices" in artifact["qc_warnings"]
    assert "disconnected_mesh_patches" in artifact["qc_warnings"]
    assert "inconsistent_face_winding" in artifact["qc_warnings"]
    for field in (
        "edge_connected_patch_count",
        "inconsistent_winding_edge_count",
        "unreferenced_vertex_count",
        "axis_aligned_dimensions_m",
        "axis_aligned_dimension_scale_uncertainty_m",
        "axis_aligned_bounding_box_diagonal_m",
        "axis_aligned_bounding_box_diagonal_scale_uncertainty_m",
        "edge_connected_patch_bounding_box_diagonals_m",
        "edge_connected_patch_bounding_box_diagonal_scale_uncertainties_m",
    ):
        assert artifact[field] == standalone.json()[field]
    assert (
        artifact["provenance"]["geometry_sha256"]
        == (standalone.json()["provenance"]["geometry_sha256"])
    )
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False


def test_saved_mesh_workflow_preserves_rigid_translation_measurement_parity(
    client: TestClient,
) -> None:
    """Saved typed graphs must not report coral growth after a coordinate-origin shift."""
    project_id = str(create_project(client, "Translated mesh workflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    vertices = [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]]
    params = {
        "vertices": [[x + 100, y - 200, z + 300] for x, y, z in vertices],
        "faces": [[0, 1, 2], [0, 2, 3]],
        "meters_per_unit": 0.5,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic translated square; independent review absent",
        "relative_scale_uncertainty": 0.1,
    }
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    graph = {
        "graph_id": "translated-mesh-parity-v14",
        "name": "Translated surface scientific parity",
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
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    expected = standalone.json()
    assert artifact["surface_area_m2"] == pytest.approx(1.0)
    assert artifact["boundary_edge_length_m"] == pytest.approx(4.0)
    assert artifact["enclosed_volume_m3"] is None
    for field in (
        "surface_area_m2",
        "surface_area_scale_interval_m2",
        "boundary_edge_length_m",
        "boundary_loop_perimeters_m",
    ):
        assert artifact[field] == pytest.approx(expected[field])
    assert artifact["boundary_loop_perimeter_scale_intervals_m"][0] == pytest.approx(
        expected["boundary_loop_perimeter_scale_intervals_m"][0]
    )
    assert artifact["provenance"]["geometry_sha256"] == expected["provenance"]["geometry_sha256"]
    assert artifact["provenance"]["calibration_verified"] is False
    assert artifact["measurement_status"] == "caller_supplied_unverified"


@pytest.mark.parametrize("reverse_winding", [False, True], ids=["outward", "inward"])
def test_saved_mesh_workflow_closed_volume_reference(
    client: TestClient, reverse_winding: bool
) -> None:
    """Saved execution preserves unsigned volume under globally reversed face winding."""
    project_id = str(create_project(client, "Closed mesh workflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "faces": [
            list(reversed(face)) if reverse_winding else face
            for face in [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]
        ],
        "meters_per_unit": 2.0,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified synthetic reference",
        "relative_scale_uncertainty": 0.1,
    }
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    graph = {
        "graph_id": "closed-mesh-volume-v14",
        "name": "Closed mesh volume",
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
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    expected = standalone.json()
    assert artifact["enclosed_volume_m3"] == pytest.approx(4 / 3)
    # Volume scales cubically with linear calibration, not linearly or quadratically.
    # These independently derived bounds must survive standalone and saved execution.
    expected_volume_interval = [(4 / 3) * 0.9**3, (4 / 3) * 1.1**3]
    assert expected["enclosed_volume_scale_interval_m3"] == pytest.approx(expected_volume_interval)
    assert artifact["enclosed_volume_scale_interval_m3"] == pytest.approx(expected_volume_interval)
    # Three right-triangle faces and one equilateral face, scaled by 2 m/unit.
    expected_surface_area = 6 + 2 * 3**0.5
    expected_surface_interval = [expected_surface_area * 0.9**2, expected_surface_area * 1.1**2]
    assert expected["surface_area_m2"] == pytest.approx(expected_surface_area)
    assert artifact["surface_area_m2"] == pytest.approx(expected_surface_area)
    assert expected["surface_area_scale_interval_m2"] == pytest.approx(expected_surface_interval)
    assert artifact["surface_area_scale_interval_m2"] == pytest.approx(expected_surface_interval)
    assert artifact["boundary_edge_length_m"] == pytest.approx(0.0)
    for key in (
        "enclosed_volume_m3",
        "enclosed_volume_scale_interval_m3",
        "surface_area_m2",
        "surface_area_scale_interval_m2",
    ):
        assert artifact[key] == pytest.approx(expected[key])
    assert artifact["provenance"]["geometry_sha256"] == expected["provenance"]["geometry_sha256"]
    assert artifact["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize(
    "obj_text",
    [
        "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n",
        "v 0 3 0\nv 0 0 0\nv 2 0 0\nf 2 3 1\n",
        "v 0 0 0\nv 2 0 0\nv 0 3 0\nf -3 -2 -1\n",
    ],
    ids=["canonical", "reindexed-vertices", "relative-face-indices"],
)
def test_mesh_vertex_reindexing_preserves_scientific_measurements(
    client: TestClient, obj_text: str
) -> None:
    """Equivalent OBJ indexing must not alter measured coral geometry."""
    project = create_project(client, "Equivalent OBJ indexing")
    response = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview",
        json={**MESH, "obj_text": obj_text},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["surface_area_m2"] == pytest.approx(0.0003)
    assert result["surface_area_to_bounding_diagonal_squared_ratio"] == pytest.approx(3 / 13)
    # A 2-by-3 right triangle has perimeter 5 + sqrt(13) mesh units.
    # Length, unlike area, must propagate scale uncertainty linearly.
    expected_perimeter = (5 + 13**0.5) * 0.01
    expected_perimeter_interval = [expected_perimeter * 0.95, expected_perimeter * 1.05]
    assert result["boundary_edge_length_m"] == pytest.approx(expected_perimeter)
    assert result["boundary_loop_perimeters_m"] == pytest.approx([expected_perimeter])
    assert result["boundary_loop_perimeter_scale_intervals_m"][0] == pytest.approx(
        expected_perimeter_interval
    )
    assert result["provenance"]["calibration_verified"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"
    # Persist and execute the same representation through the typed graph engine.
    project_id = str(project["id"])
    base = f"/api/v1/projects/{project_id}"
    graph = {
        "graph_id": "obj-indexing-parity-v14",
        "name": "Equivalent OBJ indexing scientific parity",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": {**MESH, "obj_text": obj_text},
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    # Linear scale uncertainty propagates quadratically to measured area.
    # Check an independent reference, not merely parity with the API.
    expected_area_interval = [0.0003 * 0.95**2, 0.0003 * 1.05**2]
    assert result["surface_area_scale_interval_m2"] == pytest.approx(expected_area_interval)
    assert artifact["surface_area_scale_interval_m2"] == pytest.approx(expected_area_interval)
    assert artifact["surface_area_m2"] == pytest.approx(result["surface_area_m2"])
    assert artifact["boundary_edge_length_m"] == pytest.approx(expected_perimeter)
    assert artifact["boundary_loop_perimeters_m"] == pytest.approx([expected_perimeter])
    assert artifact["boundary_loop_perimeter_scale_intervals_m"][0] == pytest.approx(
        expected_perimeter_interval
    )
    assert artifact["surface_area_to_bounding_diagonal_squared_ratio"] == pytest.approx(
        result["surface_area_to_bounding_diagonal_squared_ratio"]
    )
    assert artifact["provenance"]["geometry_sha256"] == result["provenance"]["geometry_sha256"]
    assert (
        artifact["provenance"]["source_payload_sha256"]
        == result["provenance"]["source_payload_sha256"]
    )
    # Independently recover the diagonal from calibrated area and shape ratio.
    # This guards against a dimensionless ratio accidentally using unscaled units.
    expected_diagonal_squared_m2 = 13 * 0.01**2
    for measured in (result, artifact):
        assert measured["surface_area_m2"] / measured[
            "surface_area_to_bounding_diagonal_squared_ratio"
        ] == pytest.approx(expected_diagonal_squared_m2)
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("scale", [0.01, 0.02], ids=["centimeter", "two-centimeters"])
def test_saved_obj_workflow_calibration_scaling_reference(client: TestClient, scale: float) -> None:
    """A changed caller scale changes dimensional metrics, not dimensionless shape."""
    project = create_project(client, "Calibration scaling reference")
    base = f"/api/v1/projects/{project['id']}"
    params = {
        **MESH,
        "obj_text": "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n",
        "meters_per_unit": scale,
    }
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    graph = {
        "graph_id": "calibration-scaling-reference-v14",
        "name": "Calibrated OBJ scaling reference",
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
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    expected_area = 3 * scale**2
    expected_perimeter = (5 + 13**0.5) * scale
    for measured in (standalone.json(), artifact):
        assert measured["surface_area_m2"] == pytest.approx(expected_area)
        # Independently verify each spatial dimension and its linear scale error.
        assert measured["axis_aligned_dimensions_m"] == pytest.approx([2 * scale, 3 * scale, 0])
        assert measured["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx(
            [0.1 * scale, 0.15 * scale, 0]
        )
        assert measured["axis_aligned_bounding_box_diagonal_m"] == pytest.approx(13**0.5 * scale)
        # The diagonal must agree with the independently measured orthogonal extents.
        assert measured["axis_aligned_bounding_box_diagonal_m"] ** 2 == pytest.approx(
            sum(length**2 for length in measured["axis_aligned_dimensions_m"])
        )
        assert measured["boundary_edge_length_m"] == pytest.approx(expected_perimeter)
        # Calibration uncertainty follows squared area and linear perimeter scaling.
        assert measured["surface_area_scale_interval_m2"] == pytest.approx(
            [expected_area * 0.95**2, expected_area * 1.05**2]
        )
        assert measured["boundary_loop_perimeter_scale_intervals_m"][0] == pytest.approx(
            [expected_perimeter * 0.95, expected_perimeter * 1.05]
        )
        assert measured["surface_area_to_bounding_diagonal_squared_ratio"] == pytest.approx(3 / 13)
        assert measured["provenance"]["calibration_verified"] is False
        assert measured["measurement_status"] == "caller_supplied_unverified"
        # Bounds must enclose the measured values without claiming verified calibration.
        for dimension, uncertainty in zip(
            measured["axis_aligned_dimensions_m"],
            measured["axis_aligned_dimension_scale_uncertainty_m"],
            strict=True,
        ):
            assert uncertainty >= 0
            assert dimension - uncertainty <= dimension <= dimension + uncertainty
        area_low, area_high = measured["surface_area_scale_interval_m2"]
        assert area_low <= measured["surface_area_m2"] <= area_high
        perimeter_low, perimeter_high = measured["boundary_loop_perimeter_scale_intervals_m"][0]
        assert perimeter_low <= measured["boundary_edge_length_m"] <= perimeter_high
    assert (
        artifact["provenance"]["geometry_sha256"]
        == standalone.json()["provenance"]["geometry_sha256"]
    )


def test_obj_calibration_changes_units_not_source_geometry(client: TestClient) -> None:
    """A revised caller scale cannot silently rewrite source geometry identity."""
    project = create_project(client, "Calibration provenance invariance")
    base = f"/api/v1/projects/{project['id']}"
    observations = []
    for scale in (0.01, 0.02):
        response = client.post(
            f"{base}/spatial/mesh-preview",
            json={**MESH, "meters_per_unit": scale},
        )
        assert response.status_code == 200, response.text
        observations.append(response.json())

    first, second = observations
    assert first["provenance"]["geometry_sha256"] == second["provenance"]["geometry_sha256"]
    assert (
        first["provenance"]["source_payload_sha256"]
        == second["provenance"]["source_payload_sha256"]
    )
    assert second["surface_area_m2"] == pytest.approx(4 * first["surface_area_m2"])
    assert second["boundary_edge_length_m"] == pytest.approx(2 * first["boundary_edge_length_m"])
    assert second["axis_aligned_dimensions_m"] == pytest.approx(
        [2 * value for value in first["axis_aligned_dimensions_m"]]
    )
    assert second["area_scale_uncertainty_m2"] == pytest.approx(
        4 * first["area_scale_uncertainty_m2"]
    )
    assert second["surface_area_scale_interval_m2"] == pytest.approx(
        [4 * bound for bound in first["surface_area_scale_interval_m2"]]
    )
    assert second["boundary_loop_perimeter_scale_intervals_m"][0] == pytest.approx(
        [2 * bound for bound in first["boundary_loop_perimeter_scale_intervals_m"][0]]
    )
    assert second["surface_area_to_bounding_diagonal_squared_ratio"] == pytest.approx(
        first["surface_area_to_bounding_diagonal_squared_ratio"]
    )
    assert second["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx(
        [2 * value for value in first["axis_aligned_dimension_scale_uncertainty_m"]]
    )
    assert second["axis_aligned_bounding_box_diagonal_scale_uncertainty_m"] == pytest.approx(
        2 * first["axis_aligned_bounding_box_diagonal_scale_uncertainty_m"]
    )
    for observation in observations:
        assert observation["measurement_status"] == "caller_supplied_unverified"
        assert observation["provenance"]["calibration_verified"] is False


def test_saved_obj_workflow_enforces_source_byte_binding(client: TestClient) -> None:
    """A saved mesh graph must retain the exact imported bytes it was reviewed against."""
    project_id = str(create_project(client, "Mesh source integrity workflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    original = client.post(f"{base}/spatial/mesh-preview", json=MESH)
    assert original.status_code == 200, original.text
    source_sha = original.json()["provenance"]["source_payload_sha256"]
    assert isinstance(source_sha, str) and len(source_sha) == 64

    bound = {**MESH, "expected_source_payload_sha256": source_sha}
    verified_transport = client.post(f"{base}/spatial/mesh-preview", json=bound)
    assert verified_transport.status_code == 200, verified_transport.text
    assert verified_transport.json()["provenance"]["source_payload_integrity_checked"] is True
    assert verified_transport.json()["provenance"]["calibration_verified"] is False

    # Equivalent triangles with different source bytes are not the same reviewed import.
    changed = {
        **bound,
        "obj_text": MESH["obj_text"] + "# changed source bytes\\n",
    }
    rejected = client.post(f"{base}/spatial/mesh-preview", json=changed)
    assert rejected.status_code == 400, rejected.text

    graph = {
        "graph_id": "mesh-source-binding-v14",
        "name": "Exact imported OBJ byte binding",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": bound},
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
    assert (
        saved.json()["graph_json"]["nodes"][1]["parameters"]["expected_source_payload_sha256"]
        == source_sha
    )
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
    assert artifact["provenance"]["source_payload_sha256"] == source_sha
    assert artifact["provenance"]["source_payload_integrity_checked"] is True
    assert (
        artifact["provenance"]["geometry_sha256"]
        == original.json()["provenance"]["geometry_sha256"]
    )
    assert artifact["surface_area_m2"] == pytest.approx(original.json()["surface_area_m2"])
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False

    # A second execution of the persisted graph must reproduce the same
    # scientific payload and source-byte binding, not merely the same area.
    rerun = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert rerun.status_code == 202, rerun.text
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(rerun.json()["job_id"])
    )
    rerun_detail = client.get(f"/api/v1/workflow-runs/{rerun.json()['id']}")
    assert rerun_detail.status_code == 200, rerun_detail.text
    assert rerun_detail.json()["run"]["status"] == "succeeded"
    rerun_artifact = next(
        item
        for item in rerun_detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert rerun_artifact["payload_json"] == artifact
    original_artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert rerun_artifact["payload_sha256"] == original_artifact["payload_sha256"]
    assert rerun_artifact["payload_json"]["provenance"]["source_payload_sha256"] == source_sha
    assert rerun_artifact["payload_json"]["provenance"]["calibration_verified"] is False


def test_mesh_preview_rejects_oversized_integer_calibration() -> None:
    """Direct scientific API must not leak float conversion overflow."""
    from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview

    with pytest.raises(ValueError, match="meters_per_unit must be finite"):
        measure_mesh_preview(
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            faces=[[0, 1, 2]],
            meters_per_unit=10**1000,
            calibration_method="ruler",
            calibration_evidence="Unverified test calibration",
        )


def test_mesh_preview_rejects_oversized_integer_scale_uncertainty() -> None:
    """Unbounded integer uncertainty must fail scientific validation, not overflow."""
    from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview

    with pytest.raises(ValueError, match="relative_scale_uncertainty must be between 0 and 1"):
        measure_mesh_preview(
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            faces=[[0, 1, 2]],
            meters_per_unit=0.01,
            calibration_method="ruler",
            calibration_evidence="Unverified test calibration",
            relative_scale_uncertainty=10**1000,
        )


def test_obj_uncertainty_changes_intervals_not_measured_geometry(client: TestClient) -> None:
    """Changing uncertainty must not alter measured geometry or source identity."""
    project = create_project(client, "Calibration uncertainty independence")
    base = f"/api/v1/projects/{project['id']}"
    observations = []
    for uncertainty in (0.01, 0.10):
        response = client.post(
            f"{base}/spatial/mesh-preview",
            json={**MESH, "relative_scale_uncertainty": uncertainty},
        )
        assert response.status_code == 200, response.text
        observations.append(response.json())

    low, high = observations
    for key in (
        "surface_area_m2",
        "boundary_edge_length_m",
        "axis_aligned_dimensions_m",
        "axis_aligned_bounding_box_diagonal_m",
    ):
        assert low[key] == pytest.approx(high[key])
    for key in ("geometry_sha256", "source_payload_sha256"):
        assert low["provenance"][key] == high["provenance"][key]
    assert high["area_scale_uncertainty_m2"] > low["area_scale_uncertainty_m2"]
    assert high["surface_area_scale_interval_m2"][0] < low["surface_area_scale_interval_m2"][0]
    assert high["surface_area_scale_interval_m2"][1] > low["surface_area_scale_interval_m2"][1]
    for observation in observations:
        assert observation["measurement_status"] == "caller_supplied_unverified"
        assert observation["provenance"]["calibration_verified"] is False
