"""Provisional mesh timepoint comparison: API, QC and persisted typed graph parity."""

from __future__ import annotations

from math import sqrt
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.workflow_mesh_v14 import execute_mesh_longitudinal_comparison
from reefvision.tests.test_annotations import create_project


def _mesh(observation: str, date: str, height: float) -> dict:
    return {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, height, 0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 1,
        "calibration_method": "ruler",
        "calibration_evidence": "Field ruler not yet reviewed",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "colony:16",
        "observation_id": observation,
        "observed_at_utc": date,
    }


def test_mesh_comparison_standalone_and_persisted_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "Mesh timepoints")["id"])
    base = f"/api/v1/projects/{project_id}"
    before = _mesh("survey-1", "2026-10-01T12:00:00Z", 1)
    after = _mesh("survey-2", "2026-10-02T07:00:00-05:00", 2)
    standalone = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["delta_surface_area_m2"] == pytest.approx(0.5)
    assert expected["delta_surface_area_scale_interval_m2"] == pytest.approx([0.205, 0.805])
    assert expected["relative_surface_area_change_percent"] == pytest.approx(100)
    assert expected["elapsed_days"] == pytest.approx(1)
    assert expected["average_surface_area_change_m2_per_day"] == pytest.approx(0.5)
    assert expected["before_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(sqrt(2))
    assert expected["after_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(sqrt(5))
    assert expected["delta_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(
        sqrt(5) - sqrt(2)
    )
    assert expected["relative_axis_aligned_bounding_box_diagonal_change_percent"] == (
        pytest.approx(100 * (sqrt(5) / sqrt(2) - 1))
    )
    relative_extent_bounds = expected[
        "relative_axis_aligned_bounding_box_diagonal_scale_interval_percent"
    ]
    assert relative_extent_bounds == pytest.approx(
        [
            100 * (0.9 * sqrt(5) / (1.1 * sqrt(2)) - 1),
            100 * (1.1 * sqrt(5) / (0.9 * sqrt(2)) - 1),
        ]
    )
    assert expected["delta_axis_aligned_bounding_box_diagonal_scale_interval_m"] == pytest.approx(
        [0.9 * sqrt(5) - 1.1 * sqrt(2), 1.1 * sqrt(5) - 0.9 * sqrt(2)]
    )
    assert expected["average_axis_aligned_bounding_box_diagonal_change_m_per_day"] == pytest.approx(
        sqrt(5) - sqrt(2)
    )
    assert "axis_aligned_extent_change_is_not_verified_branch_growth" in expected["qc_warnings"]
    rate_bounds = expected["average_surface_area_change_scale_interval_m2_per_day"]
    assert rate_bounds == pytest.approx([0.205, 0.805])
    warnings = expected["qc_warnings"]
    assert "average_change_per_day_is_not_a_biological_growth_rate" in warnings
    assert expected["measurement_status"] == "provisional_unverified_longitudinal_comparison"
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert "surface_area_change_is_not_verified_biological_growth" in expected["qc_warnings"]
    assert "open_mesh_surface_not_enclosed" in expected["before_mesh_qc_warnings"]
    assert "open_mesh_surface_not_enclosed" in expected["after_mesh_qc_warnings"]
    assert "source_mesh_qc_requires_review" in expected["qc_warnings"]

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    node = next(
        item for item in registry.json() if item["node_type"] == "mesh_longitudinal_comparison"
    )
    assert node["executable"] is True
    assert [port["accepted_types"] for port in node["input_ports"]] == [
        ["mesh_measurement_preview"],
        ["mesh_measurement_preview"],
    ]
    graph = {
        "graph_id": "mesh-longitudinal-v14",
        "name": "Provisional coral timepoint comparison",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "early", "node_type": "mesh_surface_preview", "parameters": before},
            {"node_id": "late", "node_type": "mesh_surface_preview", "parameters": after},
            {"node_id": "compare", "node_type": "mesh_longitudinal_comparison"},
        ],
        "edges": [
            {
                "edge_id": "project-early",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "early",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-late",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "late",
                "target_port_id": "project",
            },
            {
                "edge_id": "early-compare",
                "source_node_id": "early",
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": "before",
            },
            {
                "edge_id": "late-compare",
                "source_node_id": "late",
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": "after",
            },
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    compare_step = next(
        step for step in plan.json()["steps"] if step["node_type"] == "mesh_longitudinal_comparison"
    )
    assert "unverified 3D mesh observations" in compare_step["action"]
    assert compare_step["output_types"]["comparison"] == ["mesh_longitudinal_comparison"]
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    completed = process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    assert completed, client.get(f"/api/v1/workflow-runs/{run.json()['id']}").json()
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64


def test_mesh_comparison_retains_source_qc_and_calibration_differences(
    client: TestClient,
) -> None:
    """Do not erase reconstruction defects when scan formats or methods differ."""
    project_id = str(create_project(client, "Cross-format mesh QC")["id"])
    before = _mesh("scan-1", "2026-10-01T12:00:00Z", 1)
    after = _mesh("scan-2", "2026-10-02T12:00:00Z", 2)
    after.pop("vertices")
    after.pop("faces")
    after["obj_text"] = "\n".join(
        ["v 0 0 0", "v 1 0 0", "v 0 2 0", "f 1 2 3"]
    )
    after["calibration_method"] = "instrument"
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert "open_mesh_surface_not_enclosed" in result["before_mesh_qc_warnings"]
    assert "open_mesh_surface_not_enclosed" in result["after_mesh_qc_warnings"]
    assert "source_mesh_qc_requires_review" in result["qc_warnings"]
    assert "mesh_source_formats_differ_between_observations" in result["qc_warnings"]
    assert "calibration_methods_differ_between_observations" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False


def test_mesh_comparison_runtime_context_is_not_a_user_parameter(
    client: TestClient,
) -> None:
    """Saved workflows inject execution IDs, not scientific node parameters."""
    app = cast(FastAPI, client.app)
    runtime_context = {
        "__workflow_run_id": "run-1",
        "__workflow_node_run_id": "node-1",
    }
    with app.state.session_factory() as session:
        # With no artifacts, the adapter must proceed past parameter validation.
        with pytest.raises(ValidationError, match="Each longitudinal input"):
            execute_mesh_longitudinal_comparison(
                session, app.state.settings, "project-1", runtime_context, {}
            )
        # Genuine user-supplied parameters remain disallowed.
        with pytest.raises(ValidationError, match="takes no node parameters"):
            execute_mesh_longitudinal_comparison(
                session,
                app.state.settings,
                "project-1",
                {**runtime_context, "unrecognized": "value"},
                {},
            )


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"specimen_id": "another-colony"}, "specimen_id"),
        ({"observation_id": "survey-1"}, "distinct observation_id"),
        ({"observed_at_utc": "2026-09-30T12:00:00Z"}, "increasing timestamps"),
    ],
)
def test_mesh_comparison_rejects_invalid_pairing(
    client: TestClient, change: dict, error: str
) -> None:
    project_id = str(create_project(client, "Reject unreviewed pairing")["id"])
    before = _mesh("survey-1", "2026-10-01T12:00:00Z", 1)
    after = {**_mesh("survey-2", "2026-10-02T12:00:00Z", 2), **change}
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 400
    assert error in response.text


