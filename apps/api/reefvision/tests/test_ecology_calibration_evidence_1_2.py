"""Frozen calibration evidence is source-bound, unverified, and workflow-safe."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import EcologyIdentityCalibrationEvidence, ImageAsset
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_ecology_annotation_evidence_1_2 import _annotation_link, _box
from reefvision.tests.test_ecology_image_evidence_1_2 import _link, _register, _workflow


def _prepared_annotation(client: TestClient) -> tuple[str, str, dict[str, object]]:
    project = create_project(client, "Frozen ecological calibration")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201, image_link.text
    box_id = _box(client, image_id, str(project["label_classes"][0]["id"]))
    annotation_link = _annotation_link(
        client, project_id, image_link.json()["id"], "box", box_id
    )
    assert annotation_link.status_code == 201, annotation_link.text
    return project_id, image_id, annotation_link.json()


def _save_calibration(client: TestClient, image_id: str, scale: float = 0.25) -> None:
    response = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={
            "distance_per_pixel": scale,
            "unit": "mm",
            "source": "manual",
            "reference_length": 5.0,
            "reference_pixel_length": 20.0,
            "reference_plane_only": True,
        },
    )
    assert response.status_code == 200, response.text


def _link_calibration(
    client: TestClient, project_id: str, annotation: dict[str, object], *,
    organism_key: str = "colony-a", confirmed: bool = True,
):
    return client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/{organism_key}/calibration-evidence",
        json={
            "annotation_evidence_id": annotation["id"],
            "expected_annotation_sha256": annotation["annotation_sha256"],
            "confirm_source_calibration": confirmed,
            "reason": "Scientist confirmed the saved source-image scale",
        },
    )


def test_calibration_snapshot_persists_unverified_with_saved_workflow(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    missing = _link_calibration(client, project_id, annotation)
    assert missing.status_code == 400, missing.text
    assert "requires saved image calibration" in missing.json()["detail"]
    _save_calibration(client, image_id)
    unconfirmed = _link_calibration(client, project_id, annotation, confirmed=False)
    assert unconfirmed.status_code == 422
    linked = _link_calibration(client, project_id, annotation)
    assert linked.status_code == 201, linked.text
    row = linked.json()
    assert row["calibration_json"]["distance_per_pixel"] == 0.25
    assert row["calibration_json"]["unit"] == "mm"
    assert row["evidence_level"] == "linked_unverified"
    assert len(row["calibration_sha256"]) == 64
    duplicate = _link_calibration(client, project_id, annotation)
    assert duplicate.status_code == 409

    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    snapshot = registry.json()
    assert snapshot["calibration_evidence_count"] == 1
    assert snapshot["calibration_evidence_links"] == [row]
    assert snapshot["review_gate"] == "scientist_review_required"
    assert snapshot["evidence_level"] == "registered_unverified"
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == snapshot


def test_source_calibration_change_revokes_api_and_workflow(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    _save_calibration(client, image_id, scale=0.5)
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "source or frozen snapshot changed" in registry.json()["detail"]
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert "source or frozen snapshot changed" in workflow["run"]["error_message"]
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"]
    )


def test_calibration_snapshot_tampering_fails_closed(client: TestClient) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    linked = _link_calibration(client, project_id, annotation)
    assert linked.status_code == 201, linked.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        record = session.get(EcologyIdentityCalibrationEvidence, linked.json()["id"])
        assert record is not None
        record.calibration_json = {"distance_per_pixel": 100, "unit": "mm"}
        session.commit()
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"]
    )


def test_calibration_rejects_foreign_organism_and_nonfinite_source(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    _register(client, project_id, "colony-b")
    foreign = _link_calibration(client, project_id, annotation, organism_key="colony-b")
    assert foreign.status_code == 400, foreign.text
    assert "must belong to the organism" in foreign.json()["detail"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        metadata = dict(image.metadata_json or {})
        metadata["measurement_calibration"] = {
            "distance_per_pixel": float("inf"),
            "unit": "mm",
            "source": "manual",
        }
        image.metadata_json = metadata
        session.commit()
    invalid = _link_calibration(client, project_id, annotation)
    assert invalid.status_code == 400, invalid.text
    assert "nonfinite" in invalid.json()["detail"]
