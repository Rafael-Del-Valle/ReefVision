from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.tests.test_images import create_project, import_one


def test_project_exchange_export_and_inspection(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Exchange project")
    report = import_one(client, project["id"])
    assert report["successful"]

    created = client.post(
        f"/api/v1/projects/{project['id']}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": False,
            "include_generated_artifacts": False,
            "notes": "portable study package",
        },
    )
    assert created.status_code == 202, created.text
    payload = cast(dict[str, Any], created.json())

    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    assert process_project_exchange_export_job(
        test_settings,
        factory,
        payload["job_id"],
    )

    package_response = client.get(
        f"/api/v1/exchange-packages/{payload['package']['id']}"
    )
    assert package_response.status_code == 200, package_response.text
    package = package_response.json()
    assert package["status"] == "complete"
    assert len(package["manifest_sha256"]) == 64
    assert package["manifest_json"]["format_name"] == "reefvision-project-exchange"
    assert package["manifest_json"]["sections"]["images"]["count"] == 1
    assert package["manifest_json"]["media"][0]["kind"] == "image"

    archive_path = test_settings.resolved_data_dir / Path(package["archive_path"])
    assert archive_path.is_file()
    archive_bytes = archive_path.read_bytes()

    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("study.reefvision.zip", archive_bytes, "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    inspection = inspected.json()
    assert inspection["compatible"] is True
    assert inspection["format_version"] == "1.0"
    assert inspection["project_name"] == "Exchange project"
    assert inspection["section_counts"]["images"] == 1
    assert inspection["included_media_count"] == 1
    assert inspection["errors"] == []


def test_project_exchange_inspection_rejects_unsafe_paths(client: TestClient) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../escape.txt", b"unsafe")
        archive.writestr(
            "reefvision-exchange-manifest.json",
            b'{"format_name":"reefvision-project-exchange","format_version":"1.0"}',
        )
    stream.seek(0)

    response = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("unsafe.zip", stream.getvalue(), "application/zip")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["compatible"] is False
    assert any("unsafe paths" in message.lower() for message in payload["errors"])


def test_project_exchange_metadata_only_warns_about_relinking(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Metadata exchange")
    import_one(client, project["id"])
    created = client.post(
        f"/api/v1/projects/{project['id']}/exchange-packages",
        json={"include_media": False},
    )
    assert created.status_code == 202, created.text
    payload = created.json()
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        payload["job_id"],
    )
    package = client.get(
        f"/api/v1/exchange-packages/{payload['package']['id']}"
    ).json()
    archive_path = test_settings.resolved_data_dir / Path(package["archive_path"])

    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("metadata.zip", archive_path.read_bytes(), "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["compatible"] is True
    assert any(
        "relinking" in message.lower() for message in inspected.json()["warnings"]
    )
