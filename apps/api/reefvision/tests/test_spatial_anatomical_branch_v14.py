"""Project-backed, provisional anatomical centerline evidence and replay."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project


def _source(client: TestClient) -> tuple[str, dict[str, Any]]:
    project_id = create_project(client, "Centerline reference mesh")["id"]
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(
        f"{base}/spatial/assets",
        files={"file": ("branch.obj", b"v 0 0 0\nv 4 0 0\nv 0 4 0\nf 1 2 3\n")},
    )
    assert imported.status_code == 201, imported.text
    asset = imported.json()
    return base, {
        "asset_id": asset["id"],
        "expected_source_payload_sha256": asset["sha256"],
        "coordinate_frame_id": "specimen-source",
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic ruler control",
        "relative_scale_uncertainty": 0.1,
        "anatomical_branch": {
            "ordered_points_source_units": [[0, 0, 0], [0.3, 0.4, 0], [2.3, 0.4, 0]],
            "base_landmark": "Branch junction",
            "tip_landmark": "Terminal polyp axis",
            "selection_method": "Manual centerline from three points",
            "operator_id": "operator-1",
        },
    }


def test_declared_centerline_preview_and_two_workflow_runs_agree(client: TestClient) -> None:
    base, payload = _source(client)
    result = client.post(f"{base}/spatial/mesh-preview", json=payload)
    assert result.status_code == 200, result.text
    artifact = result.json()["declared_branch_centerline"]
    assert artifact["length_m"] == pytest.approx(0.025)
    assert artifact["scale_only_length_interval_m"] == pytest.approx([0.0225, 0.0275])
    assert artifact["source_payload_sha256"] == payload["expected_source_payload_sha256"]
    assert artifact["coordinate_frame_id"] == "specimen-source"
    assert artifact["anatomical_claim_verified"] is False
    assert artifact["evidence_status"] == "provisional_missing_evidence"
    assert artifact["declaration"] == {**payload["anatomical_branch"], "protocol": None}

    graph = {
        "graph_id": "declared-anatomical-branch",
        "name": "Synthetic branch centerline",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "measure", "node_type": "mesh_surface_preview", "parameters": payload},
        ],
        "edges": [
            {
                "edge_id": "source",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "measure",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    graph_id = saved.json()["id"]
    reopened = client.get(f"{base}/workflow-graphs").json()
    assert (
        reopened[0]["graph_json"]["nodes"][1]["parameters"]["anatomical_branch"]
        == (payload["anatomical_branch"])
    )
    app = cast(FastAPI, client.app)
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": graph_id})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, run.json()["job_id"]
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}").json()
        assert detail["run"]["status"] == "succeeded"
        measured = next(
            item for item in detail["artifacts"] if item["data_type"] == "mesh_measurement_preview"
        )
        assert measured["payload_json"]["declared_branch_centerline"] == artifact
        assert len(measured["payload_sha256"]) == 64


def test_protocol_reference_and_repeatability_stay_provisional(client: TestClient) -> None:
    base, payload = _source(client)
    protocol = {
        "protocol_reference": "preregistration-001",
        "independent_reference_id": "branch-measurement-archive-01",
        "independent_reference_observer_id": "observer-2",
        "independent_reference_length_m": 0.026,
        "independent_reference_scale_evidence": "Independent ruler calibration",
        "repeatability_reference": "repeatability-log-01",
        "repeated_lengths_m": [0.021, 0.028],
        "maximum_reference_error_m": 0.005,
        "maximum_repeatability_range_m": 0.01,
        "adjudicator_id": "reviewer-3",
    }
    payload["anatomical_branch"]["protocol"] = protocol

    result = client.post(f"{base}/spatial/mesh-preview", json=payload)
    assert result.status_code == 200, result.text
    measured = result.json()["declared_branch_centerline"]
    assert measured["declaration"]["protocol"] == protocol
    assert measured["reference_absolute_error_m"] == pytest.approx(0.001)
    assert measured["repeatability_range_m"] == pytest.approx(0.007)
    assert measured["evidence_status"] == "awaiting_independent_adjudication"
    assert measured["anatomical_claim_verified"] is False

    protocol["maximum_repeatability_range_m"] = 0.001
    result = client.post(f"{base}/spatial/mesh-preview", json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["declared_branch_centerline"]["evidence_status"] == (
        "declared_tolerances_exceeded"
    )

    protocol["independent_reference_observer_id"] = "OPERATOR-1"
    assert client.post(f"{base}/spatial/mesh-preview", json=payload).status_code == 422


def test_unbound_out_of_frame_and_repeated_centerline_points_are_rejected(
    client: TestClient,
) -> None:
    base, payload = _source(client)
    assert (
        client.post(
            f"{base}/spatial/mesh-preview",
            json={**payload, "expected_source_payload_sha256": None},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{base}/spatial/mesh-preview",
            json={**payload, "expected_source_payload_sha256": "0" * 64},
        ).status_code
        == 400
    )
    declaration = payload["anatomical_branch"]
    declaration["ordered_points_source_units"] = [[0, 0, 0], [2, 2, 5], [1, 0, 0]]
    out_of_frame = client.post(f"{base}/spatial/mesh-preview", json=payload)
    assert out_of_frame.status_code == 400, out_of_frame.text
    declaration["ordered_points_source_units"] = [[0, 0, 0], [0, 0, 0]]
    assert client.post(f"{base}/spatial/mesh-preview", json=payload).status_code == 422

    generic = client.post(
        f"{base}/spatial/mesh-preview",
        json={key: value for key, value in payload.items() if key != "anatomical_branch"},
    )
    assert generic.status_code == 200, generic.text
    assert "declared_branch_centerline" not in generic.json()
