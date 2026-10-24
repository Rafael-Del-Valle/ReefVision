"""Scientific volume gating and persisted Workflow Builder parity for 1.4."""

from __future__ import annotations

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
    assert result["edge_connected_patch_enclosed_volume_scale_intervals_m3"][0] == (
        pytest.approx([volume * 0.9**3, volume * 1.1**3])
    )
    assert result["enclosed_volume_is_provisional"] is True
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_open_and_inconsistent_meshes_withhold_volume() -> None:
    for faces in (TETRA_FACES[:-1], [[0, 1, 2], *TETRA_FACES[1:]]):
        result = measure_mesh_preview(**_params(faces=faces))
        assert result["enclosed_volume_m3"] is None
        assert result["edge_connected_patch_enclosed_volumes_m3"] == [None]
        assert result["enclosed_volume_scale_interval_m3"] is None
        assert "enclosed_volume_requires_closed_oriented_nondegenerate_patch" in (
            result["qc_warnings"]
        )


def test_translation_and_inward_winding_preserve_unsigned_volume() -> None:
    shifted = [[v + 100_000_000 for v in point] for point in TETRA_VERTICES]
    result = measure_mesh_preview(
        **_params(vertices=shifted, faces=[list(reversed(face)) for face in TETRA_FACES])
    )
    assert result["enclosed_volume_m3"] == pytest.approx(0.01**3 / 6)


def test_open_patch_does_not_hide_valid_disconnected_patch_volume() -> None:
    vertices = TETRA_VERTICES + [[3, 0, 0], [4, 0, 0], [3, 1, 0]]
    faces = TETRA_FACES + [[4, 5, 6]]
    result = measure_mesh_preview(**_params(vertices=vertices, faces=faces))
    assert result["edge_connected_patch_enclosed_volumes_m3"][0] == pytest.approx(
        0.01**3 / 6
    )
    assert result["edge_connected_patch_enclosed_volumes_m3"][1] is None
    assert result["enclosed_volume_m3"] is None


def test_missing_scale_uncertainty_does_not_invent_bounds() -> None:
    result = measure_mesh_preview(**_params(uncertainty=None))
    assert result["enclosed_volume_m3"] == pytest.approx(0.01**3 / 6)
    assert result["enclosed_volume_scale_interval_m3"] is None
    assert result["edge_connected_patch_enclosed_volume_scale_intervals_m3"] is None


def test_standalone_and_persisted_workflow_volume_parity(client: TestClient) -> None:
    project_id = str(create_project(client, "Mesh volume parity")["id"])
    params = _params()
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
        "qc_warnings",
    ):
        assert artifact[key] == standalone.json()[key]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False
