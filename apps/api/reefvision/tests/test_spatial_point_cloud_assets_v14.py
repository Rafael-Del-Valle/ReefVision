"""Project-owned PLY point-cloud execution and saved-workflow parity."""

from __future__ import annotations

from hashlib import sha256
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import SpatialSourceAsset
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project

PLY = (
    b"ply\nformat ascii 1.0\nelement vertex 3\n"
    b"property float x\nproperty float y\nproperty float z\n"
    b"end_header\n0 0 0\n1 0 0\n0 1 0\n"
)


def test_project_point_cloud_standalone_and_saved_workflow_match(client: TestClient) -> None:
    project_id = str(create_project(client, "Persisted point cloud")["id"])
    other_id = str(create_project(client, "Other point cloud")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(f"{base}/spatial/assets", files={"file": ("survey.ply", PLY)})
    assert imported.status_code == 201, imported.text
    asset_id = imported.json()["id"]
    params = {
        "asset_id": asset_id,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified field scale target",
        "relative_scale_uncertainty": 0.05,
        "expected_source_payload_sha256": sha256(PLY).hexdigest(),
    }
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    result = standalone.json()
    assert result["point_count"] == 3
    assert result["provenance"]["spatial_source_asset_id"] == asset_id
    assert result["provenance"]["spatial_source_asset_sha256"] == sha256(PLY).hexdigest()
    assert result["provenance"]["source_payload_integrity_checked"] is True
    assert result["provenance"]["specimen_identity_verified"] is False
    assert "project_source_original_unreviewed" in result["qc_warnings"]

    graph = {
        "graph_id": "persisted-ply-cloud-v14",
        "name": "Project-owned PLY point cloud",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "c", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "p-c",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "c",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    completed = process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    assert completed is True
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    assert artifact == result

    cross_project = client.post(
        f"/api/v1/projects/{other_id}/spatial/point-cloud-preview", json=params
    )
    assert cross_project.status_code == 404
    mixed = client.post(
        f"{base}/spatial/point-cloud-preview",
        json={**params, "ply_text": PLY.decode("ascii")},
    )
    assert mixed.status_code == 422
    stale = client.post(
        f"{base}/spatial/point-cloud-preview",
        json={**params, "expected_source_payload_sha256": "0" * 64},
    )
    assert stale.status_code == 400

    with app.state.session_factory() as session:
        record = session.get(SpatialSourceAsset, asset_id)
        assert record is not None
        original_path = resolve_managed_project_path(app.state.settings, record.managed_path)
        original_path.write_bytes(PLY.replace(b"1 0 0", b"2 0 0"))
    tampered = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert tampered.status_code == 400


def test_point_cloud_asset_rejects_mesh_original(client: TestClient) -> None:
    project_id = str(create_project(client, "Wrong spatial format")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(
        f"{base}/spatial/assets",
        files={"file": ("mesh.obj", b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")},
    )
    assert imported.status_code == 201, imported.text
    response = client.post(
        f"{base}/spatial/point-cloud-preview",
        json={
            "asset_id": imported.json()["id"],
            "meters_per_unit": 1,
            "calibration_method": "other",
            "calibration_evidence": "Unverified",
        },
    )
    assert response.status_code == 400