def test_mesh_comparison_does_not_invent_scale_uncertainty() -> None:
    base = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "surface_area_scale_interval_m2": None,
        "project_id": "p1",
        "provenance": {
            "specimen_id": "colony-1",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "geometry_sha256": "a",
        },
    }
    later = {
        **base,
        "surface_area_m2": 2.0,
        "provenance": {
            **base["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "geometry_sha256": "b",
        },
    }
    result = compare_mesh_observations(base, later)
    assert result["delta_surface_area_m2"] == 1
    assert result["delta_surface_area_scale_interval_m2"] is None
    assert result["delta_axis_aligned_bounding_box_diagonal_m"] is None
    assert result["relative_axis_aligned_bounding_box_diagonal_change_percent"] is None
    assert result["relative_axis_aligned_bounding_box_diagonal_scale_interval_percent"] is None
    assert "axis_aligned_extent_comparison_unavailable" in result["qc_warnings"]
    assert result["average_surface_area_change_m2_per_day"] == pytest.approx(1)
    assert result["average_surface_area_change_scale_interval_m2_per_day"] is None
    assert result["relative_surface_area_scale_interval_percent"] is None
    assert "scale_uncertainty_interval_unavailable" in result["qc_warnings"]
    early_extent = {
        **base,
        "axis_aligned_bounding_box_diagonal_m": 1.0,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": [0.9, 1.1],
    }
    late_extent = {
        **later,
        "axis_aligned_bounding_box_diagonal_m": 2.0,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": None,
    }
    extent_result = compare_mesh_observations(early_extent, late_extent)
    assert extent_result["delta_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(1)
    assert extent_result["relative_axis_aligned_bounding_box_diagonal_change_percent"] == (
        pytest.approx(100)
    )
    relative_bounds = extent_result[
        "relative_axis_aligned_bounding_box_diagonal_scale_interval_percent"
    ]
    assert relative_bounds is None
    assert extent_result["delta_axis_aligned_bounding_box_diagonal_scale_interval_m"] is None
    assert "extent_scale_uncertainty_interval_unavailable" in extent_result["qc_warnings"]
    malformed = {
        **late_extent,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": [2.1, 2.2],
    }
    malformed_result = compare_mesh_observations(early_extent, malformed)
    assert malformed_result["delta_axis_aligned_bounding_box_diagonal_scale_interval_m"] is None
    with pytest.raises(ValueError, match="verification state"):
        compare_mesh_observations(
            {**base, "provenance": {**base["provenance"], "calibration_verified": True}},
            later,
        )


@pytest.mark.parametrize(
    ("invalid_timepoint", "invalid_interval"),
    [
        ("before", [1.1, 1.2]),
        ("before", [0.8, 0.9]),
        ("after", [2.1, 2.2]),
        ("after", [1.8, 1.9]),
    ],
)
def test_mesh_comparison_withholds_scale_bounds_excluding_nominal_area(
    invalid_timepoint: str, invalid_interval: list[float]
) -> None:
    """Unreviewed scale intervals must enclose their reported nominal areas."""
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "surface_area_scale_interval_m2": [0.8, 1.2],
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
        },
    }
    after = {
        **before,
        "surface_area_m2": 2.0,
        "surface_area_scale_interval_m2": [1.8, 2.2],
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
        },
    }
    record = before if invalid_timepoint == "before" else after
    record["surface_area_scale_interval_m2"] = invalid_interval
    result = compare_mesh_observations(before, after)
    assert result["delta_surface_area_m2"] == pytest.approx(1.0)
    assert result["delta_surface_area_scale_interval_m2"] is None
    assert result["relative_surface_area_scale_interval_percent"] is None
    assert result["average_surface_area_change_scale_interval_m2_per_day"] is None
    assert "scale_uncertainty_interval_unavailable" in result["qc_warnings"]


