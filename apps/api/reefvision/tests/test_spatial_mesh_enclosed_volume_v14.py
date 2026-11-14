"""Scientific volume gating and persisted Workflow Builder parity for 1.4."""

from __future__ import annotations

from math import sqrt
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

TETRA_FACES = [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]
TETRA_VERTICES = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]


def _params(
    *,
    vertices: list[list[float]] | None = None,
    faces: list[list[int]] | None = None,
    uncertainty: float | None = 0.1,
) -> dict:
    return {
        "vertices": vertices if vertices is not None else TETRA_VERTICES,
        "faces": faces if faces is not None else TETRA_FACES,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed field scale",
        "relative_scale_uncertainty": uncertainty,
    }


def test_closed_tetrahedron_volume_and_exact_cubic_scale_bounds() -> None:
    result = measure_mesh_preview(**_params())
    volume = 0.01**3 / 6
    assert result["enclosed_volume_m3"] == pytest.approx(volume)
    assert result["edge_connected_patch_enclosed_volumes_m3"] == pytest.approx([volume])
    assert result["enclosed_volume_scale_interval_m3"] == pytest.approx(
        [volume * 0.9**3, volume * 1.1**3]
    )
    assert result["edge_connected_patch_enclosed_volume_scale_intervals_m3"][0] == pytest.approx(
        [volume * 0.9**3, volume * 1.1**3]
    )
    assert result["enclosed_volume_is_provisional"] is True
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_closed_tetrahedron_surface_volume_ratio_and_inverse_scale_bounds() -> None:
    result = measure_mesh_preview(**_params())
    expected = (3 + sqrt(3)) * 3 / 0.01
    assert result["surface_to_enclosed_volume_ratio_per_m"] == pytest.approx(expected)
    assert result["edge_connected_patch_surface_to_enclosed_volume_ratios_per_m"] == pytest.approx(
        [expected]
    )
    assert result["surface_to_enclosed_volume_ratio_scale_interval_per_m"] == pytest.approx(
        [expected / 1.1, expected / 0.9]
    )
    assert result["edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m"][
        0
    ] == pytest.approx([expected / 1.1, expected / 0.9])
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("uncertainty", [None, 0.0, 1.0])
def test_surface_volume_ratio_bounds_do_not_invent_finite_uncertainty(
    uncertainty: float | None,
) -> None:
    result = measure_mesh_preview(**_params(uncertainty=uncertainty))
    ratio = result["surface_to_enclosed_volume_ratio_per_m"]
    assert ratio is not None
    interval = result["surface_to_enclosed_volume_ratio_scale_interval_per_m"]
    if uncertainty == 0:
        assert interval == pytest.approx([ratio, ratio])
    else:
        assert interval is None
    patch_intervals = result[
        "edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m"
    ]
    if uncertainty is None:
        assert patch_intervals is None
    elif uncertainty == 1:
        assert patch_intervals == [None]
    else:
        assert patch_intervals[0] == pytest.approx([ratio, ratio])


def test_open_and_inconsistent_meshes_withhold_volume() -> None:
    for faces in (TETRA_FACES[:-1], [[0, 1, 2], *TETRA_FACES[1:]]):
        result = measure_mesh_preview(**_params(faces=faces))
        assert result["enclosed_volume_m3"] is None
        assert result["edge_connected_patch_enclosed_volumes_m3"] == [None]
        assert result["enclosed_volume_scale_interval_m3"] is None
        assert result["surface_to_enclosed_volume_ratio_per_m"] is None
        assert result["surface_to_enclosed_volume_ratio_scale_interval_per_m"] is None
        assert result["edge_connected_patch_surface_to_enclosed_volume_ratios_per_m"] == [None]
        assert (
            "enclosed_volume_requires_closed_oriented_nondegenerate_patch"
            in (result["qc_warnings"])
        )


def test_translation_and_inward_winding_preserve_unsigned_volume() -> None:
    shifted = [[v + 100_000_000 for v in point] for point in TETRA_VERTICES]
    result = measure_mesh_preview(
        **_params(vertices=shifted, faces=[list(reversed(face)) for face in TETRA_FACES])
    )
    assert result["enclosed_volume_m3"] == pytest.approx(0.01**3 / 6)


def test_open_patch_does_not_hide_valid_disconnected_patch_volume() -> None:
    vertices = [*TETRA_VERTICES, [3, 0, 0], [4, 0, 0], [3, 1, 0]]
    faces = [*TETRA_FACES, [4, 5, 6]]
    result = measure_mesh_preview(**_params(vertices=vertices, faces=faces))
    assert result["edge_connected_patch_enclosed_volumes_m3"][0] == pytest.approx(0.01**3 / 6)
    assert result["edge_connected_patch_enclosed_volumes_m3"][1] is None
    assert result["enclosed_volume_m3"] is None
    assert result["surface_to_enclosed_volume_ratio_per_m"] is None
    assert result["edge_connected_patch_surface_to_enclosed_volume_ratios_per_m"][0] is not None
    assert result["edge_connected_patch_surface_to_enclosed_volume_ratios_per_m"][1] is None


