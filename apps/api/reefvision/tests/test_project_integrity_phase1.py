from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset, Job, ModelRegistration
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one


def _attach_thumbnail(client: TestClient, image_id: str, project_id: str) -> str:
    app = cast(FastAPI, client.app)
    relative = f"projects/{project_id}/thumbnails/{image_id}.png"
    destination = resolve_managed_project_path(app.state.settings, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"thumbnail")
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.thumbnail_path = relative
        session.commit()
    return relative


def test_integrity_report_accepts_complete_managed_image(client: TestClient) -> None:
    project = create_project(client, "Integrity project")
    imported = import_one(client, str(project["id"]))
    image_id = str(imported["successful"][0]["image_id"])
    _attach_thumbnail(client, image_id, str(project["id"]))

    response = client.get(f"/api/v1/projects/{project['id']}/integrity")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is True
    assert payload["error_count"] == 0
    assert payload["existing_referenced_files"] == 2
    categories = {item["resource_kind"]: item for item in payload["categories"]}
    assert categories["image"]["existing_file_count"] == 1
    assert categories["thumbnail"]["existing_file_count"] == 1


def test_integrity_report_detects_missing_checksum_and_stale_job(
    client: TestClient,
) -> None:
    project = create_project(client, "Broken integrity project")
    imported = import_one(client, str(project["id"]))
    image_id = str(imported["successful"][0]["image_id"])
    _attach_thumbnail(client, image_id, str(project["id"]))
    app = cast(FastAPI, client.app)

    model_relative = f"projects/{project['id']}/models/corrupt.pt"
    model_path = resolve_managed_project_path(app.state.settings, model_relative)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"actual checkpoint bytes")
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image_path = resolve_managed_project_path(
            app.state.settings,
            image.managed_path,
        )
        image_path.unlink()
        session.add(
            ModelRegistration(
                project_id=str(project["id"]),
                purpose="detector",
                display_name="Corrupt detector",
                source_filename="corrupt.pt",
                managed_path=model_relative,
                sha256=sha256(b"different bytes").hexdigest(),
                file_size_bytes=model_path.stat().st_size,
                framework="ultralytics",
                task="detect",
                provider_name="ultralytics",
                provider_version="test",
                class_map_json={},
                metadata_json={},
            )
        )
        session.add(
            Job(
                project_id=str(project["id"]),
                job_type="training",
                status="running",
                started_at=datetime.now(UTC) - timedelta(hours=3),
                request_json={},
            )
        )
        session.commit()

    response = client.get(
        f"/api/v1/projects/{project['id']}/integrity",
        params={"verify_checksums": True, "stale_job_minutes": 60},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is False
    codes = {item["code"] for item in payload["issues"]}
    assert "managed_file_missing" in codes
    assert "checksum_mismatch" in codes
    assert "stale_active_job" in codes
    categories = {item["resource_kind"]: item for item in payload["categories"]}
    assert categories["model"]["checksum_verified_count"] == 1
    assert categories["model"]["checksum_mismatch_count"] == 1
