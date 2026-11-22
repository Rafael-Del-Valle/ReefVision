"""Selected mesh-edge cumulative roundoff stays explicit in saved science artifacts."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

# All coordinates satisfy the public 1e9 source-coordinate bound.
# The path 0 -> 1 -> 3 has positive lengths 1e9 and 1e-8; the latter
# cannot advance a cumulative binary64 distance of 1e9.
GEOMETRY = {
    "vertices": [
        [0.0, 0.0, 0.0],
        [1_000_000_000.0, 0.0, 0.0],
        [1_000_000_000.0, 0.0, 1e-8],
        [1_000_000_000.0, 1e-8, 0.0],
    ],
    "faces": [[0, 1, 2], [1, 2, 3]],
    "meters_per_unit": 1.0,
    "calibration_method": "ruler",
    "calibration_evidence": "Synthetic unverified route precision reference",
    "relative_scale_uncertainty": 0.01,
    "surface_path_vertex_pairs": [[0, 3], [0, 1]],
}


def test_selected_route_cumulative_roundoff_is_exposed_and_replayed(
    client: TestClient,
) -> None:
    direct_paths = mesh_edge_paths(
        points=[tuple(vertex) for vertex in GEOMETRY["vertices"]],
        faces=GEOMETRY["faces"],
        pairs=GEOMETRY["surface_path_vertex_pairs"],
        scale=1.0,
        scale_uncertainty=0.01,
    )
    assert direct_paths is not None
    affected, unaffected = direct_paths
    assert affected["status"] == "connected"
    assert affected["path_vertex_indices"] == [0, 1, 3]
    assert affected["path_edge_lengths_m"] == [1_000_000_000.0, 1e-8]
    assert affected["path_cumulative_lengths_m"] == [
        0.0,
        1_000_000_000.0,
        1_000_000_000.0,
    ]
    assert affected["path_cumulative_lost_positive_segment_indices"] == [1]
    assert (
        "positive_selected_mesh_segment_lost_in_cumulative_distance"
        in affected["path_qc_warnings"]
    )
    assert affected["path_edge_length_scale_intervals_m"][1] == [
        1e-8 * 0.99,
        1e-8 * 1.01,
    ]
    assert unaffected["path_cumulative_lost_positive_segment_indices"] == []
    assert (
        "positive_selected_mesh_segment_lost_in_cumulative_distance"
        not in unaffected["path_qc_warnings"]
    )

    direct = measure_mesh_preview(**GEOMETRY)
    assert direct["surface_edge_paths"] == direct_paths
    assert direct["measurement_status"] == "caller_supplied_unverified"
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Mesh path cumulative numeric integrity")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=GEOMETRY)
    assert standalone.status_code == 200, standalone.text
    measured = standalone.json()
    assert measured["surface_edge_paths"] == direct_paths
    assert measured["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "mesh-cumulative-roundoff-v14",
        "name": "Mesh route cumulative-distance precision QC",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": GEOMETRY},
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
    digests: list[str] = []
    app = cast(FastAPI, client.app)
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifact = next(
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        )
        assert artifact["payload_json"] == measured
        digests.append(artifact["payload_sha256"])
    assert len(set(digests)) == 1
    assert len(digests[0]) == 64