def test_open_disconnected_patch_preserves_volume_and_topology_qc() -> None:
    vertices = [*TETRA_VERTICES, [3, 0, 0], [4, 0, 0], [3, 1, 0]]
    faces = [*TETRA_FACES, [4, 5, 6]]
    result = measure_mesh_preview(**_params(vertices=vertices, faces=faces))
    warnings = result["qc_warnings"]
    assert "enclosed_volume_requires_closed_oriented_nondegenerate_patch" in warnings
    assert "open_mesh_surface_not_enclosed" in warnings
    assert "disconnected_mesh_patches" in warnings
    assert len(warnings) == len(set(warnings))
    assert result["enclosed_volume_m3"] is None
    assert result["edge_connected_patch_enclosed_volumes_m3"][0] == pytest.approx(0.01**3 / 6)


def test_mesh_patch_euler_counts_are_source_topology_not_genus() -> None:
    for faces, expected_euler in ((TETRA_FACES, 2), (TETRA_FACES[:-1], 1)):
        result = measure_mesh_preview(**_params(faces=faces))
        assert result["edge_connected_patch_vertex_counts"] == [4]
        assert result["edge_connected_patch_edge_counts"] == [6]
        assert result["edge_connected_patch_face_counts"] == [len(faces)]
        assert result["edge_connected_patch_euler_characteristics"] == [expected_euler]
        assert result["measurement_status"] == "caller_supplied_unverified"


def test_vertex_touching_patches_keep_separate_euler_diagnostics() -> None:
    vertices = [*TETRA_VERTICES, [2, 0, 0], [0, 2, 0]]
    faces = [*TETRA_FACES, [0, 4, 5]]
    result = measure_mesh_preview(**_params(vertices=vertices, faces=faces))
    assert result["edge_connected_patch_count"] == 2
    assert result["edge_connected_patch_vertex_counts"] == [4, 3]
    assert result["edge_connected_patch_edge_counts"] == [6, 3]
    assert result["edge_connected_patch_euler_characteristics"] == [2, 1]
    assert result["enclosed_volume_m3"] is None


def test_missing_scale_uncertainty_does_not_invent_bounds() -> None:
    result = measure_mesh_preview(**_params(uncertainty=None))
    assert result["enclosed_volume_m3"] == pytest.approx(0.01**3 / 6)
    assert result["enclosed_volume_scale_interval_m3"] is None
    assert result["edge_connected_patch_enclosed_volume_scale_intervals_m3"] is None


@pytest.mark.parametrize("faces", [TETRA_FACES, TETRA_FACES[:-1]], ids=["closed", "open"])
def test_standalone_and_persisted_workflow_volume_parity(
    client: TestClient, faces: list[list[int]]
) -> None:
    project_id = str(create_project(client, "Mesh volume parity")["id"])
    params = _params(faces=faces)
    params.update(
        specimen_id="swiftia-001",
        observation_id="survey-2026-10-24-001",
        observed_at_utc="2026-10-24T10:00:00-04:00",
    )
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    graph = {
        "graph_id": "mesh-enclosed-volume-v14",
        "name": "Provisional enclosed volume",
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
        "enclosed_volume_m3",
        "edge_connected_patch_enclosed_volumes_m3",
        "enclosed_volume_scale_interval_m3",
        "edge_connected_patch_enclosed_volume_scale_intervals_m3",
        "enclosed_volume_is_provisional",
        "surface_to_enclosed_volume_ratio_per_m",
        "surface_to_enclosed_volume_ratio_scale_interval_per_m",
        "edge_connected_patch_surface_to_enclosed_volume_ratios_per_m",
        "edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m",
        "edge_connected_patch_vertex_counts",
        "edge_connected_patch_edge_counts",
        "edge_connected_patch_euler_characteristics",
        "qc_warnings",
    ):
        assert artifact[key] == standalone.json()[key]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False
    assert artifact["provenance"] == standalone.json()["provenance"]
    assert artifact["provenance"]["specimen_id"] == "swiftia-001"
    assert artifact["provenance"]["observation_id"] == "survey-2026-10-24-001"
    assert artifact["provenance"]["observed_at_utc"] == "2026-10-24T14:00:00Z"
    assert artifact["provenance"]["specimen_identity_verified"] is False
    assert artifact["provenance"]["observation_metadata_verified"] is False
    if len(faces) == 3:
        assert artifact["enclosed_volume_m3"] is None
        assert (
            "enclosed_volume_requires_closed_oriented_nondegenerate_patch"
            in artifact["qc_warnings"]
        )


def test_mesh_observation_metadata_rejects_naive_time_and_invalid_identity(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Mesh observation metadata")["id"])
    endpoint = f"/api/v1/projects/{project_id}/spatial/mesh-preview"
    for invalid in (
        {"observed_at_utc": "2026-10-24T14:00:00"},
        {"specimen_id": "   "},
    ):
        response = client.post(endpoint, json={**_params(), **invalid})
        assert response.status_code == 422, response.text
