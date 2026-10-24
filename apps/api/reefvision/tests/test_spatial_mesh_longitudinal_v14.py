"""Provisional mesh timepoint comparison: API, QC and persisted typed graph parity."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
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
    rate_bounds = expected["average_surface_area_change_scale_interval_m2_per_day"]
    assert rate_bounds == pytest.approx([0.205, 0.805])
    warnings = expected["qc_warnings"]
    assert "average_change_per_day_is_not_a_biological_growth_rate" in warnings
    assert expected["measurement_status"] == "provisional_unverified_longitudinal_comparison"
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert "surface_area_change_is_not_verified_biological_growth" in expected["qc_warnings"]

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
        step
        for step in plan.json()["steps"]
        if step["node_type"] == "mesh_longitudinal_comparison"
    )
    assert "unverified 3D mesh observations" in compare_step["action"]
    assert compare_step["output_types"]["comparison"] == ["mesh_longitudinal_comparison"]
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
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64


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
    assert result["average_surface_area_change_m2_per_day"] == pytest.approx(1)
    assert result["average_surface_area_change_scale_interval_m2_per_day"] is None
    assert result["relative_surface_area_scale_interval_percent"] is None
    assert "scale_uncertainty_interval_unavailable" in result["qc_warnings"]
    with pytest.raises(ValueError, match="verification state"):
        compare_mesh_observations(
            {**base, "provenance": {**base["provenance"], "calibration_verified": True}},
            later,
        )


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
