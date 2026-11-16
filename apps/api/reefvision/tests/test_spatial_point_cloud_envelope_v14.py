"""Point-cloud envelope uncertainty and saved-graph parity for 1.4."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project


def test_calibrated_envelope_and_scale_interval() -> None:
    result = measure_point_cloud_preview(
        points=[[0, 0, 0], [2, 3, 4]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified ruler",
        relative_scale_uncertainty=0.1,
    )
    volume = 0.02 * 0.03 * 0.04
    assert result["axis_aligned_bounding_box_envelope_volume_m3"] == pytest.approx(volume)
    interval = result["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"]
    assert interval == pytest.approx([volume * 0.9**3, volume * 1.1**3])
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("uncertainty", [None, 0.0, 0.1, 1.0])
def test_degenerate_cloud_envelope(uncertainty: float | None) -> None:
    result = measure_point_cloud_preview(
        points=[[0, 0, 0], [2, 3, 0]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified ruler",
        relative_scale_uncertainty=uncertainty,
    )
    assert result["axis_aligned_bounding_box_envelope_volume_m3"] == 0
    interval = result["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"]
    if uncertainty is None:
        assert interval is None
    else:
        assert interval == [0, 0]


def test_envelope_saved_workflow_matches_standalone(client: TestClient) -> None:
    project_id = str(create_project(client, "Envelope preview")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "points": [[0, 0, 0], [2, 3, 4]],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified ruler",
        "relative_scale_uncertainty": 0.1,
    }
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    graph = {
        "graph_id": "point-cloud-envelope-v14",
        "name": "Point cloud envelope",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "cloud",
                "node_type": "point_cloud_preview",
                "parameters": params,
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
    assert (
        payload["axis_aligned_bounding_box_envelope_volume_m3"]
        == (expected["axis_aligned_bounding_box_envelope_volume_m3"])
    )
    assert (
        payload["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"]
        == (expected["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"])
    )
    assert payload["provenance"] == expected["provenance"]
    assert payload["project_id"] == project_id
    assert payload["measurement_status"] == "caller_supplied_unverified"


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_subnormal_envelope_is_unknown_with_saved_workflow_parity(
    client: TestClient, source_format: str
) -> None:
    """A 3D cloud is not planar merely because its volume underflows."""
    project_id = str(create_project(client, f"Subnormal envelope {source_format}")["id"])
    base = f"/api/v1/projects/{project_id}"
    geometry = (
        {"points": [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]}
        if source_format == "xyz"
        else {
            "ply_text": (
                "ply\nformat ascii 1.0\nelement vertex 2\n"
                "property double x\nproperty double y\nproperty double z\n"
                "end_header\n0 0 0\n1 1 1\n"
            )
        }
    )
    params = {
        **geometry,
        "meters_per_unit": 1e-110,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic numeric test; not a verified instrument",
        "relative_scale_uncertainty": 0.1,
    }
    direct_service = measure_point_cloud_preview(
        points=[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]],
        meters_per_unit=1e-110,
        calibration_method="ruler",
        calibration_evidence=params["calibration_evidence"],
        relative_scale_uncertainty=0.1,
    )
    assert direct_service["axis_aligned_dimensions_m"] == [1e-110] * 3
    assert direct_service["axis_aligned_bounding_box_envelope_volume_m3"] is None
    assert direct_service["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"] is None
    assert "envelope_volume_below_numeric_resolution" in direct_service["qc_warnings"]

    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["axis_aligned_bounding_box_envelope_volume_m3"] is None
    assert expected["qc_warnings"] == direct_service["qc_warnings"]
    assert expected["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": f"subnormal-envelope-{source_format}",
        "name": "Do not misreport an underflowed envelope as planar",
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
    payload = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    assert payload == expected


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_positive_envelope_uncertainty_lower_bound_underflow_is_unknown(
    client: TestClient, source_format: str
) -> None:
    """A positive 3D envelope must not gain a false zero lower bound."""
    scale = 1.7e-108
    points = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]
    direct = measure_point_cloud_preview(
        points=points,
        meters_per_unit=scale,
        calibration_method="ruler",
        calibration_evidence="Synthetic numerical boundary; unverified",
        relative_scale_uncertainty=0.5,
    )
    volume = direct["axis_aligned_bounding_box_envelope_volume_m3"]
    assert volume is not None and volume > 0.0
    assert volume * 0.5**3 == 0.0
    assert direct["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"] is None
    assert "envelope_uncertainty_interval_below_numeric_resolution" in direct["qc_warnings"]
    assert "envelope_volume_below_numeric_resolution" not in direct["qc_warnings"]
    assert direct["measurement_status"] == "caller_supplied_unverified"

    project_id = str(create_project(client, f"Envelope interval {source_format}")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic numerical boundary; unverified",
        "relative_scale_uncertainty": 0.5,
    }
    if source_format == "xyz":
        params["points"] = points
    else:
        params["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 2\n"
            "property double x\nproperty double y\nproperty double z\n"
            "end_header\n0 0 0\n1 1 1\n"
        )
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["axis_aligned_bounding_box_envelope_volume_m3"] == volume
    assert expected["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"] is None
    assert expected["qc_warnings"] == direct["qc_warnings"]
    assert expected["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": f"envelope-interval-underflow-{source_format}",
        "name": "Do not invent a zero lower uncertainty bound",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "cloud",
                "node_type": "point_cloud_preview",
                "parameters": params,
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
    payload = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    assert payload == expected


@pytest.mark.parametrize(
    ("scale", "uncertainty", "lower_is_exact_zero"),
    [(1.7e-108, 1.0, True), (3e-108, 0.5, False)],
)
def test_envelope_scale_interval_retains_representable_and_true_zero_bounds(
    scale: float, uncertainty: float, lower_is_exact_zero: bool
) -> None:
    """A zero lower scale factor is valid, not floating-point precision loss."""
    result = measure_point_cloud_preview(
        points=[[0, 0, 0], [1, 1, 1]],
        meters_per_unit=scale,
        calibration_method="ruler",
        calibration_evidence="Synthetic scale-only uncertainty; unverified",
        relative_scale_uncertainty=uncertainty,
    )
    bounds = result["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"]
    assert bounds is not None
    assert (bounds[0] == 0.0) is lower_is_exact_zero
    assert bounds[1] > 0.0
    assert "envelope_uncertainty_interval_below_numeric_resolution" not in result["qc_warnings"]


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_positive_chord_lower_interval_underflow_is_unresolved_in_saved_workflow(
    client: TestClient, source_format: str
) -> None:
    """Do not turn a positive calibrated chord's uncertainty bound into zero."""
    scale = 1e-323
    uncertainty = 0.9
    points = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    direct = measure_point_cloud_preview(
        points=points,
        meters_per_unit=scale,
        calibration_method="ruler",
        calibration_evidence="Synthetic underflow boundary; not a verified calibration",
        relative_scale_uncertainty=uncertainty,
        point_index_pairs=[[0, 1]],
    )
    chord = direct["selected_point_chords"][0]
    assert chord["chord_distance_m"] == scale
    assert chord["chord_distance_m"] * (1 - uncertainty) == 0.0
    assert chord["chord_distance_scale_interval_m"] is None
    assert "chord_uncertainty_interval_below_numeric_resolution" in chord["qc_warnings"]
    assert "selected_chord_uncertainty_interval_below_numeric_resolution" in direct["qc_warnings"]
    assert direct["provenance"]["calibration_verified"] is False

    # A mathematically zero lower bound and representable positive lower bound
    # must remain distinguishable from floating-point loss of precision.
    for valid_uncertainty, zero_lower_bound in [(1.0, True), (0.5, False)]:
        valid = measure_point_cloud_preview(
            points=points,
            meters_per_unit=scale,
            calibration_method="ruler",
            calibration_evidence="Synthetic interval control; not verified",
            relative_scale_uncertainty=valid_uncertainty,
            point_index_pairs=[[0, 1]],
        )
        valid_chord = valid["selected_point_chords"][0]
        interval = valid_chord["chord_distance_scale_interval_m"]
        assert interval is not None
        assert (interval[0] == 0.0) is zero_lower_bound
        assert (
            "chord_uncertainty_interval_below_numeric_resolution" not in valid_chord["qc_warnings"]
        )

    project_id = str(create_project(client, f"Chord interval boundary {source_format}")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic underflow boundary; not a verified calibration",
        "relative_scale_uncertainty": uncertainty,
        "point_index_pairs": [[0, 1]],
    }
    if source_format == "xyz":
        params["points"] = points
    else:
        params["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 2\n"
            "property double x\nproperty double y\nproperty double z\n"
            "end_header\n0 0 0\n1 0 0\n"
        )
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["selected_point_chords"][0]["chord_distance_scale_interval_m"] is None
    assert expected["qc_warnings"] == direct["qc_warnings"]

    graph = {
        "graph_id": f"subresolution-chord-interval-{source_format}",
        "name": "Chords retain unknown positive lower uncertainty bounds",
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
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    assert artifact["payload_json"] == expected
