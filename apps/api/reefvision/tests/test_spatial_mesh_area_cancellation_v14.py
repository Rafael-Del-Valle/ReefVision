"""Near-parallel triangle area must use source-coordinate geometry, also in saved graphs."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_measurements import triangle_area
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project


@pytest.mark.parametrize(
    ("case", "vertices", "expected_area"),
    [
        (
            "rounded-zero",
            [[0, 0, 0], [100000001, 100000000, 0], [100000000, 99999999, 0]],
            0.5,
        ),
        (
            "incorrect-nonzero",
            [[0, 0, 0], [99999990, 99999991, 0], [99999993, 99999994, 0]],
            1.5,
        ),
        (
            "translated-and-reflected-xy",
            [
                [100000000, -200000000, 70000000],
                [200000001, -300000000, 70000000],
                [200000000, -299999999, 70000000],
            ],
            0.5,
        ),
        (
            "nearly-parallel-yz-plane",
            [
                [300000000, 0, 0],
                [300000000, 100000001, 100000000],
                [300000000, 100000000, 99999999],
            ],
            0.5,
        ),
        (
            "nearly-parallel-xz-plane",
            [
                [0, -300000000, 0],
                [99999990, -300000000, 99999991],
                [99999993, -300000000, 99999994],
            ],
            1.5,
        ),
    ],
)
def test_exact_triangle_area_replays_standalone_and_saved_graph(
    client: TestClient,
    case: str,
    vertices: list[list[float]],
    expected_area: float,
) -> None:
    """Exact integer XY determinants are -1 and -3, independent of vertex ordering."""
    # Independent integer arithmetic is exact for these source coordinates;
    # each adversarial triangle lies in an orthogonal plane.
    first_edge = [vertices[1][axis] - vertices[0][axis] for axis in range(3)]
    second_edge = [vertices[2][axis] - vertices[0][axis] for axis in range(3)]
    integer_cross = [
        first_edge[1] * second_edge[2] - first_edge[2] * second_edge[1],
        first_edge[2] * second_edge[0] - first_edge[0] * second_edge[2],
        first_edge[0] * second_edge[1] - first_edge[1] * second_edge[0],
    ]
    assert sum(component != 0 for component in integer_cross) == 1
    assert max(abs(component) for component in integer_cross) / 2 == expected_area

    points = [(vertex[0], vertex[1], vertex[2]) for vertex in vertices]
    assert triangle_area(points[0], points[1], points[2]) == expected_area
    assert triangle_area(points[0], points[2], points[1]) == expected_area

    parameters: dict[str, Any] = {
        "vertices": vertices,
        "faces": [[0, 1, 2]],
        "meters_per_unit": 1.0,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic unreviewed numerical reference",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "synthetic-not-a-coral",
    }
    direct = measure_mesh_preview(
        vertices=vertices,
        faces=[[0, 1, 2]],
        meters_per_unit=1.0,
        calibration_method="ruler",
        calibration_evidence="Synthetic unreviewed numerical reference",
        relative_scale_uncertainty=0.1,
    )
    assert direct["surface_area_m2"] == expected_area
    assert direct["surface_area_scale_interval_m2"] == pytest.approx(
        [expected_area * 0.9**2, expected_area * 1.1**2]
    )

    project_id = str(create_project(client, "Near-parallel mesh area reference")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["surface_area_m2"] == expected_area
    assert standalone["surface_area_scale_interval_m2"] == pytest.approx(
        [expected_area * 0.9**2, expected_area * 1.1**2]
    )
    assert standalone["enclosed_volume_m3"] is None
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False
    assert standalone["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": f"near-parallel-surface-area-{case}-v14",
        "name": "Provisional near-parallel surface area reference",
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
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
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
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == standalone
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


def test_true_collinearity_stays_zero_and_unrepresentable_area_is_not_zero() -> None:
    assert triangle_area((0.0, 0.0, 0.0), (1e8, 1e8, 0.0), (2e8, 2e8, 0.0)) == 0.0
    with pytest.raises(ValueError, match="underflowed numeric precision"):
        triangle_area((0.0, 0.0, 0.0), (1e-200, 0.0, 0.0), (0.0, 1e-200, 0.0))
