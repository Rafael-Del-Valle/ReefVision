"""Project Exchange preserves immutable spatial originals and review receipts."""

from __future__ import annotations

import io
import json
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.tests.test_annotations import create_project

OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


def _replace_member(archive_bytes: bytes, member: str, payload: bytes) -> bytes:
    source = io.BytesIO(archive_bytes)
    target = io.BytesIO()
    with (
        zipfile.ZipFile(source, "r") as incoming,
        zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as outgoing,
    ):
        for info in incoming.infolist():
            outgoing.writestr(info, payload if info.filename == member else incoming.read(info))
    return target.getvalue()


def _tamper_review_note_with_consistent_section_checksum(archive_bytes: bytes) -> bytes:
    source = io.BytesIO(archive_bytes)
    target = io.BytesIO()
    with zipfile.ZipFile(source, "r") as incoming:
        members = {info.filename: incoming.read(info) for info in incoming.infolist()}
    manifest_name = "reefvision-exchange-manifest.json"
    manifest = json.loads(members[manifest_name])
    section = manifest["sections"]["spatial_calibration_reviews"]
    row = json.loads(members[section["path"]])
    row["evidence_json"]["independent_review_note"] = "Altered after review"
    records = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
    members[section["path"]] = records
    section["sha256"] = sha256(records).hexdigest()
    members[manifest_name] = json.dumps(manifest, indent=2, sort_keys=True).encode()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as outgoing:
        for name, payload in members.items():
            outgoing.writestr(name, payload)
    return target.getvalue()


