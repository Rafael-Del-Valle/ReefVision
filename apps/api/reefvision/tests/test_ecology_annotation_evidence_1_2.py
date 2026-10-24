"""Annotation revision links are project-scoped, unverified and fail closed."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from reefvision.db.models import Annotation, ImageAsset, MaskAnnotation
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_ecology_image_evidence_1_2 import (
    _link,
    _register,
    _workflow,
)


def _box(client: TestClient, image_id: str, label_id: str) -> str:
    annotation_id = "38abbe44-1d2a-4bd3-a6a7-6d0dffafc105"
    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": annotation_id,
                    "label_class_id": label_id,
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 30,
                    "y_max": 25,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return annotation_id


def _mask(client: TestClient, image_id: str, label_id: str) -> str:
    mask_id = "6a16bda5-7b56-4985-849d-34bc334a80e1"
    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": label_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 5, "y": 5},
                        {"x": 25, "y": 5},
                        {"x": 25, "y": 20},
                        {"x": 5, "y": 20},
                    ],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return mask_id


def _annotation_link(
    client: TestClient,
    project_id: str,
    image_evidence_id: str,
    kind: str,
    annotation_id: str,
    *,
    expected_revision: int = 1,
) -> Response:
    return client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/colony-a/annotation-evidence",
        json={
            "image_evidence_id": image_evidence_id,
            "annotation_kind": kind,
            "annotation_id": annotation_id,
            "expected_annotation_revision": expected_revision,
            "reason": "Annotation linked for scientist review",
        },
    )


def test_annotation_link_persists_unverified_source_in_saved_workflow(
    client: TestClient,
) -> None:
    project = create_project(client, "Annotation evidence parity")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201, image_link.text
    box_id = _box(client, image_id, str(project["label_classes"][0]["id"]))
    linked = _annotation_link(client, project_id, image_link.json()["id"], "box", box_id)
    assert linked.status_code == 201, linked.text
    assert linked.json()["evidence_level"] == "linked_unverified"
    assert len(linked.json()["annotation_sha256"]) == 64
    duplicate = _annotation_link(client, project_id, image_link.json()["id"], "box", box_id)
    assert duplicate.status_code == 409
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    snapshot = registry.json()
    assert snapshot["annotation_evidence_count"] == 1
    assert snapshot["annotation_evidence_links"] == [linked.json()]
    assert snapshot["review_gate"] == "scientist_review_required"
    assert snapshot["evidence_level"] == "registered_unverified"
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [row for row in run["artifacts"] if row["data_type"] == "ecology_identity_registry"]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == snapshot


def test_mask_annotation_change_blocks_api_and_saved_workflow(
    client: TestClient,
) -> None:
    project = create_project(client, "Mask annotation source integrity")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    linked = _annotation_link(client, project_id, image_link.json()["id"], "mask", mask_id)
    assert linked.status_code == 201, linked.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        mask.area_pixels = 1
        session.commit()

    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "revision is missing or changed" in registry.json()["detail"]
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "failed"
    assert "revision is missing or changed" in run["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in run["artifacts"])


def test_annotation_link_rejects_foreign_image_and_stale_revision(
    client: TestClient,
) -> None:
    project = create_project(client, "Annotation ownership")
    project_id = str(project["id"])
    first_image = str(import_one(client, project_id)["successful"][0]["image_id"])
    second_image = str(
        import_one(
            client,
            project_id,
            filename="other-coral.png",
            relative_path="trial-1/other-coral.png",
            size=(82, 61),
        )["successful"][0]["image_id"]
    )
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", first_image)
    assert image_link.status_code == 201
    box_id = _box(client, second_image, str(project["label_classes"][0]["id"]))
    foreign = _annotation_link(client, project_id, image_link.json()["id"], "box", box_id)
    assert foreign.status_code == 400, foreign.text
    assert "mismatched" in foreign.json()["detail"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        box = session.get(Annotation, box_id)
        assert box is not None
        box.image_id = first_image
        box.revision = 2
        source_image = session.get(ImageAsset, first_image)
        assert source_image is not None
        source_image.annotation_status = "reviewed"
        session.commit()
    stale = _annotation_link(client, project_id, image_link.json()["id"], "box", box_id)
    assert stale.status_code == 409, stale.text
    assert "Stale annotation revision" in stale.json()["detail"]


def test_unreviewed_annotation_cannot_be_linked_or_promoted(
    client: TestClient,
) -> None:
    project = create_project(client, "Annotation review gate")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201
    box_id = _box(client, image_id, str(project["label_classes"][0]["id"]))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        box = session.get(Annotation, box_id)
        assert box is not None
        box.source_type = "model"
        session.commit()
    rejected = _annotation_link(client, project_id, image_link.json()["id"], "box", box_id)
    assert rejected.status_code == 400, rejected.text
    assert "reviewed human annotations" in rejected.json()["detail"]
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200
    assert registry.json()["annotation_evidence_count"] == 0
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    assert all(
        row["payload_json"]["review_gate"] == "scientist_review_required"
        for row in run["artifacts"]
        if row["data_type"] == "ecology_identity_registry"
    )


def test_review_status_revocation_blocks_saved_workflow(
    client: TestClient,
) -> None:
    project = create_project(client, "Review revocation")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201
    box_id = _box(client, image_id, str(project["label_classes"][0]["id"]))
    linked = _annotation_link(client, project_id, image_link.json()["id"], "box", box_id)
    assert linked.status_code == 201
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.annotation_status = "in_progress"
        session.commit()
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400
    assert "reviewed image status" in registry.json()["detail"]
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "failed"
    assert "reviewed image status" in run["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in run["artifacts"])


def test_out_of_image_box_rejected_before_linking(
    client: TestClient,
) -> None:
    project = create_project(client, "Ecological box bounds validation")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201
    box_id = _box(client, image_id, str(project["label_classes"][0]["id"]))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        box = session.get(Annotation, box_id)
        image = session.get(ImageAsset, image_id)
        assert box is not None and image is not None
        box.x_max = image.width_px + 1
        session.commit()
    linked = _annotation_link(client, project_id, image_link.json()["id"], "box", box_id)
    assert linked.status_code == 400, linked.text
    assert "outside source image" in linked.json()["detail"]


def test_changed_box_bounds_fail_registry_and_saved_workflow(
    client: TestClient,
) -> None:
    project = create_project(client, "Ecological box bounds revocation")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201
    box_id = _box(client, image_id, str(project["label_classes"][0]["id"]))
    linked = _annotation_link(client, project_id, image_link.json()["id"], "box", box_id)
    assert linked.status_code == 201, linked.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        box = session.get(Annotation, box_id)
        assert box is not None
        box.x_min = float("inf")
        session.commit()
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "nonfinite source-pixel bounds" in registry.json()["detail"]
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "failed"
    assert "nonfinite source-pixel bounds" in run["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in run["artifacts"])


def test_mutated_mask_polygon_rejected_in_saved_workflow(
    client: TestClient,
) -> None:
    project = create_project(client, "Ecological mask polygon bounds")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    linked = _annotation_link(client, project_id, image_link.json()["id"], "mask", mask_id)
    assert linked.status_code == 201, linked.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        image = session.get(ImageAsset, image_id)
        assert mask is not None and image is not None
        mask.polygon_json = [[0, 0], [image.width_px + 1, 0], [0, 10]]
        session.commit()
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "polygon extends outside source image" in registry.json()["detail"]
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "failed"
    assert "polygon extends outside source image" in run["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in run["artifacts"])


def test_foreign_label_class_rejected_before_linking(
    client: TestClient,
) -> None:
    project = create_project(client, "Ecological class owner A")
    other = create_project(client, "Ecological class owner B")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    image_link = _link(client, project_id, "colony-a", image_id)
    assert image_link.status_code == 201
    box_id = _box(client, image_id, str(project["label_classes"][0]["id"]))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        box = session.get(Annotation, box_id)
        assert box is not None
        box.label_class_id = str(other["label_classes"][0]["id"])
        session.commit()
    linked = _annotation_link(client, project_id, image_link.json()["id"], "box", box_id)
    assert linked.status_code == 400, linked.text
    assert "class must belong to the source project" in linked.json()["detail"]
