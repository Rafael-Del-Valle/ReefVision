"""Project-scoped immutable source import and retrieval acceptance."""

from __future__ import annotations

from hashlib import sha256
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import SpatialSourceAsset
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project

OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


@pytest.mark.parametrize(
    "filename,payload,kind",
    [
        ("coral.obj", OBJ, "mesh"),
        ("survey.ply", b"ply\nformat ascii 1.0\nend_header\n", "mesh_or_point_cloud"),
        ("model.glb", b"glTF" + bytes(16), "mesh"),
    ],
)
def test_import_deduplicates_and_isolates_original_bytes(
    client: TestClient, filename: str, payload: bytes, kind: str
) -> None:
    project = str(create_project(client, "Spatial source")["id"])
    other = str(create_project(client, "Other spatial source")["id"])
    url = f"/api/v1/projects/{project}/spatial/assets"
    response = client.post(url, files={"file": (filename, payload)})
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["sha256"] == sha256(payload).hexdigest()
    assert asset["size_bytes"] == len(payload)
    assert asset["source_kind"] == kind
    assert asset["measurement_status"] == "source_unreviewed"
    assert asset["calibration_verified"] is False
    assert asset["specimen_identity_verified"] is False
    assert "managed_path" not in asset
    duplicate = client.post(url, files={"file": (filename, payload)})
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == asset["id"]
    assert len(client.get(url).json()) == 1
    assert client.get(f"{url}/{asset['id']}/content").content == payload
    assert client.get(f"/api/v1/projects/{other}/spatial/assets").json() == []
    assert client.get(f"/api/v1/projects/{other}/spatial/assets/{asset['id']}").status_code == 404
    assert (
        client.get(f"/api/v1/projects/{other}/spatial/assets/{asset['id']}/content").status_code
        == 404
    )


@pytest.mark.parametrize(
    "filename,payload",
    [
        ("../escape.obj", OBJ),
        ("folder\\escape.ply", OBJ),
        ("coral.exe", OBJ),
        ("empty.obj", b""),
        ("too-large.obj", b"x" * (8 * 1024 * 1024 + 1)),
    ],
)
def test_invalid_source_is_rejected(client: TestClient, filename: str, payload: bytes) -> None:
    project = str(create_project(client, "Reject spatial source")["id"])
    url = f"/api/v1/projects/{project}/spatial/assets"
    response = client.post(url, files={"file": (filename, payload)})
    assert response.status_code == 400, response.text
    assert client.get(url).json() == []


def test_persisted_obj_measurement_matches_saved_workflow_and_detects_tampering(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Asset-bound mesh workflow")["id"])
    other_id = str(create_project(client, "Unrelated mesh workflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(f"{base}/spatial/assets", files={"file": ("colony.obj", OBJ)})
    assert imported.status_code == 201, imported.text
    asset_id = imported.json()["id"]
    params = {
        "asset_id": asset_id,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified survey scale target",
        "relative_scale_uncertainty": 0.05,
    }
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    result = standalone.json()
    assert result["surface_area_m2"] == pytest.approx(0.00005)
    assert result["provenance"]["spatial_source_asset_id"] == asset_id
    assert result["provenance"]["source_payload_sha256"] == sha256(OBJ).hexdigest()
    assert result["provenance"]["source_payload_integrity_checked"] is True
    assert result["provenance"]["calibration_verified"] is False
    assert "project_source_original_unreviewed" in result["qc_warnings"]
    graph = {
        "graph_id": "persisted-obj-v14",
        "name": "Project-owned mesh source",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "p-m",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "m",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact == result
    assert (
        client.post(f"/api/v1/projects/{other_id}/spatial/mesh-preview", json=params).status_code
        == 404
    )
    assert (
        client.post(
            f"{base}/spatial/mesh-preview", json={**params, "obj_text": OBJ.decode()}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{base}/spatial/mesh-preview",
            json={**params, "expected_source_payload_sha256": "0" * 64},
        ).status_code
        == 400
    )
    with app.state.session_factory() as session:
        record = session.get(SpatialSourceAsset, asset_id)
        assert record is not None
        original_path = resolve_managed_project_path(app.state.settings, record.managed_path)
        original_path.write_bytes(b" " + OBJ[1:])  # same size, changed digest
    assert client.post(f"{base}/spatial/mesh-preview", json=params).status_code == 400


def test_standalone_longitudinal_comparison_resolves_project_assets(client: TestClient) -> None:
    project_id = str(create_project(client, "Asset-bound longitudinal comparison")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(f"{base}/spatial/assets", files={"file": ("coral.obj", OBJ)})
    assert imported.status_code == 201, imported.text
    asset_id = imported.json()["id"]
    common = {
        "asset_id": asset_id,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified field ruler",
        "specimen_id": "colony:16",
    }
    response = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={
            "before": {
                **common,
                "observation_id": "survey-1",
                "observed_at_utc": "2026-10-01T12:00:00Z",
            },
            "after": {
                **common,
                "observation_id": "survey-2",
                "observed_at_utc": "2026-10-02T12:00:00Z",
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["delta_surface_area_m2"] == pytest.approx(0)
    assert (
        response.json()["provenance"]["before_geometry_sha256"]
        == response.json()["provenance"]["after_geometry_sha256"]
    )


@pytest.mark.parametrize(
    ("filename", "original", "endpoint", "node_type", "artifact_type"),
    [
        ("colony.obj", OBJ, "mesh-preview", "mesh_surface_preview", "mesh_measurement_preview"),
        (
            "survey.ply",
            (
                b"ply\nformat ascii 1.0\nelement vertex 3\n"
                b"property float x\nproperty float y\nproperty float z\n"
                b"end_header\n0 0 0\n1 0 0\n0 1 0\n"
            ),
            "point-cloud-preview",
            "point_cloud_preview",
            "point_cloud_measurement_preview",
        ),
    ],
)
def test_asset_path_identity_cannot_be_rebound_in_saved_workflow(
    client: TestClient,
    filename: str,
    original: bytes,
    endpoint: str,
    node_type: str,
    artifact_type: str,
) -> None:
    """A matching digest alone cannot authorize a different managed source path."""
    project_id = str(create_project(client, "Immutable 3D source identity")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(f"{base}/spatial/assets", files={"file": (filename, original)})
    assert imported.status_code == 201, imported.text
    asset = imported.json()
    params = {
        "asset_id": asset["id"],
        "expected_source_payload_sha256": asset["sha256"],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified field ruler",
        "relative_scale_uncertainty": 0.05,
    }
    assert client.post(f"{base}/spatial/{endpoint}", json=params).status_code == 200
    graph = {
        "graph_id": f"immutable-path-{node_type}",
        "name": "Asset identity replay guard",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "measure", "node_type": node_type, "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-measure",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "measure",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        record = session.get(SpatialSourceAsset, asset["id"])
        assert record is not None
        # Simulate metadata corruption: the alternate file has the same bytes
        # and SHA-256, but is not the original bound to this asset ID.
        prefix = record.managed_path.rsplit("/", 1)[0]
        record.managed_path = f"{prefix}/substituted-{record.id}.{record.source_format}"
        alternate = resolve_managed_project_path(app.state.settings, record.managed_path)
        alternate.write_bytes(original)
        session.commit()

    content = client.get(f"{base}/spatial/assets/{asset['id']}/content")
    assert content.status_code == 400, content.text
    standalone = client.post(f"{base}/spatial/{endpoint}", json=params)
    assert standalone.status_code == 400, standalone.text

    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(item["data_type"] == artifact_type for item in detail.json()["artifacts"])
