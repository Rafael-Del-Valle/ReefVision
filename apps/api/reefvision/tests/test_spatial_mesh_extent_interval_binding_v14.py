"""Longitudinal extent uncertainty cannot be narrowed by edited preview artifacts."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.tests.test_annotations import create_project


def _parameters(observation: str, date: str, height: int) -> dict:
    return {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, height, 0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Provisional field scale",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "coral-16",
        "observation_id": observation,
        "observed_at_utc": date,
    }


def test_extent_intervals_reject_forged_or_unknown_uncertainty(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Bound 3D extent uncertainty")["id"])
    base = f"/api/v1/projects/{project_id}"
    previews = []
    for params in (
        _parameters("visit-1", "2026-10-01T12:00:00Z", 1),
        _parameters("visit-2", "2026-10-02T12:00:00Z", 2),
    ):
        response = client.post(f"{base}/spatial/mesh-preview", json=params)
        assert response.status_code == 200, response.text
        previews.append(response.json())
    before, after = previews
    baseline = compare_mesh_observations(before, after)
    assert baseline["delta_axis_aligned_bounding_box_diagonal_scale_interval_m"] is not None

    for side in ("before", "after"):
        changed = deepcopy(before if side == "before" else after)
        nominal = changed["axis_aligned_bounding_box_diagonal_m"]
        changed["axis_aligned_bounding_box_diagonal_scale_interval_m"] = [
            nominal * 0.99,
            nominal * 1.01,
        ]
        args = (changed, after) if side == "before" else (before, changed)
        with pytest.raises(ValueError, match="Bounding-box scale interval contradicts"):
            compare_mesh_observations(*args)

        # Unknown scale uncertainty cannot support a purported exact interval.
        changed = deepcopy(before if side == "before" else after)
        changed["provenance"]["relative_scale_uncertainty"] = None
        changed["surface_area_scale_interval_m2"] = None
        args = (changed, after) if side == "before" else (before, changed)
        with pytest.raises(ValueError, match="Bounding-box scale interval requires"):
            compare_mesh_observations(*args)


def test_extent_intervals_match_standalone_and_persisted_graph(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Saved 3D extent bounds")["id"])
    base = f"/api/v1/projects/{project_id}"
    before = _parameters("visit-1", "2026-10-01T12:00:00Z", 1)
    after = _parameters("visit-2", "2026-10-02T12:00:00Z", 2)
    standalone = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": "extent-uncertainty-binding-v14",
        "name": "Unverified longitudinal extent bounds",
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
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact == expected
