"""Durable background structural parsing for immutable project-owned 3D sources."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job
from reefvision.jobs.spatial_source_parse_v14 import process_spatial_source_parse_job
from reefvision.jobs.worker import process_next_thumbnail_job
from reefvision.tests.test_annotations import create_project

OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
POINT_PLY = b"""ply
format ascii 1.0
element vertex 2
property float x
property float y
property float z
end_header
0 0 0
1 2 3
"""


def _import(client: TestClient, project_id: str, name: str, content: bytes):
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/assets",
        files={"file": (name, content, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_import_queues_background_structural_parse_without_claiming_calibration(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Spatial parse job")["id"])
    asset = _import(client, project_id, "coral.obj", OBJ)
    assert asset["parse_status"] == "queued"
    assert asset["parse_job_id"]
    assert asset["parse_summary"] is None

    app = cast(FastAPI, client.app)
    assert process_spatial_source_parse_job(
        app.state.settings,
        app.state.session_factory,
        asset["parse_job_id"],
    )
    reopened = client.get(f"/api/v1/projects/{project_id}/spatial/assets/{asset['id']}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["parse_status"] == "succeeded"
    summary = reopened.json()["parse_summary"]
    assert summary["schema_version"] == "spatial-source-parse-0001"
    assert summary["source_kind_resolved"] == "mesh"
    assert summary["vertex_count"] == 3
    assert summary["face_count"] == 1
    assert summary["point_count"] is None
    assert summary["calibration_applied"] is False
    assert summary["calibration_verified"] is False
    assert summary["specimen_identity_verified"] is False
    assert {
        "physical_calibration_not_applied",
        "structural_parse_unreviewed",
        "open_mesh_surface_not_enclosed",
    }.issubset(summary["qc_warnings"])
    assert len(summary["geometry_sha256"]) == 64
    assert not any(key.endswith("_m") or key.endswith("_m2") for key in summary)

    with app.state.session_factory() as session:
        job = session.get(Job, asset["parse_job_id"])
        assert job is not None and job.result_json is not None
        job.result_json = {**job.result_json, "geometry_sha256": "0" * 64}
        session.commit()
    rejected = client.get(f"/api/v1/projects/{project_id}/spatial/assets/{asset['id']}")
    assert rejected.status_code == 400, rejected.text
    assert "integrity" in rejected.json()["detail"].lower()


def test_malformed_source_is_preserved_but_background_parse_fails_closed(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Malformed spatial parse")["id"])
    malformed = b"v 0 0 0\nf 1 2 3\n"
    asset = _import(client, project_id, "malformed.obj", malformed)
    app = cast(FastAPI, client.app)
    assert process_spatial_source_parse_job(
        app.state.settings,
        app.state.session_factory,
        asset["parse_job_id"],
    )

    reopened = client.get(f"/api/v1/projects/{project_id}/spatial/assets/{asset['id']}").json()
    assert reopened["parse_status"] == "failed"
    assert reopened["parse_summary"] is None
    assert (
        client.get(f"/api/v1/projects/{project_id}/spatial/assets/{asset['id']}/content").content
        == malformed
    )
    with app.state.session_factory() as session:
        job = session.get(Job, asset["parse_job_id"])
        assert job is not None
        assert job.status == "failed"
        assert "parse" in str(job.error_message).lower()
        assert job.result_json is None


def test_parse_job_rejects_changed_original_and_worker_dispatches_point_cloud(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Spatial parse dispatch")["id"])
    point_asset = _import(client, project_id, "cloud.ply", POINT_PLY)
    app = cast(FastAPI, client.app)
    assert process_next_thumbnail_job(app.state.settings, app.state.session_factory)
    point_reopened = client.get(
        f"/api/v1/projects/{project_id}/spatial/assets/{point_asset['id']}"
    ).json()
    assert point_reopened["parse_status"] == "succeeded"
    assert point_reopened["parse_summary"]["source_kind_resolved"] == "point_cloud"
    assert point_reopened["parse_summary"]["point_count"] == 2

    mesh_asset = _import(client, project_id, "tampered.obj", OBJ)
    with app.state.session_factory() as session:
        job = session.get(Job, mesh_asset["parse_job_id"])
        assert job is not None
        managed_path = Path(str(job.request_json["managed_path"]))
    (app.state.settings.resolved_data_dir / managed_path).write_bytes(b"x" * len(OBJ))
    assert process_spatial_source_parse_job(
        app.state.settings,
        app.state.session_factory,
        mesh_asset["parse_job_id"],
    )
    with app.state.session_factory() as session:
        job = session.get(Job, mesh_asset["parse_job_id"])
        assert job is not None
        assert job.status == "failed"
        assert "sha-256" in str(job.error_message).lower()


def test_duplicate_import_reuses_asset_and_parse_job(client: TestClient) -> None:
    project_id = str(create_project(client, "Spatial parse dedupe")["id"])
    first = _import(client, project_id, "coral.obj", OBJ)
    second = _import(client, project_id, "coral.obj", OBJ)
    assert second["id"] == first["id"]
    assert second["parse_job_id"] == first["parse_job_id"]
