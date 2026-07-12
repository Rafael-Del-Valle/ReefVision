from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.db.models import Annotation, AnnotationEvent, ImageAsset


def image_bytes(format_name: str = "PNG", size: tuple[int, int] = (80, 60)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, (20, 90, 120)).save(stream, format=format_name)
    return stream.getvalue()


def create_project(client: TestClient, name: str = "Annotation project") -> dict[str, Any]:
    response = client.post("/api/v1/projects", json={"name": name, "template": "octocoral"})
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def import_one(
    client: TestClient,
    project_id: str,
    *,
    filename: str = "coral.png",
    relative_path: str = "trial-1/coral.png",
    size: tuple[int, int] = (80, 60),
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/images",
        files=[("files", (filename, image_bytes(size=size), "application/octet-stream"))],
        data={"relative_paths": relative_path},
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_annotation_session_starts_empty_and_exposes_revision(client: TestClient) -> None:
    project = create_project(client)
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]

    response = client.get(f"/api/v1/images/{image_id}/annotations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["annotations"] == []
    assert payload["image"]["annotation_revision"] == 0
    assert payload["counts_by_class"][0]["count"] == 0


def test_annotation_session_reports_adjacent_images_in_gallery_order(
    client: TestClient,
) -> None:
    project = create_project(client)
    first = import_one(
        client,
        project["id"],
        filename="first.png",
        relative_path="series/first.png",
        size=(80, 60),
    )
    middle = import_one(
        client,
        project["id"],
        filename="middle.png",
        relative_path="series/middle.png",
        size=(81, 60),
    )
    last = import_one(
        client,
        project["id"],
        filename="last.png",
        relative_path="series/last.png",
        size=(82, 60),
    )
    first_id = first["successful"][0]["image_id"]
    middle_id = middle["successful"][0]["image_id"]
    last_id = last["successful"][0]["image_id"]

    app = cast(FastAPI, client.app)
    base_time = datetime(2026, 7, 8, tzinfo=UTC)
    with app.state.session_factory() as session:
        images = {
            image.id: image
            for image in session.query(ImageAsset)
            .filter(ImageAsset.id.in_([first_id, middle_id, last_id]))
            .all()
        }
        images[first_id].created_at = base_time
        images[middle_id].created_at = base_time + timedelta(seconds=10)
        images[last_id].created_at = base_time + timedelta(seconds=20)
        session.commit()

    response = client.get(f"/api/v1/images/{middle_id}/annotations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["previous_image_id"] == last_id
    assert payload["next_image_id"] == first_id


def test_annotation_batch_save_persists_counts_status_and_events(client: TestClient) -> None:
    project = create_project(client)
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]

    create_response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "annotated",
            "annotations": [
                {
                    "id": "3a521166-d6d7-42ef-a3cd-fb4090f8df49",
                    "label_class_id": label_class_id,
                    "x_min": 10,
                    "y_min": 5,
                    "x_max": 30,
                    "y_max": 25,
                }
            ],
        },
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    assert created["image"]["annotation_revision"] == 1
    assert created["image"]["annotation_status"] == "annotated"
    assert created["counts_by_class"][0]["count"] == 1

    update_response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 1,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": "3a521166-d6d7-42ef-a3cd-fb4090f8df49",
                    "label_class_id": project["label_classes"][1]["id"],
                    "x_min": 12,
                    "y_min": 8,
                    "x_max": 40,
                    "y_max": 28,
                }
            ],
        },
    )
    assert update_response.status_code == 200, update_response.text

    reloaded = client.get(f"/api/v1/images/{image_id}/annotations").json()
    assert reloaded["image"]["annotation_revision"] == 2
    assert reloaded["image"]["annotation_status"] == "reviewed"
    assert reloaded["annotations"][0]["label_class_id"] == project["label_classes"][1]["id"]
    assert reloaded["annotations"][0]["x_min"] == 12
    assert reloaded["counts_by_class"][1]["count"] == 1

    image_response = client.get(f"/api/v1/images/{image_id}")
    assert image_response.status_code == 200
    assert image_response.json()["annotation_count"] == 1

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        events = (
            session.query(AnnotationEvent)
            .filter_by(image_id=image_id)
            .order_by(AnnotationEvent.created_at, AnnotationEvent.id)
            .all()
        )
        assert [event.event_type for event in events] == ["created", "class_changed"]


