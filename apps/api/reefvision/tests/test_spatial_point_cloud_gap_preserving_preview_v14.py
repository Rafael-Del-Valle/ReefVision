"""Synthetic display pinning of projected scan-gap boundaries, not missing coral tissue."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project


def _points() -> list[list[float]]:
    # Source x has exactly two maximal 101-unit gaps at 7/8 and 299/300.
    return [
        [float(i + (100 if i >= 8 else 0) + (100 if i >= 300 else 0)), 0.0, 0.0] for i in range(600)
    ]


def _params() -> dict:
    return {
        "meters_per_unit": 0.25,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified synthetic scan ruler",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "provisional-coral-a",
        "observation_id": "visit-1",
        "preserve_largest_axis_gap_boundaries_in_preview": True,
    }


def test_gap_boundary_pinning_changes_display_not_full_source_science() -> None:
    points = _points()
    baseline = measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.25,
        calibration_method="ruler",
        calibration_evidence="Unverified synthetic scan ruler",
        relative_scale_uncertainty=0.1,
    )
    preserved = measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.25,
        calibration_method="ruler",
        calibration_evidence="Unverified synthetic scan ruler",
        relative_scale_uncertainty=0.1,
        preserve_largest_axis_gap_boundaries_in_preview=True,
    )
    assert 299 not in baseline["preview_point_indices"]
    assert 299 in preserved["preview_point_indices"]
    assert len(preserved["preview_point_indices"]) == 512
    assert preserved["preview_largest_axis_gap_boundaries_preservation_requested"] is True
    assert baseline["preview_largest_axis_gap_boundaries_preservation_requested"] is False
    assert preserved["preview_sampling_strategy"] == (
        "uniform_index_largest_gap_boundaries_preserving"
    )
    assert preserved["preview_largest_axis_gap_interval_coverage"]["x"] == {
        "total_intervals": 2,
        "fully_displayed_intervals": 2,
        "partially_displayed_intervals": 0,
        "hidden_intervals": 0,
    }
    assert preserved["preview_omitted_largest_gap_boundary_axes"] == []
    assert "preview_omits_largest_axis_gap_endpoint" not in preserved["qc_warnings"]
    assert "axis_sampling_multiple_equally_largest_gaps" in preserved["qc_warnings"]
    for key in (
        "axis_largest_adjacent_coordinate_gaps",
        "axis_aligned_dimensions_m",
        "axis_aligned_bounding_box_envelope_volume_m3",
        "source_affine_dimension",
        "point_count",
    ):
        assert preserved[key] == baseline[key]
    assert preserved["provenance"] == baseline["provenance"]
    assert preserved["surface_area_m2"] is None
    assert preserved["branch_length_m"] is None
    assert preserved["provenance"]["calibration_verified"] is False


def test_gap_pins_compose_with_chords_and_extrema_and_reject_over_budget() -> None:
    points = _points()
    preserved = measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.25,
        calibration_method="ruler",
        calibration_evidence="Unverified synthetic scan ruler",
        point_index_pairs=[[6, 222]],
        preserve_axis_extrema_in_preview=True,
        preserve_measured_chord_endpoints_in_preview=True,
        preserve_largest_axis_gap_boundaries_in_preview=True,
    )
    assert {0, 6, 7, 8, 222, 299, 300, 599}.issubset(set(preserved["preview_point_indices"]))
    assert preserved["preview_selected_chord_endpoints_covered"] is True
    assert preserved["preview_axis_extrema_covered"] is True
    assert preserved["preview_omitted_largest_gap_boundary_axes"] == []
    assert len(preserved["preview_point_indices"]) == 512

    with pytest.raises(ValueError, match="Protected point indices exceed the display budget"):
        measure_point_cloud_preview(
            points=[[float(i), 0.0, 0.0] for i in range(600)],
            meters_per_unit=1.0,
            calibration_method="ruler",
            calibration_evidence="Synthetic equispaced source with 599 tied gaps",
            preserve_largest_axis_gap_boundaries_in_preview=True,
        )
    with pytest.raises(ValueError, match="must be a boolean"):
        measure_point_cloud_preview(
            points=points,
            meters_per_unit=1.0,
            calibration_method="ruler",
            calibration_evidence="Synthetic strict typing",
            preserve_largest_axis_gap_boundaries_in_preview=cast(bool, "yes"),
        )


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_pinned_gap_boundary_replays_in_saved_executable_workflow(
    client: TestClient, source_format: str
) -> None:
    points = _points()
    params = _params()
    if source_format == "ply":
        params["ply_text"] = (
            f"ply\nformat ascii 1.0\nelement vertex {len(points)}\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n"
            + "".join(f"{point[0]:g} 0 0\n" for point in points)
        )
    else:
        params["points"] = points

    project_id = str(create_project(client, "Pinned projected scan gap boundaries")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert 299 in expected["preview_point_indices"]
    assert expected["preview_omitted_largest_gap_boundary_axes"] == []
    assert expected["measurement_status"] == "caller_supplied_unverified"
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["provenance"]["calibration_verified"] is False

    invalid = dict(params)
    invalid["preserve_largest_axis_gap_boundaries_in_preview"] = "true"
    invalid_response = client.post(f"{base}/spatial/point-cloud-preview", json=invalid)
    assert invalid_response.status_code == 422

    graph = {
        "graph_id": f"pinned-gap-boundaries-{source_format}-v14",
        "name": "Retain all projected maximum gap endpoints for visual review",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-to-cloud",
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
    hashes = []
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
        artifacts = [
            artifact
            for artifact in detail.json()["artifacts"]
            if artifact["data_type"] == "point_cloud_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == expected
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


def _repeated_boundary_points() -> list[list[float]]:
    # 600 acquisition rows, but only 300 distinct XYZ locations across
    # the boundary levels of the largest projected scan-coordinate gaps.
    return [[0.0 if i < 300 else 100.0, float(i % 150), float(i % 5)] for i in range(600)]


def test_all_gap_boundary_xyz_loci_can_be_pinned_without_preserving_duplicate_rows() -> None:
    points = _repeated_boundary_points()
    kwargs = {
        "points": points,
        "meters_per_unit": 0.25,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic unverified acquisition",
        "relative_scale_uncertainty": 0.1,
    }
    baseline = measure_point_cloud_preview(**kwargs)
    preserved = measure_point_cloud_preview(
        **kwargs,
        preserve_largest_axis_gap_boundary_loci_in_preview=True,
    )
    assert baseline["preview_unique_coordinate_count"] == 267
    assert preserved["point_count"] == 600
    assert preserved["unique_point_count"] == 300
    assert preserved["preview_unique_coordinate_count"] == 300
    assert len(preserved["preview_point_indices"]) == 512
    assert set(range(150)) | set(range(300, 450)) <= set(preserved["preview_point_indices"])
    assert preserved["preview_sampling_strategy"] == (
        "uniform_index_largest_gap_boundary_loci_preserving"
    )
    assert preserved["preview_largest_axis_gap_boundary_loci_preservation_requested"] is True
    assert baseline["preview_largest_axis_gap_boundary_loci_preservation_requested"] is False
    assert preserved["preview_omitted_largest_gap_boundary_locus_axes"] == []
    assert preserved["preview_omitted_largest_gap_boundary_acquisition_axes"] == [
        "x",
        "y",
        "z",
    ]
    assert "preview_omits_largest_axis_gap_boundary_acquisition_rows" in preserved["qc_warnings"]
    assert "preview_omits_largest_axis_gap_boundary_xyz_loci" not in preserved["qc_warnings"]
    for axis in ("x", "y", "z"):
        support = preserved["preview_largest_axis_gap_boundary_locus_support"][axis]
        assert support["source_distinct_xyz_loci"] == 300
        assert support["preview_distinct_xyz_loci"] == 300
        assert support["source_acquisition_rows"] == 600
        assert support["preview_acquisition_rows"] == 512
    assert baseline["provenance"] == preserved["provenance"]
    assert baseline["axis_aligned_dimensions_m"] == preserved["axis_aligned_dimensions_m"]
    assert (
        baseline["axis_largest_adjacent_coordinate_gaps"]
        == (preserved["axis_largest_adjacent_coordinate_gaps"])
    )
    assert preserved["surface_area_m2"] is None
    assert preserved["branch_length_m"] is None


def test_xyz_locus_pinning_is_strict_and_rejects_an_oversubscribed_preview() -> None:
    kwargs = {
        "meters_per_unit": 1.0,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic unverified source",
    }
    with pytest.raises(ValueError, match="must be a boolean"):
        measure_point_cloud_preview(
            points=_repeated_boundary_points(),
            preserve_largest_axis_gap_boundary_loci_in_preview=cast(bool, "true"),
            **kwargs,
        )
    with pytest.raises(ValueError, match="Protected point indices exceed the display budget"):
        measure_point_cloud_preview(
            points=[[float(i), 0.0, 0.0] for i in range(600)],
            preserve_largest_axis_gap_boundary_loci_in_preview=True,
            **kwargs,
        )
    combined = measure_point_cloud_preview(
        points=_repeated_boundary_points(),
        preserve_axis_extrema_in_preview=True,
        preserve_largest_axis_gap_boundaries_in_preview=True,
        preserve_largest_axis_gap_boundary_loci_in_preview=True,
        **kwargs,
    )
    assert combined["preview_unique_coordinate_count"] == 300
    assert combined["preview_axis_extrema_covered"] is True
    assert combined["preview_omitted_largest_gap_boundary_locus_axes"] == []


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_xyz_locus_pinning_standalone_and_persisted_workflow_parity(
    client: TestClient, source_format: str
) -> None:
    points = _repeated_boundary_points()
    params = {
        "meters_per_unit": 0.25,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified duplicate scan",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "provisional-coral-a",
        "observation_id": "scan-with-duplicates",
        "preserve_largest_axis_gap_boundary_loci_in_preview": True,
    }
    if source_format == "ply":
        params["ply_text"] = (
            f"ply\nformat ascii 1.0\nelement vertex {len(points)}\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n"
            + "".join(f"{x:g} {y:g} {z:g}\n" for x, y, z in points)
        )
    else:
        params["points"] = points
    project_id = str(create_project(client, "Preserved XYZ acquisition locations")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["preview_unique_coordinate_count"] == 300
    assert expected["preview_omitted_largest_gap_boundary_locus_axes"] == []
    assert expected["preview_omitted_largest_gap_boundary_acquisition_axes"] == [
        "x",
        "y",
        "z",
    ]
    assert expected["measurement_status"] == "caller_supplied_unverified"
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False

    invalid = dict(params)
    invalid["preserve_largest_axis_gap_boundary_loci_in_preview"] = "true"
    invalid_response = client.post(f"{base}/spatial/point-cloud-preview", json=invalid)
    assert invalid_response.status_code == 422

    graph = {
        "graph_id": f"gap-boundary-loci-{source_format}-v14",
        "name": "Retain projected scan-gap boundary XYZ locations for review",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-to-cloud",
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
    hashes = []
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
        artifacts = [
            artifact
            for artifact in detail.json()["artifacts"]
            if artifact["data_type"] == "point_cloud_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == expected
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]
