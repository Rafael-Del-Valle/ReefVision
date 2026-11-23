"""Scientific QC for opt-in raw PLY RGB palette retention in bounded previews."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project

CALIBRATION = {
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Synthetic unverified color acquisition scale",
    "relative_scale_uncertainty": 0.1,
}


def _colored_ply(rows: list[str]) -> str:
    return (
        "ply\nformat ascii 1.0\n"
        f"element vertex {len(rows)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n" + "\n".join(rows) + "\n"
    )


def _graph(params: dict) -> dict:
    return {
        "graph_id": "raw-rgb-triplet-retention-v14",
        "name": "Raw PLY palette retention (not biological condition)",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "c", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "c",
                "target_port_id": "project",
            }
        ],
    }


def test_palette_pinning_keeps_rare_color_without_requiring_all_xyz_rgb_pairs(
    client: TestClient,
) -> None:
    # All 600 XYZ/RGB pairs differ, but there are only two raw RGB triplets.
    # The rare color lies outside the ordinary deterministic 512-row sample.
    uniform_indices = {i * 599 // 511 for i in range(512)}
    rare_index = next(i for i in range(1, 599) if i not in uniform_indices)
    points = [[float(i), 0.0, 0.0] for i in range(600)]
    colors = [[200, 100, 50] if i == rare_index else [10, 20, 30] for i in range(600)]
    rows = [f"{i} 0 0 {rgb[0]} {rgb[1]} {rgb[2]}" for i, rgb in enumerate(colors)]
    pid = str(create_project(client, "Distinct raw color retention")["id"])
    base = f"/api/v1/projects/{pid}"
    params = {**CALIBRATION, "ply_text": _colored_ply(rows)}
    default = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    protected_params = {**params, "preserve_distinct_rgb_triplets_in_preview": True}
    pinned = client.post(f"{base}/spatial/point-cloud-preview", json=protected_params)
    assert default.status_code == 200, default.text
    assert pinned.status_code == 200, pinned.text
    ordinary, measured = default.json(), pinned.json()
    assert rare_index not in ordinary["preview_point_indices"]
    assert rare_index in measured["preview_point_indices"]
    assert len(measured["preview_point_indices"]) == 512
    assert measured["preview_distinct_rgb_triplets_preservation_requested"] is True
    assert "distinct_rgb_triplets_preserving" in measured["preview_sampling_strategy"]
    assert measured["preview_distinct_xyz_rgb_pairs_preservation_requested"] is False
    before = ordinary["preview_rgb_variant_support"]
    after = measured["preview_rgb_variant_support"]
    assert before["source_distinct_rgb_triplets"] == 2
    assert before["preview_distinct_rgb_triplets"] == 1
    assert before["preview_omitted_distinct_rgb_triplets"] == 1
    assert "preview_omits_distinct_rgb_triplets" in ordinary["qc_warnings"]
    assert after["source_distinct_rgb_triplets"] == 2
    assert after["preview_distinct_rgb_triplets"] == 2
    assert after["preview_omitted_distinct_rgb_triplets"] == 0
    assert after["fraction_of_source_rgb_triplets_displayed"] == 1.0
    assert after["source_distinct_xyz_rgb_pairs"] == 600
    assert after["preview_distinct_xyz_rgb_pairs"] == 512
    assert "preview_omits_distinct_rgb_triplets" not in measured["qc_warnings"]
    assert "preview_omits_distinct_xyz_rgb_observations" in measured["qc_warnings"]
    assert "preview_shifts_rgb_triplet_frequency_distribution" in measured["qc_warnings"]
    assert measured["provenance"] == ordinary["provenance"]
    assert measured["provenance"]["calibration_verified"] is False
    assert measured["provenance"]["specimen_identity_verified"] is False
    assert measured["surface_area_m2"] is None
    assert measured["branch_length_m"] is None

    direct = measure_point_cloud_preview(
        points=points,
        point_colors=colors,
        preserve_distinct_rgb_triplets_in_preview=True,
        **CALIBRATION,
    )
    assert direct["preview_point_indices"] == measured["preview_point_indices"]
    assert direct["provenance"]["geometry_sha256"] == measured["provenance"]["geometry_sha256"]

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    node = next(n for n in registry.json() if n["node_type"] == "point_cloud_preview")
    assert node["executable"] is True
    assert node["optional_parameters"]["preserve_distinct_rgb_triplets_in_preview"] is False
    graph = _graph(protected_params)
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    hashes: list[str] = []
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
            if item["data_type"] == "point_cloud_measurement_preview"
        )
        assert artifact["payload_json"] == measured
        hashes.append(artifact["payload_sha256"])
    assert len(set(hashes)) == 1
    assert len(hashes[0]) == 64


def test_palette_pinning_fails_closed_for_missing_rgb_or_more_than_512_colors(
    client: TestClient,
) -> None:
    pid = str(create_project(client, "Over-budget raw color requests")["id"])
    base = f"/api/v1/projects/{pid}"
    endpoint = f"{base}/spatial/point-cloud-preview"
    uncolored = {**CALIBRATION, "points": [[0, 0, 0], [1, 0, 0]]}
    missing_colors = client.post(
        endpoint,
        json={**uncolored, "preserve_distinct_rgb_triplets_in_preview": True},
    )
    assert missing_colors.status_code == 400, missing_colors.text
    assert "colored PLY" in missing_colors.text
    invalid_type = client.post(
        endpoint,
        json={**uncolored, "preserve_distinct_rgb_triplets_in_preview": "true"},
    )
    assert invalid_type.status_code == 422, invalid_type.text
    with pytest.raises(ValueError, match="must be a boolean"):
        measure_point_cloud_preview(
            points=[[0, 0, 0], [1, 0, 0]],
            preserve_distinct_rgb_triplets_in_preview="true",  # type: ignore[arg-type]
            **CALIBRATION,
        )

    # Only three different XYZ loci, but 513 distinct raw sensor color triplets.
    rows = [f"{i // 256} 0 0 {i % 256} {i // 256} 0" for i in range(513)]
    params = {
        **CALIBRATION,
        "ply_text": _colored_ply(rows),
        "preserve_distinct_rgb_triplets_in_preview": True,
    }
    with pytest.raises(ValueError, match="Protected point indices exceed the display budget"):
        measure_point_cloud_preview(
            points=[[float(i // 256), 0, 0] for i in range(513)],
            point_colors=[[i % 256, i // 256, 0] for i in range(513)],
            preserve_distinct_rgb_triplets_in_preview=True,
            **CALIBRATION,
        )
    response = client.post(endpoint, json=params)
    assert response.status_code == 400, response.text
    assert "display budget" in response.text
    graph = _graph(params)
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert (
            process_workflow_run_job(
                app.state.settings, app.state.session_factory, str(run.json()["job_id"])
            )
            is False
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "failed"
        assert "display budget" in detail.json()["run"]["error_message"]
        assert not any(
            artifact["data_type"] == "point_cloud_measurement_preview"
            for artifact in detail.json()["artifacts"]
        )
