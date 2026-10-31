"""1.4 RGB PLY import: validated color is not a scientific measurement."""

from __future__ import annotations

import hashlib
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import (
    measure_point_cloud_preview,
    parse_ascii_ply_points,
)
from reefvision.tests.test_annotations import create_project

RGB_PLY = (
    "ply\nformat ascii 1.0\nelement vertex 3\n"
    "property uchar blue\nproperty float z\nproperty uchar red\n"
    "property float x\nproperty uchar green\nproperty float y\nend_header\n"
    "255 0 0 0 128 0\n0 0 255 2 64 0\n7 0 11 0 22 3\n"
)


def test_rgb_ply_imports_xyz_without_treating_color_as_geometry() -> None:
    assert parse_ascii_ply_points(RGB_PLY) == [
        [0.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [0.0, 3.0, 0.0],
    ]


@pytest.mark.parametrize(
    "bad",
    [
        RGB_PLY.replace("property uchar red", "property float red"),
        RGB_PLY.replace("property uchar green\n", ""),
        RGB_PLY.replace("255 0 0 0 128 0", "256 0 0 0 128 0"),
        RGB_PLY.replace("255 0 0 0 128 0", "-1 0 0 0 128 0"),
        RGB_PLY.replace("255 0 0 0 128 0", "2.5 0 0 0 128 0"),
        RGB_PLY.replace("255 0 0 0 128 0", "255 nan 0 0 128 0"),
    ],
)
def test_bad_rgb_ply_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_ascii_ply_points(bad)


def test_rgb_ply_standalone_and_saved_workflow_parity(client: TestClient) -> None:
    project_id = str(create_project(client, "RGB point cloud preview")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "ply_text": RGB_PLY,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified reference",
        "relative_scale_uncertainty": 0.1,
        "point_index_pairs": [[0, 1]],
    }
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["preview_point_colors_rgb_uint8"] == [[0, 128, 255], [255, 64, 0], [11, 22, 7]]
    assert expected["measurement_status"] == "caller_supplied_unverified"
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["surface_area_m2"] is None
    original_provenance = expected["provenance"]
    source_digest = hashlib.sha256(RGB_PLY.encode("utf-8")).hexdigest()
    assert original_provenance["source_text_sha256"] == source_digest
    chord = expected["selected_point_chords"][0]
    assert chord["endpoint_coordinates_in_source_frame_m"] == [
        [0.0, 0.0, 0.0],
        [0.02, 0.0, 0.0],
    ]
    assert (
        chord["endpoint_ordered_geometry_sha256"]
        == hashlib.sha256(b"[[0.0,0.0,0.0],[2.0,0.0,0.0]]").hexdigest()
    )
    assert chord["qc_warnings"] == []
    recolored_ply = RGB_PLY.replace("255 0 0 0 128 0", "254 0 0 0 128 0")
    recolored_response = client.post(
        f"{base}/spatial/point-cloud-preview",
        json={**params, "ply_text": recolored_ply},
    )
    assert recolored_response.status_code == 200, recolored_response.text
    assert recolored_response.json()["preview_point_colors_rgb_uint8"][0] == [0, 128, 254]
    recolored_provenance = recolored_response.json()["provenance"]
    assert recolored_provenance["geometry_sha256"] == original_provenance["geometry_sha256"]
    assert recolored_provenance["source_text_sha256"] != source_digest
    assert (
        recolored_response.json()["selected_point_chords"][0]["endpoint_ordered_geometry_sha256"]
        == chord["endpoint_ordered_geometry_sha256"]
    )
    graph = {
        "graph_id": "point-cloud-rgb-v14",
        "name": "RGB point cloud geometry preview",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
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
        a for a in detail.json()["artifacts"] if a["data_type"] == "point_cloud_measurement_preview"
    )
    payload = artifact["payload_json"]
    for key in (
        "axis_aligned_dimensions_m",
        "selected_point_chords",
        "arithmetic_centroid_in_source_frame_m",
        "preview_point_colors_rgb_uint8",
        "provenance",
    ):
        assert payload[key] == expected[key]
    assert payload["project_id"] == project_id
    assert len(artifact["payload_sha256"]) == 64


def test_coincident_point_indices_have_explicit_chord_qc() -> None:
    result = measure_point_cloud_preview(
        points=[[0, 0, 0], [0, 0, 0], [0, 3, 0]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified reference",
        relative_scale_uncertainty=0.1,
        point_index_pairs=[[0, 1], [0, 2]],
    )
    assert result["qc_warnings"] == [
        "duplicate_points_present",
        "coincident_selected_chord_endpoints",
    ]
    coincident, distinct = result["selected_point_chords"]
    assert coincident["point_indices"] == [0, 1]
    assert coincident["chord_distance_m"] == 0
    assert coincident["chord_distance_scale_interval_m"] == [0, 0]
    assert coincident["qc_warnings"] == ["coincident_endpoint_coordinates"]
    assert distinct["chord_distance_m"] == pytest.approx(0.03)
    assert distinct["qc_warnings"] == []
    assert result["branch_length_m"] is None
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_rgb_decimation_retains_source_index_alignment(client: TestClient) -> None:
    project_id = str(create_project(client, "RGB sample threshold")["id"])
    header = (
        "ply\nformat ascii 1.0\nelement vertex 513\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    )
    rows = [f"{i} 0 0 {i % 256} 10 20" for i in range(513)]
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/point-cloud-preview",
        json={
            "ply_text": header + "\n".join(rows) + "\n",
            "meters_per_unit": 0.01,
            "calibration_method": "ruler",
            "calibration_evidence": "Unreviewed field ruler",
            "relative_scale_uncertainty": 0.1,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    indices = result["preview_point_indices"]
    assert len(indices) == 512
    assert indices[0] == 0 and indices[-1] == 512
    assert result["preview_point_colors_rgb_uint8"] == [[i % 256, 10, 20] for i in indices]
    assert result["axis_aligned_dimensions_m"] == pytest.approx([5.12, 0, 0])
    assert result["provenance"]["calibration_verified"] is False
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None


def test_rejected_late_ply_vertex_does_not_modify_existing_colors() -> None:
    colors = [[12, 34, 56]]
    malformed = RGB_PLY.replace("7 0 11 0 22 3", "7 nan 11 0 22 3")
    with pytest.raises(ValueError, match="finite and bounded"):
        parse_ascii_ply_points(malformed, colors_out=colors)
    assert colors == [[12, 34, 56]]
    assert len(parse_ascii_ply_points(RGB_PLY, colors_out=colors)) == 3
    assert colors == [[12, 34, 56], [0, 128, 255], [255, 64, 0], [11, 22, 7]]


def test_rejected_late_rgb_channel_does_not_modify_existing_colors() -> None:
    colors = [[99, 88, 77]]
    malformed = RGB_PLY.replace("7 0 11 0 22 3", "7 0 11 0 256 3")
    with pytest.raises(ValueError, match="0-255 integers"):
        parse_ascii_ply_points(malformed, colors_out=colors)
    assert colors == [[99, 88, 77]]


def test_colorless_ply_preserves_caller_color_buffer() -> None:
    colors = [[99, 88, 77]]
    colorless = (
        "ply\nformat ascii 1.0\nelement vertex 1\n"
        "property float x\nproperty float y\nproperty float z\n"
        "end_header\n1 2 3\n"
    )
    assert parse_ascii_ply_points(colorless, colors_out=colors) == [[1.0, 2.0, 3.0]]
    assert colors == [[99, 88, 77]]


def test_rgb_2000_vertices_atomic_on_invalid_last_channel() -> None:
    colors = [[42, 43, 44]]
    header = (
        "ply\nformat ascii 1.0\nelement vertex 2000\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    )
    rows = [f"{i} 0 0 10 20 30" for i in range(1999)]
    invalid = header + "\n".join([*rows, "1999 0 0 10 20 256"]) + "\n"
    with pytest.raises(ValueError, match="0-255 integers"):
        parse_ascii_ply_points(invalid, colors_out=colors)
    assert colors == [[42, 43, 44]]
    valid = header + "\n".join([*rows, "1999 0 0 10 20 30"]) + "\n"
    assert len(parse_ascii_ply_points(valid, colors_out=colors)) == 2000
    assert len(colors) == 2001
    assert colors[0] == [42, 43, 44]
    assert colors[-1] == [10, 20, 30]