def test_spatial_original_and_review_round_trip_and_reject_tampering(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project_id = str(create_project(client, "Spatial exchange source")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(
        f"{base}/spatial/assets",
        files={"file": ("coral.obj", OBJ, "text/plain")},
    )
    assert imported.status_code == 201, imported.text
    asset = imported.json()

    preview = client.post(
        f"{base}/spatial/mesh-preview",
        json={
            "asset_id": asset["id"],
            "expected_source_payload_sha256": asset["sha256"],
            "meters_per_unit": 0.01,
            "calibration_method": "ruler",
            "calibration_evidence": "Unverified ruler visible in source photographs",
            "relative_scale_uncertainty": 0.05,
            "specimen_id": "colony-16",
            "observation_id": "survey-1",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "coordinate_frame_id": "survey-local-A",
        },
    )
    assert preview.status_code == 200, preview.text
    review = client.post(
        f"{base}/spatial/assets/{asset['id']}/calibration-reviews",
        json={
            "evidence": {
                "calibration_operator_id": "operator-1",
                "independent_reviewer_id": "reviewer-2",
                "independent_review_decision": "inconclusive",
                "independent_review_note": "Field ruler provenance still needs verification",
                "reviewed_at_utc": "2026-10-02T12:00:00Z",
                "reviewed_geometry_sha256": preview.json()["provenance"]["geometry_sha256"],
                "reviewed_source_payload_sha256": asset["sha256"],
                "reviewed_spatial_source_asset_id": asset["id"],
                "reviewed_coordinate_frame_id": "survey-local-A",
                "reviewed_specimen_id": "colony-16",
                "reviewed_observation_id": "survey-1",
                "reviewed_observed_at_utc": "2026-10-01T12:00:00Z",
                "reviewed_meters_per_unit": 0.01,
                "reviewed_calibration_method": "ruler",
                "reviewed_calibration_evidence": ("Unverified ruler visible in source photographs"),
                "reviewed_relative_scale_uncertainty": 0.05,
            }
        },
    )
    assert review.status_code == 201, review.text

    created = client.post(
        f"{base}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": False,
            "include_generated_artifacts": False,
            "notes": "Spatial source round-trip acceptance",
        },
    )
    assert created.status_code == 202, created.text
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        str(created.json()["job_id"]),
    )
    package = client.get(f"/api/v1/exchange-packages/{created.json()['package']['id']}").json()
    assert package["manifest_json"]["sections"]["spatial_source_assets"]["count"] == 1
    assert package["manifest_json"]["sections"]["spatial_calibration_reviews"]["count"] == 1
    descriptor = next(
        item for item in package["manifest_json"]["media"] if item["kind"] == "spatial_source"
    )
    assert descriptor["record_id"] == asset["id"]
    archive_bytes = (test_settings.resolved_data_dir / Path(package["archive_path"])).read_bytes()

    inspection = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("spatial.reefvision.zip", archive_bytes, "application/zip")},
    )
    assert inspection.status_code == 200, inspection.text
    assert inspection.json()["compatible"] is True

    restored = client.post(
        "/api/v1/exchange-packages/import",
        files={"file": ("spatial.reefvision.zip", archive_bytes, "application/zip")},
        data={"project_name": "Spatial exchange restored"},
    )
    assert restored.status_code == 201, restored.text
    restored_project_id = str(restored.json()["project_id"])
    restored_assets = client.get(f"/api/v1/projects/{restored_project_id}/spatial/assets")
    assert restored_assets.status_code == 200, restored_assets.text
    restored_asset = restored_assets.json()[0]
    assert restored_asset["id"] != asset["id"]
    assert restored_asset["sha256"] == asset["sha256"]
    restored_content = client.get(
        f"/api/v1/projects/{restored_project_id}/spatial/assets/{restored_asset['id']}/content"
    )
    assert restored_content.status_code == 200, restored_content.text
    assert restored_content.content == OBJ
    restored_reviews = client.get(
        f"/api/v1/projects/{restored_project_id}/spatial/assets/"
        f"{restored_asset['id']}/calibration-reviews"
    )
    assert restored_reviews.status_code == 200, restored_reviews.text
    restored_review = restored_reviews.json()[0]
    assert restored_review["id"] != review.json()["id"]
    assert restored_review["spatial_source_asset_id"] == restored_asset["id"]
    assert restored_review["evidence"]["reviewed_spatial_source_asset_id"] == restored_asset["id"]
    replay = client.post(
        f"/api/v1/projects/{restored_project_id}/spatial/mesh-preview",
        json={
            "asset_id": restored_asset["id"],
            "calibration_review_id": restored_review["id"],
            "expected_source_payload_sha256": restored_asset["sha256"],
            "meters_per_unit": 0.01,
            "calibration_method": "ruler",
            "calibration_evidence": "Unverified ruler visible in source photographs",
            "relative_scale_uncertainty": 0.05,
            "specimen_id": "colony-16",
            "observation_id": "survey-1",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "coordinate_frame_id": "survey-local-A",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["provenance"]["calibration_review_record_id"] == restored_review["id"]

    tampered = _replace_member(archive_bytes, descriptor["path"], b"tampered")
    rejected_inspection = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("tampered.reefvision.zip", tampered, "application/zip")},
    )
    assert rejected_inspection.status_code == 200, rejected_inspection.text
    assert rejected_inspection.json()["compatible"] is False
    assert any("checksum failed" in error for error in rejected_inspection.json()["errors"])
    rejected_import = client.post(
        "/api/v1/exchange-packages/import",
        files={"file": ("tampered.reefvision.zip", tampered, "application/zip")},
    )
    assert rejected_import.status_code == 400, rejected_import.text

    altered_review = _tamper_review_note_with_consistent_section_checksum(archive_bytes)
    review_inspection = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("altered-review.reefvision.zip", altered_review, "application/zip")},
    )
    assert review_inspection.status_code == 200, review_inspection.text
    assert review_inspection.json()["compatible"] is False
    assert any(
        "review evidence failed integrity" in error.lower()
        for error in review_inspection.json()["errors"]
    )
    rejected_review_import = client.post(
        "/api/v1/exchange-packages/import",
        files={"file": ("altered-review.reefvision.zip", altered_review, "application/zip")},
    )
    assert rejected_review_import.status_code == 400, rejected_review_import.text


def test_spatial_project_exchange_requires_original_media(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project_id = str(create_project(client, "Spatial exchange requires originals")["id"])
    imported = client.post(
        f"/api/v1/projects/{project_id}/spatial/assets",
        files={"file": ("coral.obj", OBJ, "text/plain")},
    )
    assert imported.status_code == 201, imported.text
    created = client.post(
        f"/api/v1/projects/{project_id}/exchange-packages",
        json={
            "include_media": False,
            "include_model_weights": False,
            "include_generated_artifacts": False,
            "notes": "Missing originals must fail closed",
        },
    )
    assert created.status_code == 202, created.text
    app = cast(FastAPI, client.app)
    assert not process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        str(created.json()["job_id"]),
    )
    package = client.get(f"/api/v1/exchange-packages/{created.json()['package']['id']}")
    assert package.status_code == 200, package.text
    assert package.json()["status"] == "failed"
    assert "must include original media" in package.json()["error_message"]
