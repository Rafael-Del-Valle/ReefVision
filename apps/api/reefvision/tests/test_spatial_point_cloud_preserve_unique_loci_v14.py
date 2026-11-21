"""Full-cloud distinct XYZ locus retention remains provisional display-only QC."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project


def _points() -> list[list[float]]:
    # The only nonzero locus occupies index 299, omitted by uniform 512/600
    # sampling. Repeated rows are not independent XYZ spatial observations.
    points = [[0.0, 0.0, 0.0] for _ in range(600)]
    points[299] = [100.0, 1.0, 0.0]
    return points


def _params(source_format: str) -> dict:
    points = _points()
    params = {
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Provisional synthetic scan ruler",
        "relative_scale_uncertainty": 0.1,
        "preserve_distinct_xyz_loci_in_preview": True,
        "specimen_id": "provisional-colony-1",
        "observation_id": "scan-1",
    }
    if source_format == "ply":
        params["ply_text"] = (
            f"ply\nformat ascii 1.0\nelement vertex {len(points)}\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n"
            + "".join(f"{x:g} {y:g} {z:g}\n" for x, y, z in points)
        )
    else:
        params["points"] = points
    return params


def test_direct_locus_pinning_preserves_rare_location_without_claiming_replication() -> None:
    points = _points()
    kwargs = {
        "points": points,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic unverified ruler",
        "relative_scale_uncertainty": 0.1,
    }
    default = measure_point_cloud_preview(**kwargs)
    pinned = measure_point_cloud_preview(**kwargs, preserve_distinct_xyz_loci_in_preview=True)
    assert 299 not in default["preview_point_indices"]
    assert 299 in pinned["preview_point_indices"]
    assert default["preview_unique_coordinate_count"] == 1
    assert pinned["preview_unique_coordinate_count"] == 2
    assert pinned["preview_unique_coordinate_coverage_fraction"] == 1.0
    assert pinned["preview_point_indices"] == sorted(pinned["preview_point_indices"])
    assert len(pinned["preview_point_indices"]) == 512
    assert pinned["preview_distinct_xyz_loci_preservation_requested"] is True
    assert "distinct_xyz_loci_preserving" in pinned["preview_sampling_strategy"]
    assert "preview_omits_unique_coordinate_loci" not in pinned["qc_warnings"]
    assert "duplicate_points_present" in pinned["qc_warnings"]
    assert pinned["duplicate_point_row_count"] == 598
    assert pinned["surface_area_m2"] is None
    assert pinned["branch_length_m"] is None
    assert pinned["provenance"]["calibration_verified"] is False
    # Display policy must not change full-source geometry or measurements.
    assert pinned["provenance"]["geometry_sha256"] == default["provenance"]["geometry_sha256"]
    assert pinned["axis_aligned_dimensions_m"] == default["axis_aligned_dimensions_m"]


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_full_xyz_locus_retention_replays_in_persisted_typed_graph(
    client: TestClient, source_format: str
) -> None:
    project_id = str(create_project(client, "Distinct XYZ preview retention")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = _params(source_format)
    node_catalog = client.get("/api/v1/workflow-graphs/node-registry")
    assert node_catalog.status_code == 200, node_catalog.text
    # Graph execution contract and UI registry must advertise the same control.
    nodes = node_catalog.json()
    entries = nodes if isinstance(nodes, list) else nodes.get("nodes", nodes)
    if isinstance(entries, dict):
        definition = entries["point_cloud_preview"]
    else:
        definition = next(entry for entry in entries if entry["node_type"] == "point_cloud_preview")
    assert definition["optional_parameters"]["preserve_distinct_xyz_loci_in_preview"] is False

    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert 299 in expected["preview_point_indices"]
    assert expected["preview_unique_coordinate_count"] == expected["unique_point_count"] == 2
    assert expected["preview_unique_coordinate_coverage_fraction"] == 1.0
    assert expected["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": f"full-loci-{source_format}-v14",
        "name": "Display every observed XYZ source location, not every source row",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-to-cloud",
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
    hashes = []
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
            artifact
            for artifact in detail.json()["artifacts"]
            if artifact["data_type"] == "point_cloud_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == expected
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_locus_retention_rejects_overbudget_and_nonboolean_requests(
    client: TestClient, source_format: str
) -> None:
    project_id = str(create_project(client, "Overbudget XYZ preview")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = _params(source_format)
    invalid = dict(params)
    invalid["preserve_distinct_xyz_loci_in_preview"] = "true"
    response = client.post(f"{base}/spatial/point-cloud-preview", json=invalid)
    assert response.status_code == 422, response.text

    points = [[float(index), 0.0, 0.0] for index in range(600)]
    if source_format == "ply":
        params["ply_text"] = (
            f"ply\nformat ascii 1.0\nelement vertex {len(points)}\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n"
            + "".join(f"{x:g} {y:g} {z:g}\n" for x, y, z in points)
        )
    else:
        params["points"] = points
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    # A valid request whose geometry exceeds the display budget is a
    # domain-level ValueError (400), not a schema-validation error (422).
    assert response.status_code == 400, response.text
    assert "display budget" in response.text.lower()


def test_direct_locus_retention_rejects_overbudget_and_nonboolean() -> None:
    kwargs = {
        "points": [[float(index), 0.0, 0.0] for index in range(600)],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic unverified ruler",
    }
    with pytest.raises(ValueError, match="display budget"):
        measure_point_cloud_preview(**kwargs, preserve_distinct_xyz_loci_in_preview=True)
    with pytest.raises(ValueError, match="must be a boolean"):
        measure_point_cloud_preview(**kwargs, preserve_distinct_xyz_loci_in_preview=1)


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_exactly_full_unique_locus_budget_keeps_all_loci_without_duplicate_final_row(
    client: TestClient, source_format: str
) -> None:
    # 512 genuine source locations plus a repeated final acquisition row.
    # Complete unique-location retention is mathematically possible: the last
    # duplicate must not become a compulsory 513th protected preview index.
    points = [[float(index), 0.0, 0.0] for index in range(512)]
    points.append([0.0, 0.0, 0.0])
    params = {
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Provisional synthetic scale, not independently verified",
        "preserve_distinct_xyz_loci_in_preview": True,
    }
    if source_format == "ply":
        params["ply_text"] = (
            f"ply\nformat ascii 1.0\nelement vertex {len(points)}\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n"
            + "".join(f"{x:g} {y:g} {z:g}\n" for x, y, z in points)
        )
    else:
        params["points"] = points

    project_id = str(create_project(client, "Full unique-locus preview budget")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["point_count"] == 513
    assert expected["unique_point_count"] == 512
    assert expected["preview_unique_coordinate_count"] == 512
    assert expected["preview_unique_coordinate_coverage_fraction"] == 1.0
    assert expected["preview_point_indices"] == list(range(512))
    assert expected["preview_source_acquisition_endpoint_support"] == {
        "first_row_displayed": True,
        "last_row_displayed": False,
    }
    assert "preview_omits_acquisition_endpoint_row" in expected["qc_warnings"]
    assert "preview_omits_unique_coordinate_loci" not in expected["qc_warnings"]
    assert expected["surface_area_m2"] is None
    assert expected["branch_length_m"] is None
    assert expected["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": f"exact-unique-budget-{source_format}-v14",
        "name": "Retain all 512 unique XYZ loci before duplicate final row",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-to-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
                "target_port_id": "project",
            }
        ],
    }
    planned = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert planned.status_code == 200, planned.text
    assert planned.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    hashes = []
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
            artifact
            for artifact in detail.json()["artifacts"]
            if artifact["data_type"] == "point_cloud_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == expected
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]
