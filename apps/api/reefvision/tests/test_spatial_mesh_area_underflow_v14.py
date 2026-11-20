"""Prevent subnormal source triangles from becoming false zero-area surfaces."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_measurements import triangle_area
from reefvision.tests.test_annotations import create_project


def _parameters(edge: float) -> dict[str, Any]:
    return {
        "vertices": [[0.0, 0.0, 0.0], [edge, 0.0, 0.0], [0.0, edge, 0.0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 1.0,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic scale only; independently unverified",
        "relative_scale_uncertainty": 0.1,
    }


def _saved_graph(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_id": "mesh-area-numeric-integrity-v14",
        "name": "Bounded mesh triangle-area precision",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": parameters,
            },
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


def test_tiny_nondegenerate_triangle_never_becomes_zero_area() -> None:
    with pytest.raises(ValueError, match="area underflowed numeric precision"):
        triangle_area((0.0, 0.0, 0.0), (1e-200, 0.0, 0.0), (0.0, 1e-200, 0.0))
    # A truly collinear mesh stays degenerate, even at the same scale.
    collinear = triangle_area((0.0, 0.0, 0.0), (1e-200, 0.0, 0.0), (2e-200, 0.0, 0.0))
    assert collinear == 0.0
    # A small but representable area must remain measurable.
    small = triangle_area((0.0, 0.0, 0.0), (1e-100, 0.0, 0.0), (0.0, 1e-100, 0.0))
    assert small == pytest.approx(5e-201, abs=0.0)


def test_underflow_fails_standalone_and_persisted_graph_without_artifact(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Triangle area underflow QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = _parameters(1e-200)
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 400, response.text
    assert "area underflowed numeric precision" in response.text

    saved = client.post(f"{base}/workflow-graphs", json={"graph": _saved_graph(params)})
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
        artifact["data_type"] == "mesh_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )


def test_representable_tiny_area_replays_in_saved_typed_graph(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Representable triangle area QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = _parameters(1e-100)
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["surface_area_m2"] == pytest.approx(5e-201, abs=0.0)
    assert expected["measurement_status"] == "caller_supplied_unverified"
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["confidence_interval"] is None

    saved = client.post(f"{base}/workflow-graphs", json={"graph": _saved_graph(params)})
    assert saved.status_code == 201, saved.text
    hashes: list[str] = []
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
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == expected
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]
