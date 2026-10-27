"""Selected 3D point-chord measurement and saved-workflow parity tests."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project

PARAMS = {
    "points": [[0, 0, 0], [3, 4, 0], [3, 4, 12]],
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unverified ruler",
    "relative_scale_uncertainty": 0.1,
    "point_index_pairs": [[0, 1], [1, 2]],
}


def test_chord_measurements_and_saved_graph(client: TestClient) -> None:
    project_id = str(create_project(client, "Point chord preview")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/point-cloud-preview", json=PARAMS)
    assert response.status_code == 200, response.text
    expected = response.json()
    chords = expected["selected_point_chords"]
    assert [entry["chord_distance_m"] for entry in chords] == pytest.approx([0.05, 0.12])
    assert [entry["scale_uncertainty_m"] for entry in chords] == pytest.approx([0.005, 0.012])
    for chord, interval in zip(chords, ([0.045, 0.055], [0.108, 0.132]), strict=True):
        assert chord["chord_distance_scale_interval_m"] == pytest.approx(interval)
    assert expected["branch_length_m"] is None
    assert expected["provenance"]["calibration_verified"] is False
    assert len(expected["provenance"]["ordered_geometry_sha256"]) == 64

    # The request schema rejects non-integer indices (422), while the
    # measurement service rejects semantically invalid pairs (400).
    for pair in ([True, 1], [0.0, 1]):
        invalid = client.post(
            f"{base}/spatial/point-cloud-preview",
            json={**PARAMS, "point_index_pairs": [pair]},
        )
        assert invalid.status_code == 422, invalid.text

    for pair in ([0, 0], [0, 3], [0, 1, 2]):
        invalid = client.post(
            f"{base}/spatial/point-cloud-preview",
            json={**PARAMS, "point_index_pairs": [pair]},
        )
        assert invalid.status_code == 400, invalid.text
        assert "two distinct in-range integer indices" in invalid.json()["detail"]

    graph = {
        "graph_id": "point-chords-v14",
        "name": "Unverified 3D point chords",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "cloud",
                "node_type": "point_cloud_preview",
                "parameters": PARAMS,
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
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    assert artifact["payload_json"]["selected_point_chords"] == chords
    assert artifact["payload_json"]["provenance"] == expected["provenance"]
    assert artifact["payload_json"]["measurement_status"] == ("caller_supplied_unverified")


def test_repeated_unordered_point_chords_are_flagged_in_saved_workflow(
    client: TestClient,
) -> None:
    # A reversed or repeated source-index pair is the same chord, not
    # independent evidence of additional coral structure.
    params = {
        **PARAMS,
        "point_index_pairs": [[0, 1], [1, 0], [1, 2], [0, 1]],
    }
    project_id = str(create_project(client, "Repeated point chord QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    chords = expected["selected_point_chords"]
    assert [chord["qc_warnings"] for chord in chords] == [
        [],
        ["repeated_point_pair"],
        [],
        ["repeated_point_pair"],
    ]
    assert chords[0]["chord_distance_m"] == pytest.approx(
        chords[1]["chord_distance_m"]
    )
    assert chords[0]["endpoint_ordered_geometry_sha256"] != (
        chords[1]["endpoint_ordered_geometry_sha256"]
    )
    assert "repeated_selected_point_pairs" in expected["qc_warnings"]
    assert expected["branch_length_m"] is None
    assert expected["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": "repeated-point-chords-v14",
        "name": "Flag duplicate source-index chord evidence",
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
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    assert artifact["payload_json"]["selected_point_chords"] == chords
    assert artifact["payload_json"]["qc_warnings"] == expected["qc_warnings"]
    assert artifact["payload_json"]["provenance"] == expected["provenance"]
    assert len(artifact["payload_sha256"]) == 64
