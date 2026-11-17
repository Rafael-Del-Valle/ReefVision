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
    assert expected["source_affine_dimension"] == 2
    assert expected["qc_warnings"] == ["source_point_cloud_affine_dimension_below_3"]
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
        "source_affine_dimension",
        "qc_warnings",
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
        "nonuniform_duplicate_coordinates_can_bias_row_centroid",
        "coincident_selected_chord_endpoints",
        "source_point_cloud_affine_dimension_below_3",
    ]
    assert result["point_count"] == 3
    assert result["unique_point_count"] == 2
    assert result["duplicate_point_row_count"] == 1
    assert result["duplicate_point_row_fraction"] == pytest.approx(1 / 3)
    assert result["maximum_coordinate_multiplicity"] == 2
    assert result["arithmetic_centroid_in_source_frame_m"] == pytest.approx([0, 0.01, 0])
    assert result["unique_coordinate_centroid_in_source_frame_m"] == pytest.approx([0, 0.015, 0])
    assert result["row_vs_unique_coordinate_centroid_separation_m"] == pytest.approx(0.005)
    assert result["row_vs_unique_coordinate_centroid_separation_scale_interval_m"] == pytest.approx(
        [0.0045, 0.0055]
    )
    assert result["source_affine_dimension"] == 1
    assert result["axis_aligned_bounding_box_envelope_volume_m3"] == 0.0
    coincident, distinct = result["selected_point_chords"]
    assert coincident["point_indices"] == [0, 1]
    assert coincident["chord_distance_m"] == 0
    assert coincident["chord_distance_scale_interval_m"] == [0, 0]
    assert coincident["qc_warnings"] == ["coincident_endpoint_coordinates"]
    assert distinct["chord_distance_m"] == pytest.approx(0.03)
    assert distinct["qc_warnings"] == []
    assert result["branch_length_m"] is None
    assert result["measurement_status"] == "caller_supplied_unverified"


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_duplicate_centroid_qc_standalone_and_persisted_workflow(
    client: TestClient, source_format: str
) -> None:
    """Nonuniform acquisition rows must retain explicit unverified centroid QC."""
    project_id = str(create_project(client, "Repeated scan locus QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified scan ruler",
        "relative_scale_uncertainty": 0.1,
        "point_index_pairs": [[0, 1], [0, 2]],
    }
    if source_format == "xyz":
        params["points"] = [[0, 0, 0], [0, 0, 0], [0, 3, 0]]
    else:
        params["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 3\n"
            "property float x\nproperty float y\nproperty float z\nend_header\n"
            "0 0 0\n0 0 0\n0 3 0\n"
        )

    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["duplicate_point_row_fraction"] == pytest.approx(1 / 3)
    assert expected["unique_point_count"] == 2
    assert expected["arithmetic_centroid_in_source_frame_m"] == pytest.approx([0, 0.01, 0])
    assert expected["unique_coordinate_centroid_in_source_frame_m"] == pytest.approx([0, 0.015, 0])
    assert expected["row_vs_unique_coordinate_centroid_separation_m"] == pytest.approx(0.005)
    assert expected["qc_warnings"] == [
        "duplicate_points_present",
        "nonuniform_duplicate_coordinates_can_bias_row_centroid",
        "coincident_selected_chord_endpoints",
        "source_point_cloud_affine_dimension_below_3",
    ]
    assert expected["measurement_status"] == "caller_supplied_unverified"
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["surface_area_m2"] is None
    assert expected["branch_length_m"] is None

    graph = {
        "graph_id": f"duplicate-centroid-{source_format}-v14",
        "name": "Repeated scan locus centroid QC",
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
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    digests = []
    for _ in range(2):
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
            if item["data_type"] == "point_cloud_measurement_preview"
        )
        payload = artifact["payload_json"]
        for key in (
            "point_count",
            "unique_point_count",
            "duplicate_point_row_count",
            "duplicate_point_row_fraction",
            "arithmetic_centroid_in_source_frame_m",
            "unique_coordinate_centroid_in_source_frame_m",
            "row_vs_unique_coordinate_centroid_separation_m",
            "row_vs_unique_coordinate_centroid_separation_scale_interval_m",
            "qc_warnings",
            "measurement_status",
            "provenance",
            "surface_area_m2",
            "branch_length_m",
        ):
            assert payload[key] == expected[key]
        assert payload["project_id"] == project_id
        digests.append(artifact["payload_sha256"])
    assert len(set(digests)) == 1
    assert len(digests[0]) == 64


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
    # Nonfinite PLY tokens now fail strict numeric grammar before float conversion.
    with pytest.raises(ValueError, match="Invalid point-cloud coordinate"):
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


@pytest.mark.parametrize(
    "channel",
    ["0000", "0" * 5000],
    ids=["four_digit_channel", "oversized_zero_channel"],
)
def test_noncanonical_rgb_token_fails_standalone_and_saved_graph(
    client: TestClient, channel: str
) -> None:
    """Reject oversized RGB tokens without publishing scientific point-cloud artifacts."""
    invalid = RGB_PLY.replace("7 0 11 0 22 3", f"7 0 11 0 {channel} 3")
    colors = [[10, 20, 30]]
    with pytest.raises(ValueError, match="0-255 integers"):
        parse_ascii_ply_points(invalid, colors_out=colors)
    assert colors == [[10, 20, 30]]

    pid = str(create_project(client, "Bounded RGB token import")["id"])
    base = f"/api/v1/projects/{pid}"
    params = {
        "ply_text": invalid,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Provisional field ruler",
    }
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 400, standalone.text

    graph = {
        "graph_id": "bounded-rgb-token-v14",
        "name": "Reject noncanonical RGB PLY",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "c", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "c",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "point_cloud_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )


def test_three_digit_zero_rgb_token_remains_valid() -> None:
    """A bounded decimal representation is still a valid unsigned-byte color."""
    valid = RGB_PLY.replace("7 0 11 0 22 3", "7 0 11 0 000 3")
    colors: list[list[int]] = []
    assert parse_ascii_ply_points(valid, colors_out=colors) == parse_ascii_ply_points(RGB_PLY)
    assert colors[-1] == [11, 0, 7]


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_resampled_loci_stay_distinct_from_biological_change_in_saved_workflows(
    client: TestClient, source_format: str
) -> None:
    """Repeated acquisition rows alter centroids, not unique spatial loci."""
    project_id = str(create_project(client, "Acquisition resampling integrity")["id"])
    base = f"/api/v1/projects/{project_id}"
    original = [[0, 0, 0], [4, 0, 0], [0, 2, 0]]
    resampled = [[0, 0, 0], [0, 0, 0], [4, 0, 0], [0, 2, 0]]
    measured = []
    for label, points in (("original", original), ("resampled", resampled)):
        params = {
            "meters_per_unit": 0.01,
            "calibration_method": "ruler",
            "calibration_evidence": "Provisional scale; no identity review",
            "relative_scale_uncertainty": 0.1,
        }
        if source_format == "xyz":
            params["points"] = points
        else:
            header = (
                "ply\nformat ascii 1.0\n"
                f"element vertex {len(points)}\n"
                "property float x\nproperty float y\n"
                "property float z\nend_header\n"
            )
            rows = "".join(f"{x} {y} {z}\n" for x, y, z in points)
            params["ply_text"] = header + rows
        response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
        assert response.status_code == 200, response.text
        expected = response.json()
        assert expected["measurement_status"] == "caller_supplied_unverified"
        assert expected["provenance"]["calibration_verified"] is False
        assert expected["surface_area_m2"] is None
        assert expected["branch_length_m"] is None
        graph = {
            "graph_id": f"acquisition-resample-{source_format}-{label}",
            "name": "Acquisition row multiplicity QC",
            "nodes": [
                {"node_id": "p", "node_type": "project_source"},
                {
                    "node_id": "c",
                    "node_type": "point_cloud_preview",
                    "parameters": params,
                },
            ],
            "edges": [
                {
                    "edge_id": "e",
                    "source_node_id": "p",
                    "source_port_id": "project",
                    "target_node_id": "c",
                    "target_port_id": "project",
                }
            ],
        }
        plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
        assert plan.status_code == 200, plan.text
        assert plan.json()["executable"] is True
        saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
        assert saved.status_code == 201, saved.text
        digests = []
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
                item for item in detail.json()["artifacts"]
                if item["data_type"] == "point_cloud_measurement_preview"
            )
            for key in (
                "provenance",
                "qc_warnings",
                "point_count",
                "unique_point_count",
                "arithmetic_centroid_in_source_frame_m",
                "unique_coordinate_centroid_in_source_frame_m",
                "axis_aligned_dimensions_m",
                "measurement_status",
            ):
                assert artifact["payload_json"][key] == expected[key]
            digests.append(artifact["payload_sha256"])
        assert len(set(digests)) == 1
        measured.append(expected)

    first, repeated = measured
    assert first["point_count"] == 3
    assert repeated["point_count"] == 4
    assert first["unique_point_count"] == repeated["unique_point_count"] == 3
    assert first["axis_aligned_dimensions_m"] == repeated["axis_aligned_dimensions_m"]
    assert first["provenance"]["unique_coordinate_geometry_sha256"] == (
        repeated["provenance"]["unique_coordinate_geometry_sha256"]
    )
    first_hash = first["provenance"]["geometry_sha256"]
    repeated_hash = repeated["provenance"]["geometry_sha256"]
    assert first_hash != repeated_hash
    if source_format == "ply":
        assert first["provenance"]["source_text_sha256"] != (
            repeated["provenance"]["source_text_sha256"]
        )
    assert first["arithmetic_centroid_in_source_frame_m"] != (
        repeated["arithmetic_centroid_in_source_frame_m"]
    )
    assert first["unique_coordinate_centroid_in_source_frame_m"] == (
        repeated["unique_coordinate_centroid_in_source_frame_m"]
    )
    warning = "nonuniform_duplicate_coordinates_can_bias_row_centroid"
    assert warning in repeated["qc_warnings"]
    assert warning not in first["qc_warnings"]
