"""Full-mesh scientific measurements survive bounded 3D render sampling."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_render_sample_v14 import _mesh_parameters


@pytest.mark.parametrize("face_count", [512, 513])
def test_render_threshold_preserves_original_face_indices(face_count: int) -> None:
    parameters = _mesh_parameters(face_count)
    result = measure_mesh_preview(**parameters)
    indices = result["preview_face_indices"]
    source_vertices = result["preview_vertex_indices"]
    assert result["face_count"] == face_count
    assert len(indices) == 512
    assert result["preview_face_count"] == 512
    assert result["preview_face_fraction"] == pytest.approx(512 / face_count)
    assert indices[0] == 0
    assert indices[-1] == face_count - 1
    assert result["preview_is_decimated"] is (face_count == 513)
    assert len(set(indices)) == 512
    for source_face, local_face in zip(indices, result["preview_faces_local_indices"], strict=True):
        assert [source_vertices[index] for index in local_face] == parameters["faces"][source_face]
    assert result["surface_area_m2"] == pytest.approx(face_count * 0.5 * 0.01**2)
    assert result["area_scale_uncertainty_m2"] == pytest.approx(0.2 * result["surface_area_m2"])
    assert result["preview_surface_area_fraction"] == pytest.approx(512 / face_count)
    assert result["preview_sampled_surface_area_m2"] == pytest.approx(
        result["surface_area_m2"] * 512 / face_count
    )
    assert result["provenance"]["calibration_verified"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_decimated_mesh_saved_workflow_matches_standalone(client: TestClient) -> None:
    project_id = str(create_project(client, "513 triangle render workflow")["id"])
    parameters = _mesh_parameters(513)
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["preview_is_decimated"] is True
    assert expected["preview_face_count"] == 512
    assert expected["preview_face_fraction"] == pytest.approx(512 / 513)
    assert expected["preview_surface_area_fraction"] == pytest.approx(512 / 513)
    assert expected["preview_sampled_surface_area_m2"] == pytest.approx(
        expected["surface_area_m2"] * 512 / 513
    )
    assert expected["preview_camera_fit_basis"] == "all_referenced_vertices"
    assert expected["preview_coordinate_registration_verified"] is False
    assert expected["preview_camera_radius_m"] > 0

    graph = {
        "graph_id": "mesh-render-boundary-513-v14",
        "name": "Decimated 3D mesh scientific parity",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": parameters,
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
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64


def test_camera_fit_uses_unsampled_faces_but_ignores_orphan_vertices() -> None:
    """A missed display triangle must still influence the full-mesh camera fit."""
    parameters = _mesh_parameters(513)
    # Uniform 512-of-513 face sampling skips face 511.
    parameters["vertices"][3 * 511][0] = 20_000.0
    parameters["vertices"].append([100_000_000.0] * 3)
    result = measure_mesh_preview(**parameters)

    assert 511 not in result["preview_face_indices"]
    assert 3 * 511 not in result["preview_vertex_indices"]
    assert result["unreferenced_vertex_count"] == 1
    assert result["preview_referenced_bounds_in_source_frame_m"] == {
        "minimum": [0.0, 0.0, 0.0],
        "maximum": [200.0, 0.01, 0.0],
    }
    assert result["preview_camera_target_in_source_frame_m"] == pytest.approx([100.0, 0.005, 0.0])
    assert result["preview_camera_radius_m"] == pytest.approx((200.0**2 + 0.01**2) ** 0.5 / 2)
    assert result["preview_camera_fit_basis"] == "all_referenced_vertices"
    assert result["preview_coordinate_registration_verified"] is False
    assert result["provenance"]["calibration_verified"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_render_area_coverage_detects_omitted_large_triangle() -> None:
    """Face-count coverage must not masquerade as geometric area coverage."""
    parameters = _mesh_parameters(513)
    parameters["vertices"][3 * 511 + 2][1] = 100_000.0
    result = measure_mesh_preview(**parameters)
    assert 511 not in result["preview_face_indices"]
    assert result["preview_face_fraction"] == pytest.approx(512 / 513)
    assert result["preview_surface_area_fraction"] == pytest.approx(512 / 100_512)
    assert result["preview_sampled_surface_area_m2"] == pytest.approx(512 * 0.5 * 0.01**2)
    assert result["surface_area_m2"] == pytest.approx(100_512 * 0.5 * 0.01**2)
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_zero_area_mesh_has_undefined_render_area_fraction() -> None:
    parameters = _mesh_parameters(1)
    parameters["vertices"][2] = [2.0, 0.0, 0.0]
    result = measure_mesh_preview(**parameters)
    assert result["surface_area_m2"] == 0.0
    assert result["preview_sampled_surface_area_m2"] == 0.0
    assert result["preview_surface_area_fraction"] is None
    assert "degenerate_triangles_present" in result["qc_warnings"]


def test_extrema_pinning_recovers_hidden_coral_tip_without_changing_science() -> None:
    """Retain an otherwise unseen tip face; keep full-mesh metrics unchanged."""
    params = _mesh_parameters(513)
    # Uniform 512/513 face sampling omits face 511, which carries this tip.
    params["vertices"][3 * 511 + 2][1] = 100_000.0
    uniform = measure_mesh_preview(**params)
    pinned = measure_mesh_preview(**params, preserve_axis_extrema_in_preview=True)

    assert uniform["preview_sampling_strategy"] == "uniform_face_index"
    assert 511 not in uniform["preview_face_indices"]
    assert "y_max" in uniform["preview_omitted_axis_extremum_sides"]
    assert pinned["preview_sampling_strategy"] == "uniform_face_index_extrema_preserving"
    assert pinned["preview_face_count"] == 512
    assert pinned["preview_is_decimated"] is True
    assert 511 in pinned["preview_face_indices"]
    assert len(set(pinned["preview_face_indices"])) == 512
    assert pinned["preview_omitted_axis_extremum_sides"] == []
    assert pinned["preview_surface_area_fraction"] > 0.99
    assert uniform["preview_surface_area_fraction"] < 0.01
    assert pinned["surface_area_m2"] == uniform["surface_area_m2"]
    assert pinned["axis_aligned_dimensions_m"] == uniform["axis_aligned_dimensions_m"]
    assert pinned["provenance"]["geometry_sha256"] == uniform["provenance"]["geometry_sha256"]
    assert pinned["preview_camera_fit_basis"] == "all_referenced_vertices"
    assert pinned["preview_referenced_bounds_in_source_frame_m"] == (
        uniform["preview_referenced_bounds_in_source_frame_m"]
    )
    assert pinned["provenance"]["calibration_verified"] is False
    assert pinned["measurement_status"] == "caller_supplied_unverified"


def test_extrema_pinning_standalone_and_twice_replayed_saved_workflow(
    client: TestClient,
) -> None:
    """Display policy is saved, typed, deterministic and never a calibrated claim."""
    project_id = str(create_project(client, "Mesh extrema preview replay")["id"])
    params = _mesh_parameters(513)
    params["vertices"][3 * 511 + 2][1] = 100_000.0
    params["preserve_axis_extrema_in_preview"] = True
    base = f"/api/v1/projects/{project_id}"

    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["preview_omitted_axis_extremum_sides"] == []
    assert expected["preview_sampling_strategy"] == "uniform_face_index_extrema_preserving"
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": "mesh-extrema-preserving-v14",
        "name": "Scientific mesh with source-tip-aware display sample",
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
    assert saved.json()["graph_json"]["nodes"][1]["parameters"][
        "preserve_axis_extrema_in_preview"
    ] is True

    hashes = []
    for _ in range(2):
        run = client.post(
            f"{base}/workflow-runs",
            json={"graph_record_id": saved.json()["id"]},
        )
        assert run.status_code == 202, run.text
        app = cast(FastAPI, client.app)
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
        assert artifact["payload_json"] == expected
        assert len(artifact["payload_sha256"]) == 64
        hashes.append(artifact["payload_sha256"])
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize("invalid", [1, "true", None])
def test_mesh_extrema_pinning_requires_an_explicit_boolean(
    client: TestClient, invalid: object
) -> None:
    params = _mesh_parameters(1)
    params["preserve_axis_extrema_in_preview"] = invalid
    project_id = str(create_project(client, "Strict mesh preview sampling option")["id"])
    response = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert response.status_code == 422, response.text
