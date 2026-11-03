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
    annotation_link = _annotation_link(client, project_id, image_link.json()["id"], "box", box_id)
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
    client: TestClient,
    project_id: str,
    annotation: dict[str, object],
    *,
    organism_key: str = "colony-a",
    confirmed: bool = True,
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
    assert "scale conflicts with its reference length" in registry.json()["detail"]
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert "scale conflicts with its reference length" in workflow["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"])


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
    assert not any(row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"])


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


def test_pixel_unit_calibration_cannot_enter_scientific_registry_or_workflow(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        metadata = dict(image.metadata_json or {})
        calibration = dict(metadata["measurement_calibration"])
        calibration["unit"] = "pixels"
        metadata["measurement_calibration"] = calibration
        image.metadata_json = metadata
        session.commit()

    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "physical length unit" in registry.json()["detail"]
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert "physical length unit" in workflow["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"])


def test_nonfinite_camera_signature_rejected_before_link_and_after_link(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    app = cast(FastAPI, client.app)

    def set_focal_length(value: float) -> None:
        with app.state.session_factory() as session:
            image = session.get(ImageAsset, image_id)
            assert image is not None
            metadata = dict(image.metadata_json or {})
            calibration = dict(metadata["measurement_calibration"])
            calibration["camera_signature"] = {"focal_length_mm": value}
            metadata["measurement_calibration"] = calibration
            image.metadata_json = metadata
            session.commit()

    set_focal_length(float("inf"))
    invalid = _link_calibration(client, project_id, annotation)
    assert invalid.status_code == 400, invalid.text
    assert "nonfinite" in invalid.json()["detail"]

    set_focal_length(85.0)
    linked = _link_calibration(client, project_id, annotation)
    assert linked.status_code == 201, linked.text

    set_focal_length(float("inf"))
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "nonfinite" in registry.json()["detail"]
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert "nonfinite" in workflow["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"])


def test_non_length_calibration_units_fail_closed_before_and_after_link(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    app = cast(FastAPI, client.app)

    def set_unit(unit: str) -> None:
        with app.state.session_factory() as session:
            image = session.get(ImageAsset, image_id)
            assert image is not None
            metadata = dict(image.metadata_json or {})
            calibration = dict(metadata["measurement_calibration"])
            calibration["unit"] = unit
            metadata["measurement_calibration"] = calibration
            image.metadata_json = metadata
            session.commit()

    for invalid_unit in ("seconds", "degrees", "banana", "px/mm"):
        set_unit(invalid_unit)
        rejected = _link_calibration(client, project_id, annotation)
        assert rejected.status_code == 400, rejected.text
        assert "physical length unit" in rejected.json()["detail"]

    # Micro-symbol units remain valid physical lengths (casefold normalizes µ/μ).
    set_unit("µm")
    accepted = _link_calibration(client, project_id, annotation)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["calibration_json"]["unit"] == "µm"
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"

    # A subsequent dimensionality change invalidates persisted source evidence.
    set_unit("seconds")
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "physical length unit" in registry.json()["detail"]
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert "physical length unit" in workflow["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"])


def test_reference_scale_conflict_blocks_ecological_sources_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)

    # 5 mm over 20 pixels implies 0.25 mm/px, not 0.5 mm/px.
    # The generic calibration editor may store a provisional scale, but the
    # scientific evidence registry must reject contradictory reference data.
    _save_calibration(client, image_id, scale=0.5)
    rejected = _link_calibration(client, project_id, annotation)
    assert rejected.status_code == 400, rejected.text
    assert "scale conflicts with its reference length" in rejected.json()["detail"]

    # Small rounding in the user-entered physical scale remains acceptable.
    _save_calibration(client, image_id, scale=0.2501)
    linked = _link_calibration(client, project_id, annotation)
    assert linked.status_code == 201, linked.text
    path = f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    standalone = client.get(path)
    assert standalone.status_code == 200, standalone.text
    assert standalone.json()["candidate_count"] == 2
    assert standalone.json()["evidence_level"] == "linked_unverified"
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == standalone.json()

    # If the saved scale subsequently conflicts with its reference, neither
    # standalone nor saved workflows may emit a successful scientific result.
    _save_calibration(client, image_id, scale=0.5)
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "scale conflicts with its reference length" in registry.json()["detail"]
    assert client.get(path).status_code == 400
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert not any(
        row["data_type"] == "ecology_measurement_candidates" for row in workflow["artifacts"]
    )
