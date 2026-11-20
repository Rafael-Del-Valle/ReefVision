from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ClassificationPrediction,
    ImageAsset,
    ModelRegistration,
    VideoTrack,
)

from .test_annotations import import_one
from .test_class_reassignment import create_label_class, create_project, seed_reassignment_records
from .test_model_inference import register_model
from .test_reviewed_model_runtime_v15 import local_detector  # noqa: F401 - pytest fixture
from .test_reviewer_lab_v15 import judgement, make_round, role_fixture, successful
from .test_video_tracking_phase6 import _import_video


def test_multimodal_class_usage_blocks_destructive_editing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client)
    source = create_label_class(
        client, project["id"], class_index=0, name="Observed", display_color="#227755"
    )
    target = create_label_class(
        client, project["id"], class_index=1, name="New class", display_color="#447799"
    )
    seed_reassignment_records(client, project, source, target)
    video = _import_video(client, project["id"], monkeypatch)
    track = (
        client.post(
            f"/api/v1/videos/{video['id']}/tracks",
            json={
                "label_class_id": source["id"],
                "keyframes": [
                    {"frame": 0, "bbox": [10, 10, 20, 10]},
                    {"frame": 10, "bbox": [30, 10, 20, 10]},
                ],
                "interpolation": "linear",
                "status": "verified",
            },
        )
        .raise_for_status()
        .json()
    )
    engine = cast(FastAPI, client.app).state.engine
    with Session(engine) as session:
        model = session.get_one(ModelRegistration, "model-1")
        session.add(
            ClassificationPrediction(
                id="classification-queued",
                project_id=project["id"],
                image_id="image-1",
                model_id=model.id,
                label_class_id=source["id"],
                confidence=0.875,
                rank=1,
                scores_json={},
                status="pending",
            )
        )
        session.commit()

    project_class = f"/api/v1/projects/{project['id']}/classes/{source['id']}"
    usage = client.get(project_class + "/usage").raise_for_status().json()
    counts = {item["key"]: item["count"] for item in usage["counts"]}
    assert counts["video_tracks_active"] == counts["classification_predictions"] == 1
    assert not usage["can_delete"]
    assert client.delete(f"/api/v1/classes/{source['id']}").status_code == 409
    preview = (
        client.post(project_class + "/reassign/preview", json={"target_class_id": target["id"]})
        .raise_for_status()
        .json()
    )
    groups = {group["key"]: group["record_ids"] for group in preview["plan"]["blocking_records"]}
    assert groups["video_tracks_active"] == [track["id"]]
    assert groups["classification_predictions"] == ["classification-queued"]
    assert (
        client.post(
            project_class + "/reassign",
            json={
                "operation_id": preview["id"],
                "preview_checksum": preview["preview_checksum"],
            },
        ).status_code
        == 409
    )
    with Session(engine) as session:
        original_track = session.get_one(VideoTrack, track["id"])
        assert original_track.label_class_id == source["id"] and original_track.status == "verified"
        assert [keyframe["bbox"] for keyframe in original_track.keyframes_json] == [
            [10, 10, 20, 10],
            [30, 10, 20, 10],
        ]
        assert (
            session.get_one(ClassificationPrediction, "classification-queued").label_class_id
            == source["id"]
        )


def test_class_index_is_not_an_editable_presentation_field(client: TestClient) -> None:
    project = create_project(client)
    source = create_label_class(
        client, project["id"], class_index=2, name="Observed", display_color="#227755"
    )
    class_path = f"/api/v1/classes/{source['id']}"
    assert client.patch(class_path, json={"class_index": 8}).status_code == 422
    change = (
        client.patch(class_path, json={"display_order": 8, "name": "Local display name"})
        .raise_for_status()
        .json()
    )
    assert change["name"] == "Local display name"
    assert change["display_order"] == 8 and change["class_index"] == 2