def test_annotation_save_is_transactional_and_rejects_invalid_boxes(client: TestClient) -> None:
    project = create_project(client)
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]

    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [
                {
                    "id": "1cb9521d-b776-4a62-bc28-58776af5aad4",
                    "label_class_id": label_class_id,
                    "x_min": 1,
                    "y_min": 1,
                    "x_max": 20,
                    "y_max": 20,
                },
                {
                    "id": "8412087a-7441-4ced-a5b8-cb0bc43b9f32",
                    "label_class_id": label_class_id,
                    "x_min": 10,
                    "y_min": 10,
                    "x_max": 10,
                    "y_max": 30,
                },
            ],
        },
    )

    assert response.status_code == 400
    assert "positive width and height" in response.json()["detail"]
    assert client.get(f"/api/v1/images/{image_id}/annotations").json()["annotations"] == []

    out_of_bounds = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [
                {
                    "id": "ef60f0b2-6d7b-44d5-ab10-cfc2e5a1d739",
                    "label_class_id": label_class_id,
                    "x_min": -1,
                    "y_min": 1,
                    "x_max": 20,
                    "y_max": 20,
                }
            ],
        },
    )
    assert out_of_bounds.status_code == 400
    assert "outside the image" in out_of_bounds.json()["detail"]


def test_annotation_save_rejects_cross_project_classes_and_stale_revisions(
    client: TestClient,
) -> None:
    project = create_project(client, "Primary")
    other_project = create_project(client, "Secondary")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]

    wrong_class = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [
                {
                    "id": "4e7fb9d4-3a4e-4aac-838f-4d3449393d88",
                    "label_class_id": other_project["label_classes"][0]["id"],
                    "x_min": 1,
                    "y_min": 1,
                    "x_max": 20,
                    "y_max": 20,
                }
            ],
        },
    )
    assert wrong_class.status_code == 400
    assert "does not belong" in wrong_class.json()["detail"]

    initial_save = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [
                {
                    "id": "b7f94fe3-46c1-47eb-bca4-98765d607d74",
                    "label_class_id": project["label_classes"][0]["id"],
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 15,
                    "y_max": 15,
                }
            ],
        },
    )
    assert initial_save.status_code == 200

    stale = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
        },
    )
    assert stale.status_code == 409
    assert "revision conflict" in stale.json()["detail"].lower()


def test_annotation_delete_and_restore_record_events(client: TestClient) -> None:
    project = create_project(client)
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    annotation_id = "63012db7-4cca-4adf-86e6-e3f2a4a7db8f"

    created = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [
                {
                    "id": annotation_id,
                    "label_class_id": project["label_classes"][0]["id"],
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 15,
                    "y_max": 15,
                }
            ],
        },
    )
    assert created.status_code == 200

    deleted = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={"base_revision": 1, "annotation_status": "in_progress", "annotations": []},
    )
    assert deleted.status_code == 200
    assert deleted.json()["annotations"] == []

    restored = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 2,
            "annotation_status": "in_progress",
            "annotations": [
                {
                    "id": annotation_id,
                    "label_class_id": project["label_classes"][0]["id"],
                    "x_min": 6,
                    "y_min": 6,
                    "x_max": 16,
                    "y_max": 16,
                }
            ],
        },
    )
    assert restored.status_code == 200
    assert restored.json()["annotations"][0]["x_min"] == 6

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        annotation = session.get(Annotation, annotation_id)
        assert annotation is not None
        assert annotation.deleted_at is None
        event_types = [
            event.event_type
            for event in session.query(AnnotationEvent)
            .filter_by(annotation_id=annotation_id)
            .order_by(AnnotationEvent.created_at, AnnotationEvent.id)
        ]
        assert event_types == ["created", "deleted", "restored"]
