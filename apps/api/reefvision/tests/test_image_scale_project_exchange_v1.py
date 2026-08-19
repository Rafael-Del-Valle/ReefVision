from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.tests.test_images import create_project, import_one


def test_scale_calibration_round_trip_remaps_profile_source_and_preserves_homography(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Scale Assistant exchange")
    source_report = import_one(
        client,
        project["id"],
        filename="source-reference.png",
        relative_path="calibration/source-reference.png",
        size=(100, 80),
    )
    target_report = import_one(
        client,
        project["id"],
        filename="target-coral.png",
        relative_path="calibration/target-coral.png",
        size=(100, 80),
    )
    source_image_id = str(source_report["successful"][0]["image_id"])
    target_image_id = str(target_report["successful"][0]["image_id"])

    source_calibration = client.put(
        f"/api/v1/images/{source_image_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.05,
            "unit": "cm",
            "source": "charuco",
            "reference_length": 1.0,
            "reference_pixel_length": 20.0,
            "confidence": 0.97,
            "detector": "exchange-test-charuco",
            "profile_name": "Fixed coral camera rig",
            "camera_signature": {
                "camera_make": "Example",
                "camera_model": "Camera",
                "lens_model": "Macro",
                "capture_distance": 45.0,
                "setup_notes": "Fixed mount and reference plane",
            },
            "perspective_homography": [
                [0.05, 0.0, 0.0],
                [0.0, 0.05, 0.0],
                [0.0, 0.0, 1.0],
            ],
            "reference_plane_only": True,
        },
    )
    assert source_calibration.status_code == 200, source_calibration.text

    applied = client.post(
        f"/api/v1/images/{target_image_id}/measurement-calibration/apply-profile",
        json={
            "source_image_id": source_image_id,
            "confirm_same_setup": True,
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["profile_source_image_id"] == source_image_id
    assert applied.json()["perspective_homography"] is None

    created = client.post(
        f"/api/v1/projects/{project['id']}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": False,
            "include_generated_artifacts": False,
            "notes": "Scale Assistant calibration round trip",
        },
    )
    assert created.status_code == 202, created.text
    export_payload = created.json()
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        export_payload["job_id"],
    )

    package_response = client.get(
        f"/api/v1/exchange-packages/{export_payload['package']['id']}"
    )
    assert package_response.status_code == 200, package_response.text
    package = package_response.json()
    archive_path = test_settings.resolved_data_dir / Path(package["archive_path"])
    archive_bytes = archive_path.read_bytes()

    imported = client.post(
        "/api/v1/exchange-packages/import",
        files={
            "file": (
                "scale-calibration-round-trip.reefvision.zip",
                archive_bytes,
                "application/zip",
            )
        },
        data={"project_name": "Scale Assistant exchange imported"},
    )
    assert imported.status_code == 201, imported.text
    imported_project_id = str(imported.json()["project_id"])
    assert imported_project_id != project["id"]

    images_response = client.get(f"/api/v1/projects/{imported_project_id}/images")
    assert images_response.status_code == 200, images_response.text
    imported_images = {
        str(item["original_filename"]): str(item["id"])
        for item in images_response.json()["items"]
    }
    imported_source_id = imported_images["source-reference.png"]
    imported_target_id = imported_images["target-coral.png"]
    assert imported_source_id != source_image_id
    assert imported_target_id != target_image_id

    imported_source = client.get(
        f"/api/v1/images/{imported_source_id}/measurement-calibration"
    )
    assert imported_source.status_code == 200, imported_source.text
    imported_source_payload = imported_source.json()
    assert imported_source_payload["source"] == "charuco"
    assert imported_source_payload["profile_name"] == "Fixed coral camera rig"
    assert imported_source_payload["confidence"] == pytest.approx(0.97)
    assert imported_source_payload["perspective_homography"] == [
        [0.05, 0.0, 0.0],
        [0.0, 0.05, 0.0],
        [0.0, 0.0, 1.0],
    ]
    assert imported_source_payload["camera_signature"]["width_px"] == 100
    assert imported_source_payload["camera_signature"]["height_px"] == 80

    imported_target = client.get(
        f"/api/v1/images/{imported_target_id}/measurement-calibration"
    )
    assert imported_target.status_code == 200, imported_target.text
    imported_target_payload = imported_target.json()
    assert imported_target_payload["source"] == "camera_profile"
    assert imported_target_payload["profile_source_image_id"] == imported_source_id
    assert imported_target_payload["profile_source_image_id"] != source_image_id
    assert imported_target_payload["perspective_homography"] is None

    # Imported project metadata must remain independent after the source project changes.
    cleared_source = client.delete(
        f"/api/v1/images/{source_image_id}/measurement-calibration"
    )
    assert cleared_source.status_code == 204, cleared_source.text
    still_imported = client.get(
        f"/api/v1/images/{imported_source_id}/measurement-calibration"
    )
    assert still_imported.status_code == 200, still_imported.text
    assert still_imported.json()["profile_name"] == "Fixed coral camera rig"