def test_reviewer_lab_scope_is_unchanged_by_class_edits(client: TestClient) -> None:
    project = create_project(client)
    source = create_label_class(
        client, project["id"], class_index=0, name="Observed", display_color="#227755"
    )
    target = create_label_class(
        client, project["id"], class_index=1, name="New class", display_color="#447799"
    )
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    path = f"/api/v1/images/{image_id}/annotations"
    client.put(
        path,
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": source["id"],
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 14,
                    "y_max": 19,
                }
            ],
        },
    ).raise_for_status()
    before = client.get(path).raise_for_status().json()
    _, lab, roles = role_fixture(client, project["id"])
    plan = make_round(client, lab, roles, [{"type": "image", "id": image_id}])
    round_url = f"{lab}/rounds/{plan['id']}"
    subject_url = f"{round_url}/subjects/{plan['subjects'][0]['id']}"
    for label in ("Reviewer A", "Reviewer B"):
        successful(
            client.post(
                subject_url + "/decision",
                json=judgement(plan, "usable", "Independent fixture"),
                headers=roles[label][1],
            ),
            201,
        )
    report = successful(client.post(round_url + "/seal", headers=roles["Manager"][1]), 201)

    root = f"/api/v1/projects/{project['id']}/classes/{source['id']}"
    preview = (
        client.post(root + "/reassign/preview", json={"target_class_id": target["id"]})
        .raise_for_status()
        .json()
    )
    categories = {
        group["key"]: group["record_ids"] for group in preview["plan"]["blocking_records"]
    }
    assert categories["reviewer_lab_rounds"] == [plan["id"]]
    assert (
        client.post(
            root + "/reassign",
            json={"operation_id": preview["id"], "preview_checksum": preview["preview_checksum"]},
        ).status_code
        == 409
    )
    class_path = f"/api/v1/classes/{source['id']}"
    client.patch(
        class_path, json={"name": "Presentation name", "display_order": 10}
    ).raise_for_status()
    client.post(class_path + "/archive").raise_for_status()
    client.post(class_path + "/restore").raise_for_status()
    assert (
        client.get(path).raise_for_status().json()["image"]["annotation_revision"]
        == before["image"]["annotation_revision"]
    )
    assert successful(client.post(round_url + "/seal", headers=roles["Manager"][1]), 201) == report


@pytest.mark.usefixtures("local_detector")
def test_model_runtime_mapping_stays_frozen_across_class_rename(client: TestClient) -> None:
    project = create_project(client)
    model = register_model(
        client,
        project["id"],
        purpose="detector",
        filename="fixture.pt",
        display_name="Fixture detector",
    )
    root = f"/api/v1/projects/{project['id']}/model-runtime-selections"
    draft = {
        "model_id": model["id"],
        "runtime_id": "pytorch",
        "device": "cpu",
        "prompt": "confidence 0.47, iou 0.38",
    }
    preview = client.post(root + "/preview", json=draft).raise_for_status().json()
    selected = (
        client.post(root, json={"draft": draft, "reviewed_sha256": preview["content_sha256"]})
        .raise_for_status()
        .json()
    )
    class_id = next(
        identifier for identifier in selected["snapshot"]["class_mapping"].values() if identifier
    )
    class_path = f"/api/v1/classes/{class_id}"
    usage = client.get(class_path + "/usage").raise_for_status().json()
    assert {row["key"]: row["count"] for row in usage["counts"]}["model_runtime_selections"] == 1
    client.patch(
        class_path, json={"name": "New local name", "display_order": 31}
    ).raise_for_status()
    assert client.delete(class_path).status_code == 409
    assert client.get(root + "/" + selected["id"]).raise_for_status().json() == selected


def test_reassignment_refuses_stale_semantics_and_commits_once_under_retry(
    client: TestClient,
) -> None:
    project = create_project(client)
    source = create_label_class(
        client, project["id"], class_index=0, name="Observed", display_color="#227755"
    )
    target = create_label_class(
        client, project["id"], class_index=1, name="Target", display_color="#447799"
    )
    seed_reassignment_records(client, project, source, target)
    route = f"/api/v1/projects/{project['id']}/classes/{source['id']}/reassign"
    selection = {"target_class_id": target["id"], "notes": "Reviewed proposal"}

    def requested_action() -> dict[str, str]:
        preview = client.post(route + "/preview", json=selection).raise_for_status().json()
        return {"operation_id": preview["id"], "preview_checksum": preview["preview_checksum"]}

    stale = requested_action()
    client.patch(
        f"/api/v1/classes/{target['id']}", json={"scientific_name": "Updated taxonomy"}
    ).raise_for_status()
    assert client.post(route, json=stale).status_code == 409
    fresh = requested_action()
    ready = Barrier(2, timeout=5)

    def submit() -> Response:
        ready.wait()
        return client.post(route, json=fresh)

    with ThreadPoolExecutor(max_workers=2) as executor:
        requests = [executor.submit(submit) for _ in range(2)]
        first, second = [item.result(timeout=15).raise_for_status().json() for item in requests]
    assert first == second
    assert first["status"] == "completed"
    assert client.post(route, json={**fresh, "notes": "Changed retry"}).status_code == 409
    with Session(cast(FastAPI, client.app).state.engine) as session:
        box = session.get_one(Annotation, "annotation-active")
        assert box.label_class_id == target["id"]
        assert (box.x_min, box.y_min, box.x_max, box.y_max) == (10, 20, 100, 140)
        events = session.scalars(
            select(AnnotationEvent).where(AnnotationEvent.event_type == "class_reassigned")
        ).all()
        assert len(events) == 1
        assert events[0].before_json["label_class_id"] == source["id"]
        assert events[0].after_json["label_class_id"] == target["id"]
        assert session.get_one(ImageAsset, "image-1").annotation_revision == 3
