"""Every timepoint's scale evidence must be checked even if its peer lacks bounds."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.workflow_mesh_v14 import execute_mesh_longitudinal_comparison
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_longitudinal_v14 import (
    _mesh,
    _minimal_topology_pair,
)


@pytest.mark.parametrize(
    ("field", "nominal_field", "error"),
    [
        (
            "surface_area_scale_interval_m2",
            "surface_area_m2",
            "Surface-area scale interval contradicts source uncertainty",
        ),
        (
            "axis_aligned_bounding_box_diagonal_scale_interval_m",
            "axis_aligned_bounding_box_diagonal_m",
            "Bounding-box scale interval contradicts source uncertainty",
        ),
    ],
)
def test_later_forged_scale_bounds_rejected_when_earlier_bounds_missing(
    field: str, nominal_field: str, error: str
) -> None:
    before, after = _minimal_topology_pair()
    for record in (before, after):
        record["provenance"]["relative_scale_uncertainty"] = 0.1
        record["axis_aligned_bounding_box_diagonal_m"] = 2.0
    # The first observation has unknown bounds; the second cannot use that
    # absence to bypass independent validation of its own fabricated interval.
    before[field] = None
    after[field] = [after[nominal_field], after[nominal_field]]
    with pytest.raises(ValueError, match=error):
        compare_mesh_observations(before, after)

    # The executable typed Workflow Builder adapter must reject exactly the
    # same scientific evidence, not emit an apparently usable comparison.
    artifacts = {
        port: [
            SimpleNamespace(data_type="mesh_measurement_preview", payload_json=record)
        ]
        for port, record in (("before", before), ("after", after))
    }
    with pytest.raises(ValidationError, match=error):
        execute_mesh_longitudinal_comparison(None, None, "project-1", {}, artifacts)


def test_missing_early_bounds_still_withhold_combined_intervals() -> None:
    before, after = _minimal_topology_pair()
    for record in (before, after):
        record["provenance"]["relative_scale_uncertainty"] = 0.1
        record["axis_aligned_bounding_box_diagonal_m"] = 2.0
    after["surface_area_scale_interval_m2"] = [0.81, 1.21]
    after["axis_aligned_bounding_box_diagonal_scale_interval_m"] = [1.8, 2.2]
    result = compare_mesh_observations(before, after)
    assert result["delta_surface_area_scale_interval_m2"] is None
    assert result["delta_axis_aligned_bounding_box_diagonal_scale_interval_m"] is None
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"


def test_incomplete_scale_bounds_standalone_and_saved_graph_parity(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Incomplete 3D calibration bounds")["id"])
    base = f"/api/v1/projects/{project_id}"
    early = _mesh("early", "2026-10-01T12:00:00Z", 1.0)
    late = _mesh("late", "2026-10-02T12:00:00Z", 2.0)
    early.pop("relative_scale_uncertainty")
    standalone = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": early, "after": late},
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["delta_surface_area_scale_interval_m2"] is None
    assert expected["delta_axis_aligned_bounding_box_diagonal_scale_interval_m"] is None
    assert expected["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": "incomplete-scale-bounds-v14",
        "name": "Provisional comparison with incomplete calibration bounds",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "early", "node_type": "mesh_surface_preview", "parameters": early},
            {"node_id": "late", "node_type": "mesh_surface_preview", "parameters": late},
            {"node_id": "compare", "node_type": "mesh_longitudinal_comparison"},
        ],
        "edges": [
            {
                "edge_id": f"project-{target}",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": target,
                "target_port_id": "project",
            }
            for target in ("early", "late")
        ]
        + [
            {
                "edge_id": f"{source}-compare",
                "source_node_id": source,
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": port,
            }
            for source, port in (("early", "before"), ("late", "after"))
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
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64
