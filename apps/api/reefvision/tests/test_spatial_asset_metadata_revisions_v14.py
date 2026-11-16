"""Immutable revisions bind units, frames, transforms, calibration and review state."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import SpatialAssetMetadataRevision
from reefvision.schemas.spatial_asset_metadata_revision_v14 import (
    SpatialAssetMetadataRevisionCreate,
)
from reefvision.services.spatial_asset_metadata_revisions_v14 import (
    spatial_asset_metadata_content,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project

OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


def _import_asset(client: TestClient, project_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/assets",
        files={"file": ("coral.obj", OBJ, "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_spatial_metadata_revisions_are_append_only_and_integrity_checked(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Spatial metadata revisions")["id"])
    asset = _import_asset(client, project_id)
    base = f"/api/v1/projects/{project_id}/spatial/assets/{asset['id']}"
    original_before = client.get(f"{base}/content").content

    first = client.post(
        f"{base}/metadata-revisions",
        json={
            "coordinate_unit": "millimeter",
            "meters_per_unit": 0.001,
            "coordinate_frame_id": "photogrammetry-local-A",
            "transform_to_project_frame": [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            "calibration_evidence": "Unverified ruler reconstruction scale",
            "review_state": "unreviewed",
            "reviewed_by_identity": None,
            "review_note": None,
            "created_by_identity": "local_user",
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["revision"] == 1
    assert first.json()["source_sha256"] == asset["sha256"]
    assert first.json()["reviewer_authenticated"] is False
    assert first.json()["calibration_verified"] is False

    second = client.post(
        f"{base}/metadata-revisions",
        json={
            "coordinate_unit": "millimeter",
            "meters_per_unit": 0.001,
            "coordinate_frame_id": "photogrammetry-local-A",
            "transform_to_project_frame": [
                [1.0, 0.0, 0.0, 0.01],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            "calibration_evidence": "Unverified ruler reconstruction scale",
            "review_state": "attributed_unverified",
            "reviewed_by_identity": "reviewer-2",
            "review_note": "Transform checked against local control points",
            "created_by_identity": "local_user",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["revision"] == 2
    assert second.json()["previous_revision_id"] == first.json()["id"]
    assert second.json()["content_sha256"] != first.json()["content_sha256"]

    listed = client.get(f"{base}/metadata-revisions?limit=10&offset=0")
    assert listed.status_code == 200, listed.text
    assert [item["revision"] for item in listed.json()] == [1, 2]
    reopened_first = client.get(f"{base}/metadata-revisions/{first.json()['id']}")
    assert reopened_first.status_code == 200, reopened_first.text
    assert reopened_first.json() == first.json()
    assert client.get(f"{base}/content").content == original_before == OBJ

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        row = session.get(SpatialAssetMetadataRevision, first.json()["id"])
        assert row is not None
        row.content_sha256 = "0" * 64
        session.commit()
    rejected = client.get(f"{base}/metadata-revisions/{first.json()['id']}")
    assert rejected.status_code == 400, rejected.text
    assert "integrity" in rejected.json()["detail"].lower()


def test_spatial_metadata_revision_rejects_invalid_or_unbound_evidence(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Spatial metadata validation")["id"])
    other_id = str(create_project(client, "Other spatial project")["id"])
    asset = _import_asset(client, project_id)
    base = f"/api/v1/projects/{project_id}/spatial/assets/{asset['id']}"
    invalid_review = client.post(
        f"{base}/metadata-revisions",
        json={
            "coordinate_unit": "unknown",
            "meters_per_unit": None,
            "coordinate_frame_id": None,
            "transform_to_project_frame": None,
            "calibration_evidence": None,
            "review_state": "attributed_unverified",
            "reviewed_by_identity": None,
            "review_note": None,
            "created_by_identity": "local_user",
        },
    )
    assert invalid_review.status_code == 422, invalid_review.text

    invalid_transform = client.post(
        f"{base}/metadata-revisions",
        json={
            "coordinate_unit": "meter",
            "meters_per_unit": 1.0,
            "coordinate_frame_id": "frame-A",
            "transform_to_project_frame": [[1.0, 0.0], [0.0, 1.0]],
            "calibration_evidence": "Instrument scale pending independent review",
            "review_state": "unreviewed",
            "created_by_identity": "local_user",
        },
    )
    assert invalid_transform.status_code == 422, invalid_transform.text

    wrong_project = client.post(
        f"/api/v1/projects/{other_id}/spatial/assets/{asset['id']}/metadata-revisions",
        json={
            "coordinate_unit": "meter",
            "meters_per_unit": 1.0,
            "coordinate_frame_id": "frame-A",
            "transform_to_project_frame": None,
            "calibration_evidence": "Instrument scale pending independent review",
            "review_state": "unreviewed",
            "created_by_identity": "local_user",
        },
    )
    assert wrong_project.status_code == 404, wrong_project.text


def test_spatial_metadata_revisions_reject_rehashed_broken_ancestry(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Spatial ancestry integrity")["id"])
    asset = _import_asset(client, project_id)
    asset_id = str(asset["id"])
    base = f"/api/v1/projects/{project_id}/spatial/assets/{asset_id}"
    payload = {"coordinate_unit": "unknown", "created_by_identity": "local_user"}

    first = client.post(f"{base}/metadata-revisions", json=payload)
    second = client.post(f"{base}/metadata-revisions", json=payload)
    assert first.status_code == second.status_code == 201
    assert second.json()["previous_revision_id"] == first.json()["id"]

    other_project = str(create_project(client, "Unrelated spatial ancestry")["id"])
    other_asset = _import_asset(client, other_project)
    foreign_base = (
        f"/api/v1/projects/{other_project}/spatial/assets/{other_asset['id']}"
    )
    foreign = client.post(f"{foreign_base}/metadata-revisions", json=payload)
    assert foreign.status_code == 201

    app = cast(FastAPI, client.app)
    for forged_predecessor in (None, foreign.json()["id"]):
        with app.state.session_factory() as session:
            row = session.get(SpatialAssetMetadataRevision, second.json()["id"])
            assert row is not None
            row.previous_revision_id = forged_predecessor
            row.content_sha256 = canonical_json_sha256(
                spatial_asset_metadata_content(
                    project_id=project_id,
                    asset_id=asset_id,
                    source_sha256=str(asset["sha256"]),
                    revision=2,
                    previous_revision_id=forged_predecessor,
                    payload=SpatialAssetMetadataRevisionCreate.model_validate(payload),
                )
            )
            session.commit()
        response = client.get(f"{base}/metadata-revisions/{second.json()['id']}")
        assert response.status_code == 400, response.text
        assert "ancestry" in response.json()["detail"].lower()
        listed = client.get(f"{base}/metadata-revisions")
        assert listed.status_code == 400, listed.text

    unchanged = client.get(f"{base}/metadata-revisions/{first.json()['id']}")
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json() == first.json()
