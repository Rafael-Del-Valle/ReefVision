"""Synthetic axis-projected scan gap QC: never infer biological tissue gaps."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project

POINTS = [
    [0.0, 0.0, 0.0],
    [1.0, 0.0, 1.0],
    [2.0, 1.0, 0.0],
    [9.0, 1.0, 1.0],
    [1.0, 0.0, 1.0],
]
# Three equal maximal x-axis gaps. The x=2 boundary is supported by
# three rows but just two distinct XYZ acquisition locations.
TIED_POINTS = [
    [0.0, 0.0, 0.0],
    [2.0, 0.0, 1.0],
    [4.0, 1.0, 0.0],
    [6.0, 1.0, 1.0],
    [2.0, 1.0, 1.0],
    [2.0, 1.0, 1.0],
]
PARAMS = {
    "meters_per_unit": 0.25,
    "calibration_method": "ruler",
    "calibration_evidence": "Unverified synthetic scan ruler",
    "relative_scale_uncertainty": 0.1,
    "specimen_id": "provisional-coral-a",
    "observation_id": "field-visit-1",
}


def _direct(points: list[list[float]]) -> dict:
    return measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.25,
        calibration_method="ruler",
        calibration_evidence="Unverified synthetic scan ruler",
        relative_scale_uncertainty=0.1,
    )


def test_axis_gap_is_projection_only_duplicate_invariant_and_scale_bounded() -> None:
    original = _direct(POINTS)
    reversed_rows = _direct(list(reversed(POINTS)))
    gaps = original["axis_largest_adjacent_coordinate_gaps"]
    assert gaps == reversed_rows["axis_largest_adjacent_coordinate_gaps"]
    assert gaps["x"]["distinct_source_coordinate_levels"] == 4
    assert gaps["x"]["equally_largest_adjacent_gap_count"] == 1
    assert gaps["x"]["source_endpoint_values"] == [2.0, 9.0]
    assert gaps["x"]["gap_endpoint_support"] == {
        "lower": {"source_rows": 1, "distinct_xyz_loci": 1},
        "upper": {"source_rows": 1, "distinct_xyz_loci": 1},
    }
    assert gaps["x"]["largest_adjacent_source_gap_units"] == 7.0
    assert gaps["x"]["fraction_of_source_axis_span"] == pytest.approx(7 / 9)
    assert gaps["x"]["calibrated_gap_m"] == pytest.approx(1.75)
    assert gaps["x"]["calibrated_gap_scale_interval_m"] == pytest.approx([1.575, 1.925])
    for axis in ("y", "z"):
        assert gaps[axis]["distinct_source_coordinate_levels"] == 2
        assert gaps[axis]["largest_adjacent_source_gap_units"] == 1.0
        assert gaps[axis]["equally_largest_adjacent_gap_count"] == 1
        assert gaps[axis]["calibrated_gap_m"] == pytest.approx(0.25)
    assert (
        original["provenance"]["geometry_sha256"] == reversed_rows["provenance"]["geometry_sha256"]
    )
    assert original["axis_aligned_dimensions_m"] == pytest.approx([2.25, 0.25, 0.25])
    assert original["provenance"]["calibration_verified"] is False
    assert original["provenance"]["coordinate_registration_verified"] is False
    assert original["surface_area_m2"] is None
    assert original["branch_length_m"] is None


def test_collapsed_axis_has_no_invented_sampling_gap() -> None:
    result = _direct([[0.0, 5.0, 0.0], [2.0, 5.0, 0.0]])
    gaps = result["axis_largest_adjacent_coordinate_gaps"]
    assert gaps["y"] == {
        "distinct_source_coordinate_levels": 1,
        "source_endpoint_values": None,
        "gap_endpoint_support": None,
        "equally_largest_adjacent_gap_count": 0,
        "largest_adjacent_source_gap_units": None,
        "fraction_of_source_axis_span": None,
        "calibrated_gap_m": None,
        "calibrated_gap_scale_interval_m": None,
    }
    assert gaps["x"]["source_endpoint_values"] == [0.0, 2.0]


def test_gap_boundary_support_distinguishes_rows_and_distinct_xyz_loci() -> None:
    # Three scan rows at x=2 represent only two distinct XYZ locations.
    # These numbers quantify acquisition support, not coral tissue presence.
    points = [
        [0.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [2.0, 1.0, 0.0],
        [2.0, 1.0, 0.0],
        [9.0, 1.0, 0.0],
    ]
    original = _direct(points)
    reordered = _direct(list(reversed(points)))
    x_gap = original["axis_largest_adjacent_coordinate_gaps"]["x"]
    assert x_gap["source_endpoint_values"] == [2.0, 9.0]
    assert x_gap["equally_largest_adjacent_gap_count"] == 1
    assert x_gap["gap_endpoint_support"] == {
        "lower": {"source_rows": 3, "distinct_xyz_loci": 2},
        "upper": {"source_rows": 1, "distinct_xyz_loci": 1},
    }
    # Adding a duplicate scan row changes row support, not distinct loci or geometry.
    with_extra_row = _direct([*points, [2.0, 1.0, 0.0]])
    duplicate_gap = with_extra_row["axis_largest_adjacent_coordinate_gaps"]["x"]
    assert duplicate_gap["source_endpoint_values"] == x_gap["source_endpoint_values"]
    assert duplicate_gap["largest_adjacent_source_gap_units"] == 7.0
    assert duplicate_gap["gap_endpoint_support"]["lower"] == {
        "source_rows": 4,
        "distinct_xyz_loci": 2,
    }
    assert (
        original["axis_largest_adjacent_coordinate_gaps"]
        == reordered["axis_largest_adjacent_coordinate_gaps"]
    )
    assert original["provenance"]["geometry_sha256"] == reordered["provenance"]["geometry_sha256"]
    assert original["provenance"]["calibration_verified"] is False
    assert original["surface_area_m2"] is None
    assert original["branch_length_m"] is None


def test_exact_tied_largest_gaps_preserve_row_support_and_disclose_ambiguity() -> None:
    original = _direct(TIED_POINTS)
    reversed_rows = _direct(list(reversed(TIED_POINTS)))
    x_gap = original["axis_largest_adjacent_coordinate_gaps"]["x"]
    assert x_gap == reversed_rows["axis_largest_adjacent_coordinate_gaps"]["x"]
    assert x_gap["source_endpoint_values"] == [0.0, 2.0]
    assert x_gap["equally_largest_adjacent_gap_count"] == 3
    assert x_gap["largest_adjacent_source_gap_units"] == 2.0
    assert x_gap["gap_endpoint_support"] == {
        "lower": {"source_rows": 1, "distinct_xyz_loci": 1},
        "upper": {"source_rows": 3, "distinct_xyz_loci": 2},
    }
    assert "axis_sampling_multiple_equally_largest_gaps" in original["qc_warnings"]
    assert original["qc_warnings"] == reversed_rows["qc_warnings"]
    assert (
        original["provenance"]["geometry_sha256"] == reversed_rows["provenance"]["geometry_sha256"]
    )
    assert original["provenance"]["calibration_verified"] is False
    assert original["surface_area_m2"] is None
    assert original["branch_length_m"] is None


def _assert_projected_gap_workflow_replay(
    client: TestClient, params: dict[str, Any], direct: dict[str, Any]
) -> None:
    project_id = str(create_project(client, "Projected gap numeric resolution")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    for key in (
        "axis_largest_adjacent_coordinate_gaps",
        "axis_aligned_dimensions_m",
        "axis_aligned_dimension_scale_interval_m",
        "axis_aligned_dimension_scale_uncertainty_m",
        "axis_aligned_bounding_box_envelope_volume_m3",
        "axis_aligned_bounding_box_envelope_volume_scale_interval_m3",
        "qc_warnings",
    ):
        assert expected[key] == direct[key]
    graph = {
        "graph_id": "projected-gap-numeric-resolution-v14",
        "name": "Projected sampling gap numeric resolution",
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
        assert artifacts[0]["payload_json"]["measurement_status"] == "caller_supplied_unverified"
        assert artifacts[0]["payload_json"]["provenance"]["calibration_verified"] is False
        assert artifacts[0]["payload_json"]["branch_length_m"] is None
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


def test_positive_axis_gap_below_calibration_resolution_is_not_zero(
    client: TestClient,
) -> None:
    # Distinct y coordinates keep the calibrated XYZ loci distinguishable.
    # The x projection alone loses adjacent gaps; its full extent survives.
    scale = 1e-304
    points = [[1e-4 + index * 1e-20, float(index), 0.0] for index in range(512)]
    assert len({tuple(value * scale for value in point) for point in points}) == len(points)
    assert len({point[0] * scale for point in points}) < len({point[0] for point in points})
    params: dict[str, Any] = {
        "points": points,
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Unphysical floating-point synthetic stress fixture",
        "relative_scale_uncertainty": 0.1,
    }
    result = measure_point_cloud_preview(**params)
    gap = result["axis_largest_adjacent_coordinate_gaps"]["x"]
    assert gap["largest_adjacent_source_gap_units"] > 0.0
    assert gap["calibrated_gap_m"] is None
    assert gap["calibrated_gap_scale_interval_m"] is None
    assert gap["fraction_of_source_axis_span"] > 0.0
    assert result["axis_aligned_dimensions_m"][0] > 0.0
    assert "axis_sampling_gap_below_numeric_resolution" in result["qc_warnings"]
    assert result["provenance"]["calibration_verified"] is False
    _assert_projected_gap_workflow_replay(client, params, result)


@pytest.mark.parametrize(
    ("levels", "expected_gap_m", "expected_fraction"),
    [
        ([-1.0, 1e-16, 1.0], 0.10000000000000002, 0.5),
        ([-1e-16, 0.0, 1.0], 0.1, 0.9999999999999999),
    ],
)
def test_projected_gap_scale_and_span_avoid_intermediate_rounding(
    client: TestClient,
    levels: list[float],
    expected_gap_m: float,
    expected_fraction: float,
) -> None:
    params: dict[str, Any] = {
        "points": [[value, 0.0, 0.0] for value in levels],
        "meters_per_unit": 0.1,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic projected gap precision control; unverified",
    }
    result = measure_point_cloud_preview(**params)
    gap = result["axis_largest_adjacent_coordinate_gaps"]["x"]
    assert gap["calibrated_gap_m"] == expected_gap_m
    assert gap["fraction_of_source_axis_span"] == expected_fraction
    assert gap["largest_adjacent_source_gap_units"] == 1.0
    assert gap["equally_largest_adjacent_gap_count"] == 1
    _assert_projected_gap_workflow_replay(client, params, result)


@pytest.mark.parametrize(
    ("levels", "uncertainty", "expected_interval"),
    [
        ([-1.0, 1e-16, 1.0], 0.1, [0.09000000000000001, 0.11000000000000001]),
        ([-1e-16, 0.0, 1.0], 0.2, [0.08, 0.12000000000000001]),
        ([0.0, 3.0], 0.1, [0.27, 0.33]),
        ([-1.0, 1e-16, 1.0], 0.0, [0.10000000000000002, 0.10000000000000002]),
        ([-1.0, 1e-16, 1.0], 1.0, [0.0, 0.20000000000000004]),
    ],
)
def test_projected_gap_scale_interval_rounds_only_final_bounds(
    client: TestClient,
    levels: list[float],
    uncertainty: float,
    expected_interval: list[float],
) -> None:
    # Expected endpoints independently evaluated with 120-digit Decimal
    # arithmetic on the exact imported binary floats, then rounded once.
    params: dict[str, Any] = {
        "points": [[value, 0.0, 0.0] for value in levels],
        "meters_per_unit": 0.1,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic scale interval precision control; unverified",
        "relative_scale_uncertainty": uncertainty,
    }
    result = measure_point_cloud_preview(**params)
    gap = result["axis_largest_adjacent_coordinate_gaps"]["x"]
    assert gap["calibrated_gap_scale_interval_m"] == expected_interval
    assert result["provenance"]["calibration_verified"] is False
    _assert_projected_gap_workflow_replay(client, params, result)


@pytest.mark.parametrize(
    ("lo", "hi", "uncertainty", "extent", "interval", "absolute"),
    [
        (
            -1.0,
            1e-16,
            0.1,
            0.10000000000000002,
            [0.09000000000000001, 0.11000000000000001],
            0.010000000000000002,
        ),
        (
            -1.0,
            1e-16,
            0.0,
            0.10000000000000002,
            [0.10000000000000002, 0.10000000000000002],
            0.0,
        ),
        (
            -1.0,
            1e-16,
            1.0,
            0.10000000000000002,
            [0.0, 0.20000000000000004],
            0.10000000000000002,
        ),
        (0.0, 3.0, 0.1, 0.30000000000000004, [0.27, 0.33], 0.030000000000000002),
        (
            -1e-16,
            1.0,
            0.2,
            0.10000000000000002,
            [0.08000000000000002, 0.12000000000000002],
            0.020000000000000004,
        ),
    ],
)
def test_extent_and_scale_uncertainty_use_unrounded_source_span(
    client: TestClient,
    lo: float,
    hi: float,
    uncertainty: float,
    extent: float,
    interval: list[float],
    absolute: float,
) -> None:
    # Independently evaluated using 120-digit Decimal arithmetic on exact
    # imported binary floats; the mirrored z axis has the same extent.
    params: dict[str, Any] = {
        "points": [[lo, 0.0, -hi], [hi, 0.0, -lo]],
        "meters_per_unit": 0.1,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic extent precision control; unverified",
        "relative_scale_uncertainty": uncertainty,
    }
    result = measure_point_cloud_preview(**params)
    assert result["axis_aligned_dimensions_m"] == [extent, 0.0, extent]
    assert result["axis_aligned_dimension_scale_interval_m"] == [interval, [0.0, 0.0], interval]
    assert result["axis_aligned_dimension_scale_uncertainty_m"] == [absolute, 0.0, absolute]
    for axis in ("x", "z"):
        gap = result["axis_largest_adjacent_coordinate_gaps"][axis]
        assert gap["calibrated_gap_m"] == extent
        assert gap["calibrated_gap_scale_interval_m"] == interval
    _assert_projected_gap_workflow_replay(client, params, result)


@pytest.mark.parametrize(
    ("uncertainty", "interval"),
    [
        (0.1, [0.0007290000000000004, 0.0013310000000000006]),
        (0.0, [0.0010000000000000005, 0.0010000000000000005]),
        (1.0, [0.0, 0.008000000000000004]),
    ],
)
def test_envelope_uses_exact_calibrated_spans(
    client: TestClient, uncertainty: float, interval: list[float]
) -> None:
    # Independent high-precision Decimal reference using exact binary inputs.
    # Two diagonal endpoints define an envelope, not a biological volume.
    params: dict[str, Any] = {
        "points": [[-1.0, -1.0, -1.0], [1e-16, 1e-16, 1e-16]],
        "meters_per_unit": 0.1,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic envelope precision control; unverified",
        "relative_scale_uncertainty": uncertainty,
    }
    result = measure_point_cloud_preview(**params)
    assert result["axis_aligned_bounding_box_envelope_volume_m3"] == 0.0010000000000000005
    assert result["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"] == interval
    assert "positive_bounding_envelope_for_lower_dimensional_source" in result["qc_warnings"]
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None
    _assert_projected_gap_workflow_replay(client, params, result)


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_all_tied_maximum_gap_boundaries_are_audited_in_saved_workflow(
    client: TestClient, source_format: str
) -> None:
    # Both intervals have the same maximum source-x gap (101 units).
    # Uniform 512/600 display sampling shows indices 7 and 8, but hides
    # index 299 while showing 300. The representative first gap is visible.
    points = [
        [float(i + (100 if i >= 8 else 0) + (100 if i >= 300 else 0)), 0.0, 0.0] for i in range(600)
    ]
    params = dict(PARAMS)
    if source_format == "ply":
        params["ply_text"] = (
            f"ply\nformat ascii 1.0\nelement vertex {len(points)}\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n"
            + "".join(f"{point[0]:g} 0 0\n" for point in points)
        )
    else:
        params["points"] = points

    project_id = str(create_project(client, "Tied sampling gap boundary QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert (
        expected["axis_largest_adjacent_coordinate_gaps"]["x"]["equally_largest_adjacent_gap_count"]
        == 2
    )
    assert expected["axis_largest_adjacent_coordinate_gaps"]["x"]["source_endpoint_values"] == [
        7.0,
        108.0,
    ]
    assert 7 in expected["preview_point_indices"]
    assert 8 in expected["preview_point_indices"]
    assert 299 not in expected["preview_point_indices"]
    assert 300 in expected["preview_point_indices"]
    assert expected["preview_largest_axis_gap_endpoint_support"]["x"] == {
        "lower": True,
        "upper": True,
    }
    assert expected["preview_largest_axis_gap_interval_coverage"] == {
        "x": {
            "total_intervals": 2,
            "fully_displayed_intervals": 1,
            "partially_displayed_intervals": 1,
            "hidden_intervals": 0,
        },
        "y": None,
        "z": None,
    }
    assert expected["preview_omitted_largest_gap_boundary_axes"] == ["x"]
    assert "preview_omits_largest_axis_gap_endpoint" in expected["qc_warnings"]
    assert "axis_sampling_multiple_equally_largest_gaps" in expected["qc_warnings"]
    assert expected["preview_axis_extrema_covered"] is True
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["surface_area_m2"] is None
    assert expected["branch_length_m"] is None

    graph = {
        "graph_id": f"tied-preview-gaps-{source_format}-v14",
        "name": "Audit all tied projected scan gaps without biological inference",
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


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_hidden_maximum_gap_boundary_is_disclosed_on_saved_workflow_replay(
    client: TestClient, source_format: str
) -> None:
    # Uniform 512/600-row sampling omits source row 6 but displays row 7.
    # The largest source-x gap is between those two acquisition rows; both
    # source-axis extrema remain displayed, so extrema QC alone misses this.
    points = [[float(index + (100 if index >= 7 else 0)), 0.0, 0.0] for index in range(600)]
    params = dict(PARAMS)
    if source_format == "ply":
        params["ply_text"] = (
            f"ply\nformat ascii 1.0\nelement vertex {len(points)}\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n"
            + "".join(f"{point[0]:g} 0 0\n" for point in points)
        )
    else:
        params["points"] = points

    project_id = str(create_project(client, "Hidden scan gap display QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["axis_largest_adjacent_coordinate_gaps"]["x"]["source_endpoint_values"] == [
        6.0,
        107.0,
    ]
    assert 6 not in expected["preview_point_indices"]
    assert 7 in expected["preview_point_indices"]
    assert expected["preview_axis_extrema_covered"] is True
    assert expected["preview_largest_axis_gap_endpoint_support"] == {
        "x": {"lower": False, "upper": True},
        "y": None,
        "z": None,
    }
    assert expected["preview_omitted_largest_gap_boundary_axes"] == ["x"]
    assert "preview_omits_largest_axis_gap_endpoint" in expected["qc_warnings"]
    assert "preview_omits_axis_extrema" not in expected["qc_warnings"]
    assert expected["surface_area_m2"] is None
    assert expected["branch_length_m"] is None
    assert expected["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": f"hidden-gap-boundary-{source_format}-v14",
        "name": "Inspect omitted projected gap support without inferring tissue loss",
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


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
@pytest.mark.parametrize("tied_gap", [False, True], ids=["unique-largest", "three-way-tie"])
def test_imported_and_xyz_gap_science_replays_from_saved_typed_graph(
    client: TestClient, source_format: str, tied_gap: bool
) -> None:
    project_id = str(create_project(client, "Synthetic point-cloud sampling QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = dict(PARAMS)
    points = TIED_POINTS if tied_gap else POINTS
    if source_format == "ply":
        header = (
            f"ply\nformat ascii 1.0\nelement vertex {len(points)}\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n"
        )
        params["ply_text"] = header + "".join(f"{x:g} {y:g} {z:g}\n" for x, y, z in points)
    else:
        params["points"] = points
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["axis_largest_adjacent_coordinate_gaps"]["x"]["source_endpoint_values"] == (
        [0.0, 2.0] if tied_gap else [2.0, 9.0]
    )
    assert expected["axis_largest_adjacent_coordinate_gaps"]["x"][
        "equally_largest_adjacent_gap_count"
    ] == (3 if tied_gap else 1)
    assert expected["axis_largest_adjacent_coordinate_gaps"]["x"]["gap_endpoint_support"] == {
        "lower": {"source_rows": 1, "distinct_xyz_loci": 1},
        "upper": {
            "source_rows": 3 if tied_gap else 1,
            "distinct_xyz_loci": 2 if tied_gap else 1,
        },
    }
    assert ("axis_sampling_multiple_equally_largest_gaps" in expected["qc_warnings"]) is tied_gap
    assert expected["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": f"point-cloud-axis-gaps-{source_format}-{tied_gap}-v14",
        "name": "Review projected coordinate gaps, not coral tissue gaps",
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


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
@pytest.mark.parametrize("duplicate_loci", [False, True], ids=["distinct-loci", "repeat-rows"])
def test_distinct_xyz_gap_boundary_loci_audited_in_saved_workflow(
    client: TestClient, source_format: str, duplicate_loci: bool
) -> None:
    # Each endpoint level has 300 acquisition rows. A bounded 512-row preview
    # loses 88 raw rows, but repeated XYZ locations do not become biological
    # replicates. Only the nonduplicate cloud loses distinct XYZ loci.
    points = [
        [0.0 if i < 300 else 100.0, 0.0 if duplicate_loci else float(i % 300), 0.0]
        for i in range(600)
    ]
    direct = _direct(points)
    params = dict(PARAMS)
    if source_format == "ply":
        params["ply_text"] = (
            f"ply\nformat ascii 1.0\nelement vertex {len(points)}\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n"
            + "".join(f"{x:g} {y:g} {z:g}\n" for x, y, z in points)
        )
    else:
        params["points"] = points

    project_id = str(create_project(client, "Distinct gap-boundary XYZ display QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    support = expected["preview_largest_axis_gap_boundary_locus_support"]
    expected_loci = 2 if duplicate_loci else 600
    displayed_loci = 2 if duplicate_loci else 512
    assert support["x"] == {
        "source_acquisition_rows": 600,
        "preview_acquisition_rows": 512,
        "fraction_of_source_rows_displayed": pytest.approx(512 / 600),
        "source_distinct_xyz_loci": expected_loci,
        "preview_distinct_xyz_loci": displayed_loci,
        "fraction_of_source_loci_displayed": pytest.approx(displayed_loci / expected_loci),
    }
    assert direct["preview_largest_axis_gap_boundary_locus_support"] == support
    assert expected["preview_largest_axis_gap_endpoint_support"]["x"] == {
        "lower": True,
        "upper": True,
    }
    assert expected["preview_largest_axis_gap_interval_coverage"]["x"] == {
        "total_intervals": 1,
        "fully_displayed_intervals": 1,
        "partially_displayed_intervals": 0,
        "hidden_intervals": 0,
    }
    # The distinct-loci cloud also has 299 *tied* maximum y-axis gaps
    # (unit spacing at each of 300 levels). Their union spans all 600 rows,
    # and default 512-row decimation omits 21 y levels. The repeated-row
    # fixture has a constant y axis, so it must not report a y-axis gap.
    # Do not conflate retaining both x-gap endpoints with retaining all
    # maximum-gap boundaries on the other axes.
    if duplicate_loci:
        assert support["y"] is None
    else:
        assert support["y"] == support["x"]
        assert (
            expected["axis_largest_adjacent_coordinate_gaps"]["y"][
                "equally_largest_adjacent_gap_count"
            ]
            == 299
        )
        assert expected["preview_largest_axis_gap_interval_coverage"]["y"] == {
            "total_intervals": 299,
            "fully_displayed_intervals": 257,
            "partially_displayed_intervals": 42,
            "hidden_intervals": 0,
        }
    assert expected["preview_omitted_largest_gap_boundary_locus_axes"] == (
        [] if duplicate_loci else ["x", "y"]
    )
    assert expected["preview_omitted_largest_gap_boundary_acquisition_axes"] == (
        ["x"] if duplicate_loci else ["x", "y"]
    )
    assert expected["preview_omitted_largest_gap_boundary_axes"] == (
        [] if duplicate_loci else ["y"]
    )
    assert ("preview_omits_largest_axis_gap_boundary_xyz_loci" in expected["qc_warnings"]) is (
        not duplicate_loci
    )
    assert "preview_omits_largest_axis_gap_boundary_acquisition_rows" in expected["qc_warnings"]
    assert ("preview_omits_largest_axis_gap_endpoint" in expected["qc_warnings"]) is (
        not duplicate_loci
    )
    assert (
        expected["axis_largest_adjacent_coordinate_gaps"]["x"]["largest_adjacent_source_gap_units"]
        == 100.0
    )
    assert expected["surface_area_m2"] is None
    assert expected["branch_length_m"] is None
    assert expected["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": f"boundary-xyz-loci-{source_format}-{duplicate_loci}-v14",
        "name": "Audit displayed XYZ loci at projected largest-gap boundaries",
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


@pytest.mark.parametrize("preserve_distinct_loci", [False, True])
def test_rgb_ply_duplicate_xyz_color_variants_are_audited_in_saved_graph(
    client: TestClient, preserve_distinct_loci: bool
) -> None:
    # Row 34 is a rare red acquisition at an otherwise repeated XYZ location.
    # Both bounded sampling modes omit it, even though both distinct XYZ loci
    # are displayed. A loss of RGB evidence is not a diagnosis of tissue loss.
    points = [[0.0 if i < 300 else 100.0, 0.0, 0.0] for i in range(600)]
    rgb = [
        [255, 0, 0] if i == 34 else [20, 20, 20] if i < 300 else [230, 230, 230] for i in range(600)
    ]
    ply = (
        "ply\nformat ascii 1.0\nelement vertex 600\n"
        "property double x\nproperty double y\nproperty double z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
        + "".join(
            f"{point[0]:g} 0 0 {color[0]} {color[1]} {color[2]}\n"
            for point, color in zip(points, rgb, strict=True)
        )
    )
    params = {
        **PARAMS,
        "ply_text": ply,
        "preserve_distinct_xyz_loci_in_preview": preserve_distinct_loci,
    }
    project_id = str(create_project(client, "PLY RGB duplicate-locus sampling QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["point_count"] == 600
    assert expected["unique_point_count"] == 2
    assert expected["preview_unique_coordinate_count"] == 2
    assert 34 not in expected["preview_point_indices"]
    # Row coverage alone conceals rare-color and channel-extremum losses.
    # Audit source-vs-preview RGB distributions without inferring tissue condition.
    assert expected["preview_rgb_variant_support"] == {
        "source_repeated_xyz_rgb_observation_rows": 597,
        "source_repeated_xyz_rgb_observation_fraction": 597 / 600,
        "preview_repeated_xyz_rgb_observation_rows": 510,
        "source_xyz_rgb_observation_rows_represented_in_preview": 599,
        "fraction_of_source_xyz_rgb_observation_rows_represented_in_preview": 599 / 600,
        "preview_vs_source_xyz_rgb_observation_total_variation": 1 / 600,
        "preview_vs_source_xyz_rgb_observation_total_variation_exact_fraction": [1, 600],
        "source_rgb_channel_ranges_uint8": {
            "red": [20, 255],
            "green": [0, 230],
            "blue": [0, 230],
        },
        "preview_rgb_channel_ranges_uint8": {
            "red": [20, 230],
            "green": [20, 230],
            "blue": [20, 230],
        },
        "preview_omitted_source_rgb_channel_extrema": [
            "red_max",
            "green_min",
            "blue_min",
        ],
        "source_distinct_rgb_triplets": 3,
        "preview_distinct_rgb_triplets": 2,
        "fraction_of_source_rgb_triplets_displayed": pytest.approx(2 / 3),
        "preview_omitted_distinct_rgb_triplets": 1,
        "preview_vs_source_rgb_triplet_total_variation": 1 / 600,
        "preview_vs_source_rgb_triplet_total_variation_exact_fraction": [1, 600],
        "preview_xyz_rgb_vs_rgb_marginal_tv_gap": 0.0,
        "preview_xyz_rgb_vs_rgb_marginal_tv_gap_exact_fraction": [0, 1],
        "preview_vs_source_xyz_locus_total_variation": 0.0,
        "preview_vs_source_xyz_locus_total_variation_exact_fraction": [0, 1],
        "preview_xyz_rgb_vs_xyz_marginal_tv_gap": 1 / 600,
        "preview_xyz_rgb_vs_xyz_marginal_tv_gap_exact_fraction": [1, 600],
        "source_distinct_xyz_rgb_pairs": 3,
        "preview_distinct_xyz_rgb_pairs": 2,
        "fraction_of_source_xyz_rgb_pairs_displayed": pytest.approx(2 / 3),
        "source_xyz_loci_with_multiple_rgb_values": 1,
        "multi_rgb_xyz_loci_with_complete_preview": 0,
        "multi_rgb_xyz_loci_with_incomplete_preview": 1,
        "preview_sample_xyz_rgb_sha256": expected["preview_rgb_variant_support"][
            "preview_sample_xyz_rgb_sha256"
        ],
    }
    assert len(expected["preview_rgb_variant_support"]["preview_sample_xyz_rgb_sha256"]) == 64
    assert "source_xyz_loci_have_multiple_rgb_values" in expected["qc_warnings"]
    assert "preview_omits_distinct_xyz_rgb_observations" in expected["qc_warnings"]
    assert "preview_omits_distinct_rgb_triplets" in expected["qc_warnings"]
    assert "preview_shifts_rgb_triplet_frequency_distribution" in expected["qc_warnings"]
    assert "preview_shifts_xyz_locus_frequency_distribution" not in expected["qc_warnings"]
    assert "preview_xyz_rgb_tv_exceeds_xyz_marginal_tv" in expected["qc_warnings"]
    assert "preview_omits_multi_rgb_locus_variants" in expected["qc_warnings"]
    assert [255, 0, 0] not in expected["preview_point_colors_rgb_uint8"]
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["surface_area_m2"] is None
    assert expected["branch_length_m"] is None

    # An inline XYZ cloud contains no RGB evidence. Its absent color audit
    # must never be misconstrued as confirmation of stable biological color.
    xyz_response = client.post(
        f"{base}/spatial/point-cloud-preview", json={**PARAMS, "points": points}
    )
    assert xyz_response.status_code == 200, xyz_response.text
    assert xyz_response.json()["preview_rgb_variant_support"] is None
    assert (
        "preview_shifts_xyz_locus_frequency_distribution" not in xyz_response.json()["qc_warnings"]
    )
    assert "preview_xyz_rgb_tv_exceeds_xyz_marginal_tv" not in xyz_response.json()["qc_warnings"]
    assert "preview_omits_distinct_xyz_rgb_observations" not in xyz_response.json()["qc_warnings"]
    assert "preview_omits_distinct_rgb_triplets" not in xyz_response.json()["qc_warnings"]
    assert (
        "preview_shifts_rgb_triplet_frequency_distribution"
        not in xyz_response.json()["qc_warnings"]
    )
    graph = {
        "graph_id": f"point-cloud-rgb-variants-{preserve_distinct_loci}-v14",
        "name": "Audit RGB display evidence without tissue-condition inference",
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


def test_complete_multi_rgb_locus_stays_distinct_from_biological_condition(
    client: TestClient,
) -> None:
    # A small imported scan retains both acquisition colors at one XYZ locus.
    # This proves visualization evidence coverage, not calibrated color or health.
    ply = (
        "ply\nformat ascii 1.0\nelement vertex 3\n"
        "property double x\nproperty double y\nproperty double z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
        "0 0 0 10 20 30\n"
        "0 0 0 200 100 50\n"
        "1 0 0 10 20 30\n"
    )
    project_id = str(create_project(client, "Complete RGB acquisition preview QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {**PARAMS, "ply_text": ply}
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    support = expected["preview_rgb_variant_support"]
    assert support["source_distinct_xyz_rgb_pairs"] == 3
    assert support["preview_distinct_xyz_rgb_pairs"] == 3
    assert support["fraction_of_source_xyz_rgb_pairs_displayed"] == 1.0
    assert support["source_distinct_rgb_triplets"] == 2
    assert support["preview_distinct_rgb_triplets"] == 2
    assert support["fraction_of_source_rgb_triplets_displayed"] == 1.0
    assert support["preview_omitted_distinct_rgb_triplets"] == 0
    assert support["source_xyz_loci_with_multiple_rgb_values"] == 1
    assert support["multi_rgb_xyz_loci_with_complete_preview"] == 1
    assert support["multi_rgb_xyz_loci_with_incomplete_preview"] == 0
    # A full three-row preview retains the joint XYZ/RGB observation
    # distribution AND both marginals exactly. Multiple observed colors at
    # one locus must not by itself create a false display-drift warning.
    assert expected["preview_point_indices"] == [0, 1, 2]
    for prefix in (
        "preview_vs_source_xyz_rgb_observation",
        "preview_vs_source_rgb_triplet",
        "preview_vs_source_xyz_locus",
    ):
        assert support[f"{prefix}_total_variation"] == 0.0
        assert support[f"{prefix}_total_variation_exact_fraction"] == [0, 1]
    for marginal in ("rgb", "xyz"):
        assert support[f"preview_xyz_rgb_vs_{marginal}_marginal_tv_gap"] == 0.0
        assert support[f"preview_xyz_rgb_vs_{marginal}_marginal_tv_gap_exact_fraction"] == [0, 1]
    for warning in (
        "preview_shifts_xyz_rgb_observation_frequency_distribution",
        "preview_shifts_rgb_triplet_frequency_distribution",
        "preview_shifts_xyz_locus_frequency_distribution",
        "preview_xyz_rgb_tv_exceeds_rgb_marginal_tv",
        "preview_xyz_rgb_tv_exceeds_xyz_marginal_tv",
    ):
        assert warning not in expected["qc_warnings"]
    assert "source_xyz_loci_have_multiple_rgb_values" in expected["qc_warnings"]
    assert "preview_omits_distinct_xyz_rgb_observations" not in expected["qc_warnings"]
    assert "preview_omits_distinct_rgb_triplets" not in expected["qc_warnings"]
    assert "preview_omits_multi_rgb_locus_variants" not in expected["qc_warnings"]
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": "point-cloud-complete-rgb-preview-v14",
        "name": "Retained color observations are not validated biology",
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
