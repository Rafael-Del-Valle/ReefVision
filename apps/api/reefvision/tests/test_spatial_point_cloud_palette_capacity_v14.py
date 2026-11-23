"""Exact preview-capacity boundary for raw RGB palette and joint XYZ/RGB evidence."""

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
    "calibration_evidence": "Synthetic, unverified source-scale witness",
    "relative_scale_uncertainty": 0.1,
}


def _source() -> tuple[list[list[float]], list[list[int]], str]:
    # 513 spatial/color pairs but exactly 512 distinct raw RGB triplets.
    points = [[float(i), 0.0, 0.0] for i in range(513)]
    colors = [[i % 256, i // 256, 0] for i in range(512)] + [[0, 0, 0]]
    rows = [f"{i} 0 0 {rgb[0]} {rgb[1]} {rgb[2]}" for i, rgb in enumerate(colors)]
    text = (
        "ply\nformat ascii 1.0\n"
        f"element vertex {len(rows)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n" + "\n".join(rows) + "\n"
    )
    return points, colors, text


def _graph(params: dict, suffix: str) -> dict:
    return {
        "graph_id": f"exact-palette-capacity-{suffix}",
        "name": f"Exact raw palette capacity: {suffix}",
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


def test_exact_palette_capacity_and_conflicting_pair_preservation_in_saved_graphs(
    client: TestClient,
) -> None:
    points, colors, ply_text = _source()
    project_id = str(create_project(client, "Raw palette capacity boundary")["id"])
    base = f"/api/v1/projects/{project_id}"
    palette_only = {
        **CALIBRATION,
        "ply_text": ply_text,
        "preserve_distinct_rgb_triplets_in_preview": True,
    }
    both = {**palette_only, "preserve_distinct_xyz_rgb_pairs_in_preview": True}
    ok = client.post(f"{base}/spatial/point-cloud-preview", json=palette_only)
    assert ok.status_code == 200, ok.text
    artifact = ok.json()
    assert artifact["preview_point_indices"] == list(range(512))
    assert artifact["preview_distinct_rgb_triplets_preservation_requested"] is True
    assert artifact["preview_distinct_xyz_rgb_pairs_preservation_requested"] is False
    support = artifact["preview_rgb_variant_support"]
    assert support["source_distinct_rgb_triplets"] == 512
    assert support["preview_distinct_rgb_triplets"] == 512
    assert support["preview_omitted_distinct_rgb_triplets"] == 0
    assert support["source_distinct_xyz_rgb_pairs"] == 513
    assert support["preview_distinct_xyz_rgb_pairs"] == 512
    assert "preview_omits_distinct_rgb_triplets" not in artifact["qc_warnings"]
    assert "preview_omits_distinct_xyz_rgb_observations" in artifact["qc_warnings"]
    assert artifact["provenance"]["calibration_verified"] is False
    assert artifact["provenance"]["specimen_identity_verified"] is False
    assert artifact["surface_area_m2"] is None
    assert artifact["branch_length_m"] is None

    direct = measure_point_cloud_preview(
        points=points,
        point_colors=colors,
        preserve_distinct_rgb_triplets_in_preview=True,
        **CALIBRATION,
    )
    assert direct["preview_point_indices"] == artifact["preview_point_indices"]
    assert direct["preview_rgb_variant_support"] == support
    with pytest.raises(ValueError, match="Protected point indices exceed the display budget"):
        measure_point_cloud_preview(
            points=points,
            point_colors=colors,
            preserve_distinct_rgb_triplets_in_preview=True,
            preserve_distinct_xyz_rgb_pairs_in_preview=True,
            **CALIBRATION,
        )
    rejected = client.post(f"{base}/spatial/point-cloud-preview", json=both)
    assert rejected.status_code == 400, rejected.text
    assert "display budget" in rejected.text

    # Both independent requests must keep the same boundary when persisted.
    app = cast(FastAPI, client.app)
    for suffix, params, expected in (
        ("palette", palette_only, "succeeded"),
        ("pairs", both, "failed"),
    ):
        graph = _graph(params, suffix)
        plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
        assert plan.status_code == 200, plan.text
        assert plan.json()["executable"] is True
        saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
        assert saved.status_code == 201, saved.text
        hashes: list[str] = []
        for _ in range(2):
            run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
            assert run.status_code == 202, run.text
            succeeded = process_workflow_run_job(
                app.state.settings, app.state.session_factory, str(run.json()["job_id"])
            )
            assert succeeded is (expected == "succeeded")
            detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["run"]["status"] == expected
            outputs = [
                item
                for item in detail.json()["artifacts"]
                if item["data_type"] == "point_cloud_measurement_preview"
            ]
            if expected == "succeeded":
                assert len(outputs) == 1
                assert outputs[0]["payload_json"] == artifact
                hashes.append(outputs[0]["payload_sha256"])
            else:
                assert "display budget" in detail.json()["run"]["error_message"]
                assert outputs == []
        if expected == "succeeded":
            assert len(set(hashes)) == 1
            assert len(hashes[0]) == 64


def test_combined_palette_and_locus_preservation_reuses_shared_rows_in_saved_graphs(
    client: TestClient,
) -> None:
    # 513 distinct XYZ/RGB pairs, but just 512 distinct XYZ loci and colors.
    # RGB 1 first occurs at row 1, while locus 1 first occurs at row 2.
    # Pinning those first occurrences independently wastes the 513th slot:
    # row 2 covers both requirements and row 1 can safely be omitted.
    points = [[float(max(0, index - 1)), 0.0, 0.0] for index in range(513)]
    colors = [[0, 0, 0], [1, 0, 0]] + [
        [(index - 1) % 256, (index - 1) // 256, 0]
        for index in range(2, 513)
    ]
    rows = [
        f"{int(point[0])} 0 0 {rgb[0]} {rgb[1]} {rgb[2]}"
        for point, rgb in zip(points, colors, strict=True)
    ]
    ply_text = (
        "ply\\nformat ascii 1.0\\n"
        f"element vertex {len(rows)}\\n"
        "property float x\\nproperty float y\\nproperty float z\\n"
        "property uchar red\\nproperty uchar green\\nproperty uchar blue\\n"
        "end_header\\n" + "\\n".join(rows) + "\\n"
    )
    params = {
        **CALIBRATION,
        "ply_text": ply_text,
        "preserve_distinct_xyz_loci_in_preview": True,
        "preserve_distinct_rgb_triplets_in_preview": True,
    }
    project_id = str(create_project(client, "Shared capture for color and XYZ")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    artifact = response.json()
    selected = [0, *range(2, 513)]
    assert artifact["preview_point_indices"] == selected
    assert artifact["preview_unique_coordinate_count"] == 512
    assert artifact["preview_unique_coordinate_coverage_fraction"] == 1.0
    assert artifact["preview_distinct_xyz_loci_preservation_requested"] is True
    assert artifact["preview_distinct_rgb_triplets_preservation_requested"] is True
    support = artifact["preview_rgb_variant_support"]
    assert support["source_distinct_rgb_triplets"] == 512
    assert support["preview_distinct_rgb_triplets"] == 512
    assert support["source_distinct_xyz_rgb_pairs"] == 513
    assert support["preview_distinct_xyz_rgb_pairs"] == 512
    assert "preview_omits_distinct_rgb_triplets" not in artifact["qc_warnings"]
    assert "preview_omits_distinct_xyz_rgb_observations" in artifact["qc_warnings"]
    assert artifact["provenance"]["calibration_verified"] is False
    assert artifact["provenance"]["specimen_identity_verified"] is False
    assert artifact["surface_area_m2"] is None
    assert artifact["branch_length_m"] is None

    direct = measure_point_cloud_preview(
        points=points,
        point_colors=colors,
        preserve_distinct_xyz_loci_in_preview=True,
        preserve_distinct_rgb_triplets_in_preview=True,
        **CALIBRATION,
    )
    assert direct["preview_point_indices"] == selected
    assert direct["provenance"]["geometry_sha256"] == artifact["provenance"]["geometry_sha256"]

    graph = _graph(params, "shared-acquisition")
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
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
        outputs = [
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "point_cloud_measurement_preview"
        ]
        assert len(outputs) == 1
        assert outputs[0]["payload_json"] == artifact
        hashes.append(outputs[0]["payload_sha256"])
    assert len(set(hashes)) == 1
    assert len(hashes[0]) == 64
