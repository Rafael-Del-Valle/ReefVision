"""Bounded render geometry must never replace full-cloud scientific measurements."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project


def _mesh_parameters(face_count: int) -> dict:
    vertices = []
    faces = []
    for index in range(face_count):
        offset = 3 * index
        vertices.extend(
            [[float(offset), 0.0, 0.0], [float(offset + 1), 0.0, 0.0], [float(offset), 1.0, 0.0]]
        )
        faces.append([offset, offset + 1, offset + 2])
    return {
        "vertices": vertices,
        "faces": faces,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed physical ruler",
        "relative_scale_uncertainty": 0.1,
    }


def test_mesh_render_sample_does_not_change_full_mesh_science() -> None:
    params = _mesh_parameters(513)
    result = measure_mesh_preview(**params)
    assert result["face_count"] == 513
    assert result["vertex_count"] == 1539
    assert result["surface_area_m2"] == pytest.approx(513 * 0.5 * 0.01**2)
    assert result["area_scale_uncertainty_m2"] == pytest.approx(2 * 0.1 * result["surface_area_m2"])
    assert result["preview_is_decimated"] is True
    assert result["preview_surface_area_fraction"] == pytest.approx(512 / 513)
    face_indices = result["preview_face_indices"]
    vertex_indices = result["preview_vertex_indices"]
    render_faces = result["preview_faces_local_indices"]
    render_vertices = result["preview_vertices_in_source_frame_m"]
    assert len(face_indices) == 512
    assert face_indices[0] == 0 and face_indices[-1] == 512
    assert len(set(face_indices)) == 512
    assert len(vertex_indices) == len(render_vertices) == 1536
    assert len(render_faces) == 512
    for sampled_face_index, local_face in zip(face_indices, render_faces, strict=True):
        assert [vertex_indices[index] for index in local_face] == params["faces"][
            sampled_face_index
        ]
    assert render_vertices[0] == [0.0, 0.0, 0.0]
    assert result["provenance"]["calibration_verified"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result == measure_mesh_preview(**params)


def test_mesh_render_sample_saved_workflow_matches_standalone(client: TestClient) -> None:
    project_id = str(create_project(client, "Mesh render sample parity")["id"])
    params = _mesh_parameters(2)
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["preview_is_decimated"] is False
    assert expected["preview_face_indices"] == [0, 1]
    assert expected["preview_vertex_indices"] == [0, 1, 2, 3, 4, 5]
    graph = {
        "graph_id": "mesh-render-sample-v14",
        "name": "Bounded mesh render sample",
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


def test_preview_missing_face_area_underflow_is_flagged_and_replayable(
    client: TestClient,
) -> None:
    """A hidden tiny face is not measured as zero merely because its patch is large."""
    # With 513 faces, the bounded 512-face display omits source face 511.
    # Every face shares an edge, so the tiny face belongs to the large patch;
    # its underflow cannot be caught by the per-patch calibrated-area guard.
    vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    vertices.extend([[0.0, 1.0 + index / 1000, 0.0] for index in range(513)])
    vertices[513] = [0.0, 1e-200, 0.0]
    params = {
        "vertices": vertices,
        "faces": [[0, 1, index + 2] for index in range(513)],
        "meters_per_unit": 1e-100,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed synthetic surface calibration",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "unverified-preview-specimen",
        "observation_id": "unverified-preview-timepoint",
        "coordinate_frame_id": "unregistered-preview-frame",
    }
    # No scale interval is fabricated when the uncertainty is unspecified,
    # but the lost positive display-only area must still be diagnosed.
    direct_params = {
        key: value
        for key, value in params.items()
        if key not in {"specimen_id", "observation_id", "coordinate_frame_id"}
    }
    direct = measure_mesh_preview(**direct_params)
    assert set(range(513)) - set(direct["preview_face_indices"]) == {511}
    assert direct["edge_connected_patch_count"] == 1
    assert direct["preview_partially_sampled_patch_indices"] == [0]
    assert direct["preview_partially_sampled_patch_missing_area_fraction"] > 0
    assert direct["preview_partially_sampled_patch_missing_area_m2"] is None
    assert direct["preview_partially_sampled_patch_missing_area_scale_interval_m2"] is None
    assert direct["surface_area_m2"] > 0
    assert direct["surface_area_scale_interval_m2"] is not None
    flag = "preview_partially_sampled_missing_area_numeric_unrepresentable"
    assert flag in direct["qc_warnings"]
    assert "surface_area_scale_interval_numeric_unrepresentable" in direct["qc_warnings"]

    unspecified = measure_mesh_preview(**{**direct_params, "relative_scale_uncertainty": None})
    assert flag in unspecified["qc_warnings"]
    assert "surface_area_scale_interval_numeric_unrepresentable" not in unspecified["qc_warnings"]
    assert unspecified["surface_area_scale_interval_m2"] is None
    assert unspecified["preview_partially_sampled_patch_missing_area_scale_interval_m2"] is None

    project_id = str(create_project(client, "Synthetic sampled-area underflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["surface_area_m2"] == direct["surface_area_m2"]
    assert flag in standalone["qc_warnings"]
    assert standalone["provenance"]["calibration_verified"] is False
    assert standalone["provenance"]["coordinate_registration_verified"] is False
    assert standalone["provenance"]["specimen_identity_verified"] is False
    assert standalone["confidence_interval"] is None

    # Missing calibration uncertainty must stay absent across the project API
    # and a persisted graph, without suppressing the preview-only underflow QC.
    no_uncertainty_params = {
        key: value for key, value in params.items() if key != "relative_scale_uncertainty"
    }
    no_uncertainty_response = client.post(
        f"{base}/spatial/mesh-preview", json=no_uncertainty_params
    )
    assert no_uncertainty_response.status_code == 200, no_uncertainty_response.text
    no_uncertainty_expected = no_uncertainty_response.json()
    assert flag in no_uncertainty_expected["qc_warnings"]
    assert (
        "surface_area_scale_interval_numeric_unrepresentable"
        not in no_uncertainty_expected["qc_warnings"]
    )
    assert no_uncertainty_expected["surface_area_scale_interval_m2"] is None
    assert no_uncertainty_expected["preview_partially_sampled_patch_missing_area_m2"] is None
    assert (
        no_uncertainty_expected["preview_partially_sampled_patch_missing_area_scale_interval_m2"]
        is None
    )
    assert no_uncertainty_expected["provenance"]["calibration_verified"] is False
    assert no_uncertainty_expected["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": "preview-missing-face-area-underflow-v14",
        "name": "Unverified preview missing-area numeric review",
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

    uncalibrated_graph = {
        **graph,
        "graph_id": "preview-missing-face-area-no-uncertainty-v14",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": no_uncertainty_params,
            },
        ],
    }
    uncalibrated_plan = client.post(f"{base}/workflow-graphs/plan", json=uncalibrated_graph)
    assert uncalibrated_plan.status_code == 200, uncalibrated_plan.text
    assert uncalibrated_plan.json()["executable"] is True
    uncalibrated_saved = client.post(f"{base}/workflow-graphs", json={"graph": uncalibrated_graph})
    assert uncalibrated_saved.status_code == 201, uncalibrated_saved.text
    uncalibrated_hashes: list[str] = []
    for _ in range(2):
        run = client.post(
            f"{base}/workflow-runs",
            json={"graph_record_id": uncalibrated_saved.json()["id"]},
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
        assert artifact["payload_json"] == no_uncertainty_expected
        uncalibrated_hashes.append(artifact["payload_sha256"])
    assert len(uncalibrated_hashes[0]) == 64
    assert uncalibrated_hashes[0] == uncalibrated_hashes[1]
    assert uncalibrated_hashes[0] != hashes[0]


def _hidden_small_patch_parameters() -> dict:
    """514-face synthetic mesh with a small, non-extreme, display-hidden patch."""
    vertices = [[0.0, 0.0, 0.0]]
    vertices.extend([[float(index), 1.0, 0.0] for index in range(514)])
    faces = [[0, index + 1, index + 2] for index in range(513)]
    vertices.extend([[10.0, 0.25, 0.0], [10.1, 0.25, 0.0], [10.0, 0.30, 0.0]])
    faces.insert(256, [515, 516, 517])
    return {
        "vertices": vertices,
        "faces": faces,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic mesh, physical scale not reviewed",
        "relative_scale_uncertainty": 0.1,
    }


def test_patch_preserving_display_recovers_small_hidden_component(
    client: TestClient,
) -> None:
    """Show otherwise hidden disconnected patches without changing scientific data."""
    params = _hidden_small_patch_parameters()
    uniform = measure_mesh_preview(**params, preserve_axis_extrema_in_preview=True)
    pinned = measure_mesh_preview(
        **params,
        preserve_axis_extrema_in_preview=True,
        preserve_edge_connected_patches_in_preview=True,
    )
    assert uniform["edge_connected_patch_face_counts"] == [513, 1]
    assert uniform["preview_omitted_edge_connected_patch_indices"] == [1]
    assert 256 not in uniform["preview_face_indices"]
    assert uniform["preview_omitted_axis_extremum_sides"] == []
    assert uniform["preview_largest_triangle_displayed"] is True
    assert pinned["preview_sampling_strategy"] == "uniform_face_index_extrema_patch_preserving"
    assert pinned["preview_face_count"] == 512
    assert len(set(pinned["preview_face_indices"])) == 512
    assert 256 in pinned["preview_face_indices"]
    assert pinned["preview_edge_connected_patch_face_counts"][1] == 1
    assert pinned["preview_omitted_edge_connected_patch_indices"] == []
    assert "preview_omits_edge_connected_mesh_patches" not in pinned["qc_warnings"]
    assert pinned["preview_omitted_axis_extremum_sides"] == []
    assert pinned["surface_area_m2"] == uniform["surface_area_m2"]
    assert pinned["surface_area_scale_interval_m2"] == uniform["surface_area_scale_interval_m2"]
    assert pinned["axis_aligned_dimensions_m"] == uniform["axis_aligned_dimensions_m"]
    assert pinned["edge_connected_patch_geometry_sha256"] == uniform[
        "edge_connected_patch_geometry_sha256"
    ]
    assert pinned["provenance"]["geometry_sha256"] == uniform["provenance"]["geometry_sha256"]
    assert pinned["provenance"]["calibration_verified"] is False
    assert pinned["measurement_status"] == "caller_supplied_unverified"

    project_id = str(create_project(client, "Patch-preserving mesh preview")["id"])
    base = f"/api/v1/projects/{project_id}"
    request_params = {
        **params,
        "preserve_axis_extrema_in_preview": True,
        "preserve_edge_connected_patches_in_preview": True,
        "specimen_id": "unverified-patch-specimen",
        "observation_id": "unverified-patch-observation",
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=request_params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["preview_face_indices"] == pinned["preview_face_indices"]
    assert expected["surface_area_m2"] == pinned["surface_area_m2"]
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "patch-preserving-sample-v14",
        "name": "Bounded patch-preserving unverified mesh preview",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": request_params},
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
        saved.json()["graph_json"]["nodes"][1]["parameters"][
            "preserve_edge_connected_patches_in_preview"
        ]
        is True
    )
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
        artifact = next(
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        )
        assert artifact["payload_json"] == expected
        hashes.append(artifact["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize("invalid", [1, "true", None])
def test_patch_preserving_preview_requires_strict_boolean(
    client: TestClient, invalid: object
) -> None:
    params = _mesh_parameters(2)
    params["preserve_edge_connected_patches_in_preview"] = invalid
    project_id = str(create_project(client, "Strict patch preview flag")["id"])
    response = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert response.status_code == 422, response.text
