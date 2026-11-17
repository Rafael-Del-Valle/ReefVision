"""Scientific regression: unordered cloud identity is not ordered point identity."""

from __future__ import annotations

import hashlib
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project


def _preview(points: list[list[float]]) -> dict:
    return measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Unverified source-frame ruler",
        relative_scale_uncertainty=0.1,
        point_index_pairs=[[0, 1]],
    )


def test_permuted_cloud_retains_geometry_hash_but_not_point_order() -> None:
    original = _preview([[-2.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 4.0, 0.0]])
    permuted = _preview([[1.0, 4.0, 0.0], [-2.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

    assert original["provenance"]["geometry_sha256"] == permuted["provenance"]["geometry_sha256"]
    assert (
        original["provenance"]["ordered_geometry_sha256"]
        != permuted["provenance"]["ordered_geometry_sha256"]
    )
    assert original["axis_aligned_dimensions_m"] == pytest.approx(
        permuted["axis_aligned_dimensions_m"]
    )
    assert original["selected_point_chords"][0]["chord_distance_m"] == pytest.approx(0.3)
    assert permuted["selected_point_chords"][0]["chord_distance_m"] == pytest.approx(0.5)
    assert original["selected_point_chords"][0]["chord_distance_scale_interval_m"] == pytest.approx(
        [0.27, 0.33]
    )
    assert permuted["selected_point_chords"][0]["chord_distance_scale_interval_m"] == pytest.approx(
        [0.45, 0.55]
    )
    assert original["measurement_status"] == "caller_supplied_unverified"
    assert permuted["provenance"]["coordinate_registration_verified"] is False
    assert original["branch_length_m"] is None
    assert permuted["surface_area_m2"] is None


@pytest.mark.parametrize(
    "source_format",
    ["xyz", "ply", "ply_rgb", "ply_rgb_colors_only", "ply_rgb_signed_only"],
)
def test_signed_zero_is_not_a_new_specimen_geometry_in_saved_workflow(
    client: TestClient, source_format: str
) -> None:
    """Separately vary signed zeros and RGB across API and persisted workflows."""
    canonical_points = [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 1.0]]
    signed_points = [[-0.0, 0.0, -0.0], [2.0, -0.0, 0.0], [0.0, 3.0, 1.0]]
    canonical_direct = _preview(canonical_points)
    signed_direct = _preview(signed_points)
    for key in ("geometry_sha256", "ordered_geometry_sha256"):
        assert canonical_direct["provenance"][key] == signed_direct["provenance"][key]
    assert (
        canonical_direct["selected_point_chords"][0]["endpoint_ordered_geometry_sha256"]
        == signed_direct["selected_point_chords"][0]["endpoint_ordered_geometry_sha256"]
    )
    assert canonical_direct == signed_direct

    params = {
        "meters_per_unit": 0.1,
        "calibration_method": "ruler",
        "calibration_evidence": "Signed-zero synthetic reference, calibration unverified",
        "relative_scale_uncertainty": 0.1,
        "point_index_pairs": [[0, 1]],
    }
    if source_format == "xyz":
        canonical_params = {**params, "points": canonical_points}
        signed_params = {**params, "points": signed_points}
    else:
        colored = source_format.startswith("ply_rgb")
        header = (
            "ply\nformat ascii 1.0\nelement vertex 3\n"
            "property double x\nproperty double y\nproperty double z\n"
        )
        if colored:
            header += "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        header += "end_header\n"
        if colored:
            canonical_text = header + "0 0 0 12 34 56\n2 0 0 65 43 21\n0 3 1 7 8 9\n"
            is_color_only = source_format == "ply_rgb_colors_only"
            is_signed_only = source_format == "ply_rgb_signed_only"
            source_zero = "0 0 0" if is_color_only else "-0 0 -0"
            source_two = "2 0 0" if is_color_only else "2 -0 0"
            first_rgb = "12 34 56" if is_signed_only else "120 34 56"
            signed_text = (
                header
                + f"{source_zero} {first_rgb}\n"
                + f"{source_two} 65 43 21\n"
                + "0 3 1 7 8 9\n"
            )
        else:
            canonical_text = header + "0 0 0\n2 0 0\n0 3 1\n"
            signed_text = header + "-0 0 -0\n2 -0 0\n0 3 1\n"
        canonical_params = {**params, "ply_text": canonical_text}
        signed_params = {**params, "ply_text": signed_text}

    project_id = str(create_project(client, "Signed-zero geometry identity")["id"])
    base = f"/api/v1/projects/{project_id}"
    clean_response = client.post(f"{base}/spatial/point-cloud-preview", json=canonical_params)
    signed_response = client.post(f"{base}/spatial/point-cloud-preview", json=signed_params)
    assert clean_response.status_code == 200, clean_response.text
    assert signed_response.status_code == 200, signed_response.text
    clean, signed = clean_response.json(), signed_response.json()
    for key in ("geometry_sha256", "ordered_geometry_sha256"):
        assert clean["provenance"][key] == signed["provenance"][key]
    assert clean["selected_point_chords"] == signed["selected_point_chords"]
    for field in (
        "axis_aligned_dimensions_m",
        "axis_aligned_bounding_box_envelope_volume_m3",
        "arithmetic_centroid_in_source_frame_m",
        "qc_warnings",
    ):
        assert clean[field] == signed[field]
    assert clean["source_affine_dimension"] == signed["source_affine_dimension"] == 2
    assert (
        "positive_bounding_envelope_for_lower_dimensional_source" in signed["qc_warnings"]
    )
    assert signed["provenance"]["calibration_verified"] is False
    assert signed["provenance"]["specimen_identity_verified"] is False
    assert signed["surface_area_m2"] is None
    assert signed["branch_length_m"] is None
    if source_format != "xyz":
        assert (
            clean["provenance"]["source_text_sha256"] != signed["provenance"]["source_text_sha256"]
        )
        assert (
            signed["provenance"]["source_text_sha256"]
            == hashlib.sha256(signed_params["ply_text"].encode("utf-8")).hexdigest()
        )
    else:
        assert signed["provenance"]["source_text_sha256"] is None
    if source_format.startswith("ply_rgb"):
        clean_colors = clean["preview_point_colors_rgb_uint8"]
        modified_colors = signed["preview_point_colors_rgb_uint8"]
        assert clean_colors == [[12, 34, 56], [65, 43, 21], [7, 8, 9]]
        if source_format == "ply_rgb_signed_only":
            assert modified_colors == clean_colors
        else:
            assert modified_colors == [[120, 34, 56], [65, 43, 21], [7, 8, 9]]
            assert clean_colors != modified_colors
    else:
        assert clean["preview_point_colors_rgb_uint8"] is None
        assert signed["preview_point_colors_rgb_uint8"] is None

    graph = {
        "graph_id": f"signed-zero-geometry-{source_format}-v14",
        "name": "Signed-zero imported geometry identity",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "cloud",
                "node_type": "point_cloud_preview",
                "parameters": signed_params,
            },
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
        assert artifact["payload_json"] == signed
        assert artifact["payload_json"]["measurement_status"] == "caller_supplied_unverified"
        assert len(artifact["payload_sha256"]) == 64
