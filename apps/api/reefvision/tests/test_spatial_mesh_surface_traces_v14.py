"""Caller-selected triangle-edge traces: provisional geometry and saved-workflow parity."""

from __future__ import annotations

from math import sqrt
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

PARAMS = {
    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    "faces": [[0, 1, 2]],
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Provisional ruler observation, not an anatomical centerline",
    "relative_scale_uncertainty": 0.1,
    "surface_path_vertex_pairs": [[0, 1]],
    "surface_trace_vertex_paths": [[0, 2, 1]],
}


def test_trace_follows_selected_edges_not_the_shortest_route() -> None:
    result = measure_mesh_preview(**PARAMS)
    trace = result["surface_edge_traces"][0]
    assert trace["trace_type"] == "caller_selected_mesh_surface_edges"
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"
    assert trace["human_review_verified"] is False
    assert trace["vertex_indices"] == [0, 2, 1]
    assert trace["vertices_in_source_frame_m"] == [
        [0.0, 0.0, 0.0],
        [0.0, 0.01, 0.0],
        [0.01, 0.0, 0.0],
    ]
    assert trace["segment_lengths_m"] == pytest.approx([0.01, sqrt(2) * 0.01])
    expected = (1 + sqrt(2)) * 0.01
    assert trace["length_m"] == pytest.approx(expected)
    assert trace["cumulative_lengths_m"] == pytest.approx(
        [0.0, 0.01, expected]
    )
    assert trace["length_scale_only_interval_m"] == pytest.approx(
        [expected * 0.9, expected * 1.1]
    )
    assert trace["length_m"] > result["surface_edge_paths"][0]["length_m"]
    assert trace["qc_warnings"] == [
        "caller_selected_surface_trace_not_anatomical_centerline",
        "open_boundary_edge_on_surface_trace",
    ]
    assert result["measurement_status"] == "caller_supplied_unverified"


@pytest.mark.parametrize(
    "paths",
    [
        [[0]],
        [[0, 0]],
        [[0, 1, 0]],
        [[0, 3]],
        [[True, 1]],
        [[-1, 2]],
        [[0, 1]] * 17,
    ],
)
def test_trace_schema_or_engine_rejects_invalid_vertex_paths(
    client: TestClient, paths: list[list[int]]
) -> None:
    project_id = str(create_project(client, "Bad surface trace")["id"])
    params = {**PARAMS, "surface_trace_vertex_paths": paths}
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params
    )
    assert response.status_code == 422, response.text


def test_selected_trace_requires_real_triangle_edges(client: TestClient) -> None:
    project_id = str(create_project(client, "Disconnected surface trace")["id"])
    params = {
        **PARAMS,
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [2, 0, 0]],
        "surface_trace_vertex_paths": [[0, 3]],
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params
    )
    assert response.status_code == 422, response.text


def test_omitted_trace_does_not_invent_anatomical_centerlines() -> None:
    params = {key: value for key, value in PARAMS.items() if key != "surface_trace_vertex_paths"}
    result = measure_mesh_preview(**params)
    assert result["surface_edge_traces"] is None


@pytest.mark.parametrize("uncertainty", [None, 1.0])
def test_trace_scale_boundary_is_explicit_and_not_a_confidence_interval(
    uncertainty: float | None,
) -> None:
    result = measure_mesh_preview(
        **{**PARAMS, "relative_scale_uncertainty": uncertainty}
    )
    trace = result["surface_edge_traces"][0]
    expected = (1 + sqrt(2)) * 0.01
    assert trace["length_scale_only_interval_m"] == (
        pytest.approx([0.0, 2 * expected]) if uncertainty is not None else None
    )
    assert trace["human_review_verified"] is False


def test_saved_typed_mesh_trace_matches_standalone_and_provenance(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Surface edge trace workflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=PARAMS)
    assert standalone.status_code == 200, standalone.text

    graph = {
        "graph_id": "mesh-surface-traces-v14",
        "name": "Provisional scientist-selected triangle edge trace",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": PARAMS},
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "m",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    assert (
        saved.json()["graph_json"]["nodes"][1]["parameters"]["surface_trace_vertex_paths"]
        == [[0, 2, 1]]
    )
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
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["surface_edge_traces"] == standalone.json()["surface_edge_traces"]
    assert artifact["provenance"] == standalone.json()["provenance"]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["surface_edge_traces"][0]["human_review_verified"] is False
