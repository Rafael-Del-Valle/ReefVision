"""Surface trace uncertainty must not masquerade as a zero-width interval.

These synthetic probes do not validate biological branch length or calibration.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_paths_v14 import mesh_surface_edge_traces
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project


PARAMS = {
    "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    "faces": [[0, 1, 2]],
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Synthetic unverified ruler",
    "relative_scale_uncertainty": 1e-17,
    "surface_path_vertex_pairs": [[0, 1]],
    "surface_trace_vertex_paths": [[0, 1]],
}


def _check_resolution_limited_trace(trace: dict) -> None:
    assert trace["length_m"] == pytest.approx(0.01)
    assert trace["segment_lengths_m"] == [0.01]
    assert trace["cumulative_lengths_m"] == [0.0, 0.01]
    assert trace["length_scale_only_interval_m"] is None
    assert trace["segment_length_scale_only_intervals_m"] is None
    assert trace["cumulative_length_scale_only_intervals_m"] is None
    assert trace["endpoint_chord_scale_only_interval_m"] is None
    assert "surface_trace_scale_interval_below_numeric_resolution" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


def test_roundoff_withholds_trace_intervals_but_keeps_nominal_geometry() -> None:
    direct = mesh_surface_edge_traces(
        [tuple(point) for point in PARAMS["vertices"]],
        PARAMS["faces"],
        PARAMS["surface_trace_vertex_paths"],
        PARAMS["meters_per_unit"],
        PARAMS["relative_scale_uncertainty"],
    )
    assert direct is not None
    _check_resolution_limited_trace(direct[0])
    preview = measure_mesh_preview(**PARAMS)
    _check_resolution_limited_trace(preview["surface_edge_traces"][0])
    assert "path_scale_interval_below_numeric_resolution" in (
        preview["surface_edge_paths"][0]["path_qc_warnings"]
    )


@pytest.mark.parametrize("uncertainty", [None, 0.0, 1.0])
def test_absent_zero_and_full_scale_uncertainty_are_distinct(
    uncertainty: float | None,
) -> None:
    result = measure_mesh_preview(**{**PARAMS, "relative_scale_uncertainty": uncertainty})
    trace = result["surface_edge_traces"][0]
    assert "surface_trace_scale_interval_below_numeric_resolution" not in trace["qc_warnings"]
    expected = (
        None
        if uncertainty is None
        else [0.01 * (1 - uncertainty), 0.01 * (1 + uncertainty)]
    )
    assert trace["length_scale_only_interval_m"] == pytest.approx(expected) if expected is not None else trace["length_scale_only_interval_m"] is None
    assert trace["segment_length_scale_only_intervals_m"] is None if uncertainty is None else trace["segment_length_scale_only_intervals_m"][0] == pytest.approx(expected)
    assert trace["endpoint_chord_scale_only_interval_m"] == pytest.approx(expected) if expected is not None else trace["endpoint_chord_scale_only_interval_m"] is None


def test_subresolution_trace_survives_standalone_and_two_persisted_runs(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Surface trace precision QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone_response = client.post(f"{base}/spatial/mesh-preview", json=PARAMS)
    assert standalone_response.status_code == 200, standalone_response.text
    standalone = standalone_response.json()
    _check_resolution_limited_trace(standalone["surface_edge_traces"][0])
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "subresolution-trace-uncertainty-v14",
        "name": "Provisional selected surface trace scale precision",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": PARAMS},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    assert saved.json()["graph_json"]["nodes"][1]["parameters"] == PARAMS

    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            item for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == standalone
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]
