"""Reject silent numeric coercion in provisional 3D point-cloud science."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_point_cloud_v14 import PointCloudPreviewRequest
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project

PARAMS: dict[str, Any] = {
    "points": [[0, 0, 0], [3, 4, 0]],
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unverified field ruler",
    "relative_scale_uncertainty": 0.1,
}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("meters_per_unit", True),
        ("meters_per_unit", "0.01"),
        ("relative_scale_uncertainty", False),
        ("relative_scale_uncertainty", "0.1"),
        ("points", [[True, 0, 0], [3, 4, 0]]),
        ("points", [["0", 0, 0], [3, 4, 0]]),
    ],
)
def test_schema_rejects_coerced_scientific_numbers(field: str, value: object) -> None:
    with pytest.raises(PydanticValidationError):
        PointCloudPreviewRequest.model_validate({**PARAMS, field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("meters_per_unit", True),
        ("meters_per_unit", "0.01"),
        ("relative_scale_uncertainty", False),
        ("relative_scale_uncertainty", "0.1"),
        ("points", [[True, 0, 0], [3, 4, 0]]),
        ("points", [["0", 0, 0], [3, 4, 0]]),
    ],
)
def test_direct_service_rejects_coerced_scientific_numbers(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        measure_point_cloud_preview(**{**PARAMS, field: value})


def test_numeric_integer_coordinates_and_zero_uncertainty_remain_valid() -> None:
    request = PointCloudPreviewRequest.model_validate(
        {**PARAMS, "meters_per_unit": 1, "relative_scale_uncertainty": 0}
    )
    result = measure_point_cloud_preview(
        points=request.points,
        meters_per_unit=request.meters_per_unit,
        calibration_method=request.calibration_method,
        calibration_evidence=request.calibration_evidence,
        relative_scale_uncertainty=request.relative_scale_uncertainty,
    )
    assert result["selected_point_chords"] == []
    assert result["axis_aligned_dimensions_m"] == [3.0, 4.0, 0.0]
    assert result["provenance"]["relative_scale_uncertainty"] == 0
    assert result["provenance"]["calibration_verified"] is False
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("meters_per_unit", True),
        ("points", [[0, 0, 0], ["3", 4, 0]]),
    ],
)
def test_api_and_saved_workflow_reject_coercion_without_artifact(
    client: TestClient, field: str, value: object
) -> None:
    project_id = str(create_project(client, "Point-cloud numeric integrity")["id"])
    base = f"/api/v1/projects/{project_id}"
    invalid = {**PARAMS, field: value}
    response = client.post(f"{base}/spatial/point-cloud-preview", json=invalid)
    assert response.status_code == 422, response.text

    graph = {
        "graph_id": "point-cloud-strict-numbers-v14",
        "name": "Reject coerced calibration or geometry",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": invalid},
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


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_calibration_underflow_standalone_and_workflow_fail_closed(
    client: TestClient, source_format: str
) -> None:
    """Do not record a physically nonzero point as calibrated zero."""
    project_id = str(create_project(client, f"Underflow {source_format}")["id"])
    base = f"/api/v1/projects/{project_id}"
    tiny_points = [[0.0, 0.0, 0.0], [1e-30, 0.0, 0.0]]
    tiny_ply = (
        "ply\nformat ascii 1.0\nelement vertex 2\n"
        "property double x\nproperty double y\nproperty double z\n"
        "end_header\n0 0 0\n1e-30 0 0\n"
    )
    params: dict[str, Any] = {
        "meters_per_unit": 1e-300,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified subnormal calibration",
    }
    if source_format == "xyz":
        params["points"] = tiny_points
    else:
        params["ply_text"] = tiny_ply
    with pytest.raises(ValueError, match="underflows after calibration"):
        measure_point_cloud_preview(
            points=tiny_points,
            meters_per_unit=1e-300,
            calibration_method="ruler",
            calibration_evidence="Unverified subnormal calibration",
        )
    direct = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert direct.status_code == 400, direct.text

    graph = {
        "graph_id": f"point-cloud-underflow-{source_format}",
        "name": "Reject unrepresentable calibrated coordinates",
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


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_nonzero_point_cloud_span_does_not_collapse_in_saved_workflow(
    client: TestClient, source_format: str
) -> None:
    """Nonzero calibrated endpoints alone do not prove a resolvable span."""
    points = [[1e-20, 0, 0], [1e-20 + 1e-30, 0, 0]]
    scale = 1e-300
    assert points[0][0] != points[1][0]
    assert points[0][0] * scale != 0.0
    assert points[0][0] * scale == points[1][0] * scale
    params: dict[str, Any] = {
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic subnormal scale; not physically verified",
        "point_index_pairs": [[0, 1]],
    }
    if source_format == "xyz":
        params["points"] = points
    else:
        params["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 2\n"
            "property double x\nproperty double y\nproperty double z\n"
            "end_header\n1e-20 0 0\n1.0000000001e-20 0 0\n"
        )

    with pytest.raises(ValueError, match="axis span collapses after calibration"):
        measure_point_cloud_preview(
            points=points,
            meters_per_unit=scale,
            calibration_method="ruler",
            calibration_evidence="Synthetic subnormal scale; not physically verified",
            point_index_pairs=[[0, 1]],
        )
    project_id = str(create_project(client, f"Collapsed span {source_format}")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 400, standalone.text

    graph = {
        "graph_id": f"point-cloud-collapsed-span-{source_format}",
        "name": "Reject silently collapsed source-axis span",
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


@pytest.mark.parametrize(
    ("points", "scale", "expected_extent"),
    [
        ([[0, 0, 0], [1e-100, 0, 0]], 1e-200, 1e-300),
        ([[1e-20, 0, 0], [2e-20, 0, 0]], 1e-300, 1e-320),
    ],
)
def test_small_representable_point_cloud_survives_persisted_workflow(
    client: TestClient, points: list[list[float]], scale: float, expected_extent: float
) -> None:
    """Do not reject legitimately small but representable calibrated lengths."""
    project_id = str(create_project(client, "Representable tiny cloud")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "points": points,
        "point_index_pairs": [[0, 1]],
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified small-scale ruler",
        "relative_scale_uncertainty": 0.0,
    }
    direct = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert direct.status_code == 200, direct.text
    expected = direct.json()
    assert expected["axis_aligned_dimensions_m"][0] == expected_extent
    assert expected["axis_aligned_dimensions_m"][1:] == [0.0, 0.0]
    assert expected["selected_point_chords"][0]["chord_distance_m"] == expected_extent
    assert expected["selected_point_chords"][0]["qc_warnings"] == []
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["surface_area_m2"] is None
    assert expected["branch_length_m"] is None

    graph = {
        "graph_id": "point-cloud-representable-tiny",
        "name": "Retain representable calibrated extents",
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
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    assert artifact == expected


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_selected_chord_subresolution_separation_fails_without_workflow_artifact(
    client: TestClient, source_format: str
) -> None:
    """A cloud-wide extent cannot validate every shorter selected chord."""
    points = [[1e-20, 0.0, 0.0], [1.0000000001e-20, 0.0, 0.0], [1.0, 0.0, 0.0]]
    scale = 1e-300
    assert points[0][0] != points[1][0]
    assert points[0][0] * scale == points[1][0] * scale != 0.0
    assert (points[2][0] - points[0][0]) * scale != 0.0

    params: dict[str, Any] = {
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic short-chord precision control; unverified",
        "point_index_pairs": [[0, 1]],
    }
    if source_format == "xyz":
        params["points"] = points
    else:
        params["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 3\n"
            "property double x\nproperty double y\nproperty double z\n"
            "end_header\n1e-20 0 0\n1.0000000001e-20 0 0\n1 0 0\n"
        )
    with pytest.raises(ValueError, match="selected chord endpoints collapse"):
        measure_point_cloud_preview(
            points=points,
            meters_per_unit=scale,
            calibration_method=params["calibration_method"],
            calibration_evidence=params["calibration_evidence"],
            point_index_pairs=[[0, 1]],
        )

    project_id = str(create_project(client, f"Unresolvable chord {source_format}")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 400, standalone.text
    assert "selected chord endpoints collapse" in standalone.json()["detail"]

    graph = {
        "graph_id": f"point-cloud-unresolvable-chord-{source_format}",
        "name": "Reject a subresolution selected chord",
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


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
@pytest.mark.parametrize("sign", [-1, 1])
def test_calibrated_subnormal_centroid_survives_averaging_in_saved_workflow(
    client: TestClient, source_format: str, sign: int
) -> None:
    """Scale before averaging: a tiny raw mean may be zero while meters are not."""
    points = [[sign * 5e-324, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    scale = 1_000_000.0
    assert sum(point[0] for point in points) / len(points) * scale == 0.0
    expected_x = sign * (5e-324 * scale) / len(points)
    assert expected_x != 0.0

    params: dict[str, Any] = {
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic subnormal arithmetic; scale unverified",
        "relative_scale_uncertainty": 0.1,
    }
    if source_format == "xyz":
        params["points"] = points
    else:
        token = "-5e-324" if sign < 0 else "5e-324"
        params["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 3\n"
            "property double x\nproperty double y\nproperty double z\n"
            f"end_header\n{token} 0 0\n0 0 0\n0 0 0\n"
        )
    direct = measure_point_cloud_preview(
        points=points,
        meters_per_unit=scale,
        calibration_method="ruler",
        calibration_evidence="Synthetic subnormal arithmetic; scale unverified",
        relative_scale_uncertainty=0.1,
    )
    assert direct["arithmetic_centroid_in_source_frame_m"][0] == expected_x
    assert direct["arithmetic_centroid_in_source_frame_m"][1:] == [0.0, 0.0]
    assert direct["arithmetic_centroid_in_source_frame_scale_interval_m"][0] is not None
    assert direct["provenance"]["calibration_verified"] is False
    assert direct["branch_length_m"] is None

    project_id = str(create_project(client, f"Subnormal centroid {source_format} {sign}")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert (
        expected["arithmetic_centroid_in_source_frame_m"]
        == (direct["arithmetic_centroid_in_source_frame_m"])
    )
    assert (
        expected["arithmetic_centroid_in_source_frame_scale_interval_m"]
        == (direct["arithmetic_centroid_in_source_frame_scale_interval_m"])
    )
    graph = {
        "graph_id": f"subnormal-centroid-{source_format}-{sign}-v14",
        "name": "Review provisional calibrated centroid arithmetic",
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
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    for key, value in expected.items():
        assert artifact[key] == value
    assert artifact["project_id"] == project_id
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
@pytest.mark.parametrize(
    ("relative_uncertainty", "expected_interval", "unresolved"),
    [
        (0.0, [5e-324, 5e-324], False),
        (0.25, None, True),
        (1.0, [0.0, 1e-323], False),
    ],
)
def test_subnormal_diagonal_uncertainty_is_not_false_zero_in_saved_workflow(
    client: TestClient,
    source_format: str,
    relative_uncertainty: float,
    expected_interval: list[float] | None,
    unresolved: bool,
) -> None:
    """A representable diagonal must not report numerically collapsed scale certainty."""
    points = [[0.0, 0.0, 0.0], [5e-324, 0.0, 0.0]]
    params: dict[str, Any] = {
        "meters_per_unit": 1.0,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic subnormal diagonal; no verified scale",
        "relative_scale_uncertainty": relative_uncertainty,
    }
    if source_format == "xyz":
        params["points"] = points
    else:
        params["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 2\n"
            "property double x\nproperty double y\nproperty double z\n"
            "end_header\n0 0 0\n5e-324 0 0\n"
        )
    direct = measure_point_cloud_preview(
        points=points,
        meters_per_unit=1.0,
        calibration_method="ruler",
        calibration_evidence="Synthetic subnormal diagonal; no verified scale",
        relative_scale_uncertainty=relative_uncertainty,
    )
    assert direct["axis_aligned_bounding_box_diagonal_m"] == 5e-324
    assert direct["axis_aligned_bounding_box_diagonal_scale_interval_m"] == expected_interval
    assert (
        "diagonal_uncertainty_interval_below_numeric_resolution" in direct["qc_warnings"]
    ) is unresolved
    assert (direct["axis_aligned_bounding_box_diagonal_scale_uncertainty_m"] is None) is unresolved
    assert direct["surface_area_m2"] is None
    assert direct["branch_length_m"] is None
    assert direct["provenance"]["calibration_verified"] is False
    # A null subresolution interval must not be contradicted by a falsely
    # zero absolute scale uncertainty on that same positive dimension.
    assert direct["axis_aligned_dimension_scale_interval_m"][0] == expected_interval
    assert direct["axis_aligned_dimension_scale_uncertainty_m"] == [
        None if unresolved else 5e-324 * relative_uncertainty,
        0.0,
        0.0,
    ]
    assert (
        "dimension_uncertainty_interval_below_numeric_resolution" in direct["qc_warnings"]
    ) is unresolved

    project_id = str(create_project(client, "Subnormal diagonal interval v14")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["axis_aligned_bounding_box_diagonal_scale_interval_m"] == expected_interval
    assert expected["axis_aligned_dimension_scale_uncertainty_m"] == (
        direct["axis_aligned_dimension_scale_uncertainty_m"]
    )
    graph = {
        "graph_id": f"subnormal-diagonal-{source_format}-{relative_uncertainty}-v14",
        "name": "Inspect provisional diagonal uncertainty resolution",
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
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    for key, value in expected.items():
        assert artifact[key] == value
    assert artifact["project_id"] == project_id
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
@pytest.mark.parametrize(
    ("uncertainty", "expected_delta"),
    [(0.0, 0.0), (0.25, None), (1.0, 5e-324)],
)
def test_unresolved_chord_scale_delta_is_not_false_zero_in_saved_workflow(
    client: TestClient,
    source_format: str,
    uncertainty: float,
    expected_delta: float | None,
) -> None:
    """An unresolved subnormal chord interval must not advertise exact scale."""
    points = [[0.0, 0.0, 0.0], [5e-324, 0.0, 0.0]]
    params: dict[str, Any] = {
        "meters_per_unit": 1.0,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic, unverified subnormal chord scale",
        "relative_scale_uncertainty": uncertainty,
        "point_index_pairs": [[0, 1]],
    }
    if source_format == "xyz":
        params["points"] = points
    else:
        params["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 2\n"
            "property double x\nproperty double y\nproperty double z\n"
            "end_header\n0 0 0\n5e-324 0 0\n"
        )
    direct = measure_point_cloud_preview(
        points=points,
        meters_per_unit=1.0,
        calibration_method="ruler",
        calibration_evidence="Synthetic, unverified subnormal chord scale",
        relative_scale_uncertainty=uncertainty,
        point_index_pairs=[[0, 1]],
    )
    chord = direct["selected_point_chords"][0]
    assert chord["chord_distance_m"] == 5e-324
    assert chord["scale_uncertainty_m"] == expected_delta
    unresolved = expected_delta is None
    assert (
        "chord_uncertainty_interval_below_numeric_resolution" in chord["qc_warnings"]
    ) is unresolved
    assert (
        "selected_chord_uncertainty_interval_below_numeric_resolution" in direct["qc_warnings"]
    ) is unresolved
    assert (chord["chord_distance_scale_interval_m"] is None) is unresolved
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, f"Subnormal chord delta {source_format}")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["selected_point_chords"] == direct["selected_point_chords"]
    assert expected["qc_warnings"] == direct["qc_warnings"]

    graph = {
        "graph_id": f"subnormal-chord-delta-{source_format}-{uncertainty}-v14",
        "name": "Review provisional chord scale uncertainty",
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
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    for key, value in expected.items():
        assert artifact[key] == value
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False
