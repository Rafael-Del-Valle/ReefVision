"""Synthetic axis-projected scan gap QC: never infer biological tissue gaps."""

from __future__ import annotations

from typing import cast

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
        assert gaps[axis]["calibrated_gap_m"] == pytest.approx(0.25)
    assert original["provenance"]["geometry_sha256"] == reversed_rows["provenance"][
        "geometry_sha256"
    ]
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
    assert x_gap["gap_endpoint_support"] == {
        "lower": {"source_rows": 3, "distinct_xyz_loci": 2},
        "upper": {"source_rows": 1, "distinct_xyz_loci": 1},
    }
    assert original["axis_largest_adjacent_coordinate_gaps"] == reordered[
        "axis_largest_adjacent_coordinate_gaps"
    ]
    assert original["provenance"]["geometry_sha256"] == reordered["provenance"][
        "geometry_sha256"
    ]
    assert original["provenance"]["calibration_verified"] is False
    assert original["surface_area_m2"] is None
    assert original["branch_length_m"] is None


def test_positive_axis_gap_below_calibration_resolution_is_not_zero() -> None:
    # All calibrated points and the full calibrated axis extent are nonzero;
    # adjacent source-coordinate differences alone underflow after scaling.
    points = [[1e-4 + index * 1e-20, 0.0, 0.0] for index in range(512)]
    result = measure_point_cloud_preview(
        points=points,
        meters_per_unit=1e-304,
        calibration_method="ruler",
        calibration_evidence="Unphysical floating-point synthetic stress fixture",
        relative_scale_uncertainty=0.1,
    )
    gap = result["axis_largest_adjacent_coordinate_gaps"]["x"]
    assert gap["largest_adjacent_source_gap_units"] > 0.0
    assert gap["calibrated_gap_m"] is None
    assert gap["calibrated_gap_scale_interval_m"] is None
    assert gap["fraction_of_source_axis_span"] > 0.0
    assert result["axis_aligned_dimensions_m"][0] > 0.0
    assert "axis_sampling_gap_below_numeric_resolution" in result["qc_warnings"]
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_imported_and_xyz_gap_science_replays_from_saved_typed_graph(
    client: TestClient, source_format: str
) -> None:
    project_id = str(create_project(client, "Synthetic point-cloud sampling QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = dict(PARAMS)
    if source_format == "ply":
        header = (
            "ply\nformat ascii 1.0\nelement vertex 5\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n"
        )
        params["ply_text"] = header + "".join(
            f"{x:g} {y:g} {z:g}\n" for x, y, z in POINTS
        )
    else:
        params["points"] = POINTS
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["axis_largest_adjacent_coordinate_gaps"]["x"][
        "source_endpoint_values"
    ] == [2.0, 9.0]
    assert expected["axis_largest_adjacent_coordinate_gaps"]["x"][
        "gap_endpoint_support"
    ] == {
        "lower": {"source_rows": 1, "distinct_xyz_loci": 1},
        "upper": {"source_rows": 1, "distinct_xyz_loci": 1},
    }
    assert expected["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": f"point-cloud-axis-gaps-{source_format}-v14",
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