def test_mesh_comparison_average_rate_preserves_negative_change(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Mesh declining area")["id"])
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={
            "before": _mesh("early", "2026-10-01T12:00:00Z", 2),
            "after": _mesh("late", "2026-10-03T12:00:00Z", 1),
        },
    )
    assert response.status_code == 200, response.text
    comparison = response.json()
    assert comparison["elapsed_days"] == pytest.approx(2)
    assert comparison["delta_surface_area_m2"] == pytest.approx(-0.5)
    assert comparison["delta_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(
        sqrt(2) - sqrt(5)
    )
    daily_extent_change = comparison["average_axis_aligned_bounding_box_diagonal_change_m_per_day"]
    assert daily_extent_change == pytest.approx((sqrt(2) - sqrt(5)) / 2)
    assert comparison["relative_axis_aligned_bounding_box_diagonal_change_percent"] == (
        pytest.approx(100 * (sqrt(2) / sqrt(5) - 1))
    )
    assert comparison["average_surface_area_change_m2_per_day"] == pytest.approx(-0.25)
    rate_bounds = comparison["average_surface_area_change_scale_interval_m2_per_day"]
    assert rate_bounds == pytest.approx([-0.4025, -0.1025])
    assert comparison["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize(
    "invalid_area",
    [None, True, False, "1.0", -0.01, float("nan"), float("inf")],
)
@pytest.mark.parametrize("invalid_timepoint", ["before", "after"])
def test_mesh_comparison_rejects_non_numeric_area(
    invalid_area: object, invalid_timepoint: str
) -> None:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "surface_area_scale_interval_m2": [0.8, 1.2],
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "survey-1",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
        },
    }
    after = {
        **before,
        "provenance": {
            **before["provenance"],
            "observation_id": "survey-2",
            "observed_at_utc": "2026-10-02T12:00:00Z",
        },
    }
    target = before if invalid_timepoint == "before" else after
    target["surface_area_m2"] = invalid_area
    with pytest.raises(ValueError, match="finite and nonnegative"):
        compare_mesh_observations(before, after)


def test_mesh_comparison_zero_baseline_extent_withholds_relative_change() -> None:
    """Zero baseline cannot define percent change, even with known scale intervals."""
    base = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 0.0,
        "surface_area_scale_interval_m2": [0.0, 0.0],
        "axis_aligned_bounding_box_diagonal_m": 0.0,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": [0.0, 0.0],
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "geometry_sha256": "first-geometry",
        },
    }
    later = {
        **base,
        "surface_area_m2": 1.0,
        "surface_area_scale_interval_m2": [0.81, 1.21],
        "axis_aligned_bounding_box_diagonal_m": 2.0,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": [1.8, 2.2],
        "provenance": {
            **base["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "geometry_sha256": "second-geometry",
        },
    }
    comparison = compare_mesh_observations(base, later)
    assert comparison["delta_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(2)
    assert comparison["relative_axis_aligned_bounding_box_diagonal_change_percent"] is None
    relative_bounds = comparison[
        "relative_axis_aligned_bounding_box_diagonal_scale_interval_percent"
    ]
    assert relative_bounds is None
    assert "relative_axis_aligned_extent_change_unavailable" in comparison["qc_warnings"]
    assert comparison["provenance"]["coordinate_registration_verified"] is False
