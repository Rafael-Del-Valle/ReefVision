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
from reefvision.jobs.spatial_source_parse_v14 import process_spatial_source_parse_job
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


def _tamper_metadata_frame_with_consistent_section_checksum(
    archive_bytes: bytes,
) -> bytes:
    source = io.BytesIO(archive_bytes)
    target = io.BytesIO()
    with zipfile.ZipFile(source, "r") as incoming:
        members = {info.filename: incoming.read(info) for info in incoming.infolist()}
    manifest_name = "reefvision-exchange-manifest.json"
    manifest = json.loads(members[manifest_name])
    section = manifest["sections"]["spatial_asset_metadata_revisions"]
    rows = [json.loads(line) for line in members[section["path"]].splitlines()]
    rows[0]["coordinate_frame_id"] = "altered-frame"
    records = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    ).encode()
    members[section["path"]] = records
    section["sha256"] = sha256(records).hexdigest()
    members[manifest_name] = json.dumps(manifest, indent=2, sort_keys=True).encode()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as outgoing:
        for name, payload in members.items():
            outgoing.writestr(name, payload)
    return target.getvalue()


def _tamper_parse_with_consistent_section_checksum(
    archive_bytes: bytes,
    *,
    request_overrides: dict[str, object] | None = None,
    result_overrides: dict[str, object] | None = None,
) -> bytes:
    source = io.BytesIO(archive_bytes)
    target = io.BytesIO()
    with zipfile.ZipFile(source, "r") as incoming:
        members = {info.filename: incoming.read(info) for info in incoming.infolist()}
    manifest_name = "reefvision-exchange-manifest.json"
    manifest = json.loads(members[manifest_name])
    section = manifest["sections"]["jobs"]
    rows = [json.loads(line) for line in members[section["path"]].splitlines()]
    parse_job = next(row for row in rows if row["job_type"] == "spatial_source_parse")
    if request_overrides is not None:
        parse_job["request_json"].update(request_overrides)
    elif result_overrides is not None:
        parse_job["result_json"].update(result_overrides)
    else:
        parse_job["result_json"]["geometry_sha256"] = "0" * 64
    records = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    ).encode()
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
    app = cast(FastAPI, client.app)
    assert process_spatial_source_parse_job(
        test_settings,
        app.state.session_factory,
        asset["parse_job_id"],
    )

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
    metadata = client.post(
        f"{base}/spatial/assets/{asset['id']}/metadata-revisions",
        json={
            "coordinate_unit": "millimeter",
            "meters_per_unit": 0.001,
            "coordinate_frame_id": "survey-local-A",
            "transform_to_project_frame": [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            "calibration_evidence": "Unverified ruler reconstruction scale",
            "review_state": "attributed_unverified",
            "reviewed_by_identity": "reviewer-2",
            "review_note": "Frame and scale evidence inspected",
            "created_by_identity": "local_user",
        },
    )
    assert metadata.status_code == 201, metadata.text
    metadata_second = client.post(
        f"{base}/spatial/assets/{asset['id']}/metadata-revisions",
        json={
            "coordinate_unit": "millimeter",
            "meters_per_unit": 0.001,
            "coordinate_frame_id": "survey-local-A",
            "transform_to_project_frame": [
                [1.0, 0.0, 0.0, 0.02],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            "calibration_evidence": "Unverified ruler reconstruction scale",
            "review_state": "attributed_unverified",
            "reviewed_by_identity": "reviewer-2",
            "review_note": "Transform translation corrected after local inspection",
            "created_by_identity": "local_user",
        },
    )
    assert metadata_second.status_code == 201, metadata_second.text

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
    assert process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        str(created.json()["job_id"]),
    )
    package = client.get(f"/api/v1/exchange-packages/{created.json()['package']['id']}").json()
    assert package["manifest_json"]["sections"]["spatial_source_assets"]["count"] == 1
    assert package["manifest_json"]["sections"]["spatial_calibration_reviews"]["count"] == 1
    assert package["manifest_json"]["sections"]["spatial_asset_metadata_revisions"]["count"] == 2
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
    assert restored_asset["parse_status"] == "succeeded"
    assert restored_asset["parse_summary"]["source_kind_resolved"] == "mesh"
    assert restored_asset["parse_summary"]["geometry_sha256"]
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
    restored_metadata = client.get(
        f"/api/v1/projects/{restored_project_id}/spatial/assets/"
        f"{restored_asset['id']}/metadata-revisions"
    )
    assert restored_metadata.status_code == 200, restored_metadata.text
    assert len(restored_metadata.json()) == 2
    restored_first, restored_second = restored_metadata.json()
    assert restored_first["id"] != metadata.json()["id"]
    assert restored_first["spatial_source_asset_id"] == restored_asset["id"]
    assert restored_first["coordinate_frame_id"] == "survey-local-A"
    assert restored_first["content_sha256"] != metadata.json()["content_sha256"]
    assert restored_second["id"] != metadata_second.json()["id"]
    assert restored_second["previous_revision_id"] == restored_first["id"]
    assert restored_second["content_sha256"] != metadata_second.json()["content_sha256"]
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

    altered_metadata = _tamper_metadata_frame_with_consistent_section_checksum(archive_bytes)
    metadata_inspection = client.post(
        "/api/v1/exchange-packages/inspect",
        files={
            "file": (
                "altered-metadata.reefvision.zip",
                altered_metadata,
                "application/zip",
            )
        },
    )
    assert metadata_inspection.status_code == 200, metadata_inspection.text
    assert metadata_inspection.json()["compatible"] is False
    assert any(
        "metadata evidence failed integrity" in error.lower()
        for error in metadata_inspection.json()["errors"]
    ), metadata_inspection.json()["errors"]
    rejected_metadata_import = client.post(
        "/api/v1/exchange-packages/import",
        files={
            "file": (
                "altered-metadata.reefvision.zip",
                altered_metadata,
                "application/zip",
            )
        },
    )
    assert rejected_metadata_import.status_code == 400, rejected_metadata_import.text

    altered_parse = _tamper_parse_with_consistent_section_checksum(archive_bytes)
    parse_inspection = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("altered-parse.reefvision.zip", altered_parse, "application/zip")},
    )
    assert parse_inspection.status_code == 200, parse_inspection.text
    assert parse_inspection.json()["compatible"] is False
    assert any(
        "parse result failed integrity" in error.lower()
        for error in parse_inspection.json()["errors"]
    )
    rejected_parse_import = client.post(
        "/api/v1/exchange-packages/import",
        files={"file": ("altered-parse.reefvision.zip", altered_parse, "application/zip")},
    )
    assert rejected_parse_import.status_code == 400, rejected_parse_import.text

    for overrides in (
        {"size_bytes": float(len(OBJ))},
        {"size_bytes": True},
        {"size_bytes": len(OBJ) + 1},
        {"managed_path": "unrelated.obj"},
    ):
        altered_request = _tamper_parse_with_consistent_section_checksum(
            archive_bytes, request_overrides=overrides
        )
        files = {"file": ("altered-request.reefvision.zip", altered_request, "application/zip")}
        request_inspection = client.post("/api/v1/exchange-packages/inspect", files=files)
        assert request_inspection.status_code == 200, request_inspection.text
        assert request_inspection.json()["compatible"] is False
        assert any(
            "parse job binding is invalid" in error.lower()
            for error in request_inspection.json()["errors"]
        ), request_inspection.json()["errors"]
        rejected_request = client.post("/api/v1/exchange-packages/import", files=files)
        assert rejected_request.status_code == 400, rejected_request.text

    for result_overrides in (
        {"vertex_count": 3.0},
        {"face_count": True},
        {"calibration_verified": 0},
    ):
        altered_result = _tamper_parse_with_consistent_section_checksum(
            archive_bytes, result_overrides=result_overrides
        )
        files = {"file": ("altered-result.reefvision.zip", altered_result, "application/zip")}
        result_inspection = client.post("/api/v1/exchange-packages/inspect", files=files)
        assert result_inspection.status_code == 200, result_inspection.text
        assert result_inspection.json()["compatible"] is False
        assert any(
            "parse result is invalid" in error.lower()
            for error in result_inspection.json()["errors"]
        ), result_inspection.json()["errors"]
        rejected_result = client.post("/api/v1/exchange-packages/import", files=files)
        assert rejected_result.status_code == 400, rejected_result.text

    original = client.get(f"{base}/spatial/assets/{asset['id']}/content")
    assert original.status_code == 200, original.text
    assert original.content == OBJ


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
