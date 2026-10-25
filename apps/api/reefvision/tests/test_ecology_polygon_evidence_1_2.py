"""Scientific polygon topology must be checked on both API and saved workflows."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import MaskAnnotation
from reefvision.domain.ecology_polygon_qc import validate_ecological_polygon_topology
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_ecology_annotation_evidence_1_2 import _annotation_link, _mask
from reefvision.tests.test_ecology_image_evidence_1_2 import _link, _register, _workflow


@pytest.mark.parametrize(
    "points",
    [
        [[5, 5], [25, 20], [5, 20], [25, 5]],  # Bow tie.
        [[5, 5], [25, 5], [15, 5], [25, 20], [5, 20]],  # Backtrack.
        [[5, 5], [25, 5], [25, 20], [5, 20], [25, 5]],  # Repeated vertex.
        [[5, 5], [15, 5], [25, 5]],  # Zero area.
    ],
)
def test_invalid_polygon_topology_rejected_before_annotation_link(
    client: TestClient, points: list[list[int]]
) -> None:
    project = create_project(client, "Ecological polygon topology pre-link")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201, image_link.text
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        mask.polygon_json = points
        session.commit()
    rejected = _annotation_link(client, project_id, image_link.json()["id"], "mask", mask_id)
    assert rejected.status_code == 400, rejected.text
    assert "Ecological mask polygon" in rejected.json()["detail"]
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["annotation_evidence_count"] == 0


def test_polygon_topology_change_invalidates_registry_and_saved_workflow(
    client: TestClient,
) -> None:
    project = create_project(client, "Ecological polygon topology revocation")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201, image_link.text
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    linked = _annotation_link(client, project_id, image_link.json()["id"], "mask", mask_id)
    assert linked.status_code == 201, linked.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        mask.polygon_json = [[5, 5], [25, 20], [5, 20], [25, 5]]
        session.commit()
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "Ecological mask polygon" in registry.json()["detail"]
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert "Ecological mask polygon" in workflow["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"])


@pytest.mark.parametrize(
    "points",
    [
        [[5, 5], [25, 5], [25, 20], [5, 20], [5, 5]],  # Closed ring.
        [[5, 5], [25, 5], [25, 20], [15, 12], [5, 20]],  # Concave ring.
    ],
)
def test_valid_polygon_topology_keeps_workflow_parity(
    client: TestClient, points: list[list[int]]
) -> None:
    project = create_project(client, "Ecological polygon topology valid")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201, image_link.text
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        mask.polygon_json = points
        session.commit()
    linked = _annotation_link(client, project_id, image_link.json()["id"], "mask", mask_id)
    assert linked.status_code == 201, linked.text
    standalone = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert standalone.status_code == 200, standalone.text
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == standalone.json()


def test_polygon_topology_helper_does_not_promote_review_status() -> None:
    validate_ecological_polygon_topology([[0, 0], [5, 0], [5, 5], [0, 5]])


def test_polygon_bbox_inconsistency_rejected_before_link(client: TestClient) -> None:
    project = create_project(client, "Ecological mask bbox mismatch")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201, image_link.text
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        # A valid polygon inside the photograph but outside its saved bbox.
        mask.polygon_json = [[5, 5], [35, 5], [35, 20], [5, 20]]
        session.commit()
    rejected = _annotation_link(client, project_id, image_link.json()["id"], "mask", mask_id)
    assert rejected.status_code == 400, rejected.text
    assert "outside its source-pixel bounds" in rejected.json()["detail"]


def test_polygon_bbox_change_revokes_registry_and_saved_workflow(
    client: TestClient,
) -> None:
    project = create_project(client, "Ecological mask bbox revocation")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201, image_link.text
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    linked = _annotation_link(client, project_id, image_link.json()["id"], "mask", mask_id)
    assert linked.status_code == 201, linked.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        mask.x_max = 10
        session.commit()
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "outside its source-pixel bounds" in registry.json()["detail"]
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert "outside its source-pixel bounds" in workflow["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"])


def test_polygon_bbox_one_pixel_rounding_keeps_saved_workflow_parity(
    client: TestClient,
) -> None:
    project = create_project(client, "Ecological mask bbox rounding")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201, image_link.text
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        mask.x_max = 24.5
        session.commit()
    linked = _annotation_link(client, project_id, image_link.json()["id"], "mask", mask_id)
    assert linked.status_code == 201, linked.text
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == registry.json()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("x_min", 2.0),
        ("y_min", 2.0),
        ("x_max", 35.0),
        ("y_max", 30.0),
    ],
)
def test_polygon_bbox_must_tightly_match_polygon_before_link(
    client: TestClient, field: str, value: float
) -> None:
    project = create_project(client, "Ecological oversized polygon bbox")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201, image_link.text
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        setattr(mask, field, value)
        session.commit()
    rejected = _annotation_link(client, project_id, image_link.json()["id"], "mask", mask_id)
    assert rejected.status_code == 400, rejected.text
    assert "does not match its source-pixel bounds" in rejected.json()["detail"]
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["annotation_evidence_count"] == 0


def test_polygon_bbox_stale_expansion_revokes_saved_workflow_artifact(
    client: TestClient,
) -> None:
    project = create_project(client, "Ecological stale polygon bbox")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201, image_link.text
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    linked = _annotation_link(client, project_id, image_link.json()["id"], "mask", mask_id)
    assert linked.status_code == 201, linked.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        mask.x_max = 35.0
        session.commit()
    standalone = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert standalone.status_code == 400, standalone.text
    assert "does not match its source-pixel bounds" in standalone.json()["detail"]
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert "does not match its source-pixel bounds" in workflow["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"])
