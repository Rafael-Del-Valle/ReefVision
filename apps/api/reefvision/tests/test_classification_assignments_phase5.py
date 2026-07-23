from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ClassificationAssignment,
    ClassificationLabelSet,
    ClassificationPrediction,
    ModelRegistration,
)
from reefvision.tests.test_classification_phase5 import _seed_classification_project


def _seed_prediction(
    client: TestClient,
    *,
    project_id: str,
    image_id: str,
    annotation_id: str,
    label_set: str,
    label_class_id: str,
    predicted_label: str,
    model_name: str,
) -> tuple[str, str]:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model_token = model_name.casefold().replace(" ", "-")
        model = ModelRegistration(
            project_id=project_id,
            purpose="classifier",
            display_name=model_name,
            source_filename=f"{model_token}.pt",
            managed_path=f"projects/{project_id}/models/{model_token}.pt",
            sha256=(model_token.encode("utf-8").hex() + "0" * 64)[:64],
            file_size_bytes=1,
            framework="ultralytics",
            task="classify",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={
                "classification_mode": "multiclass",
                "labels": [predicted_label],
                "mapping": {predicted_label: label_class_id},
            },
            metadata_json={"classification_label_set": label_set},
        )
        session.add(model)
        session.flush()
        prediction = ClassificationPrediction(
            project_id=project_id,
            image_id=image_id,
            annotation_id=annotation_id,
            model_id=model.id,
            label_set=label_set,
            classification_mode="multiclass",
            x_min=5,
            y_min=5,
            x_max=25,
            y_max=25,
            predicted_label=predicted_label,
            predicted_index=0,
            label_class_id=label_class_id,
            confidence=0.91,
            probabilities_json={predicted_label: 0.91},
            review_status="pending",
            inference_settings_json={"minimum_crop_size_px": 10},
            provenance_json={
                "model_checksum": model.sha256,
                "source_annotation_revision": 1,
            },
        )
        session.add(prediction)
        session.commit()
        return model.id, prediction.id


def test_multiple_classifiers_can_assign_independent_labels_to_one_box(
    client: TestClient,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    annotation_id = "e52cc1a2-321a-4c12-ad46-1b95a48600e1"

    state_set = client.post(
        f"/api/v1/projects/{project_id}/classification-label-sets",
        json={
            "key": "polyp-state",
            "name": "Polyp state",
            "target_kind": "annotation",
            "cardinality": "single",
            "allowed_class_ids": [class_ids["closed"], class_ids["open"]],
        },
    )
    assert state_set.status_code == 201, state_set.text
    health_set = client.post(
        f"/api/v1/projects/{project_id}/classification-label-sets",
        json={
            "key": "health-screen",
            "name": "Health screen",
            "target_kind": "annotation",
            "cardinality": "single",
            "allowed_class_ids": [class_ids["small"]],
        },
    )
    assert health_set.status_code == 201, health_set.text

    state_model_id, state_prediction_id = _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="polyp-state",
        label_class_id=class_ids["open"],
        predicted_label="open",
        model_name="Polyp state classifier",
    )
    health_model_id, health_prediction_id = _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="health-screen",
        label_class_id=class_ids["small"],
        predicted_label="healthy",
        model_name="Health classifier",
    )

    accepted_state = client.post(
        f"/api/v1/classification-predictions/{state_prediction_id}/accept-assignment",
        json={"label_set_id": state_set.json()["id"]},
    )
    assert accepted_state.status_code == 200, accepted_state.text
    accepted_health = client.post(
        f"/api/v1/classification-predictions/{health_prediction_id}/accept-assignment",
        json={"label_set_id": health_set.json()["id"]},
    )
    assert accepted_health.status_code == 200, accepted_health.text

    repeated = client.post(
        f"/api/v1/classification-predictions/{state_prediction_id}/accept-assignment",
        json={"label_set_id": state_set.json()["id"]},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["id"] == accepted_state.json()["id"]

    listed = client.get(
        f"/api/v1/projects/{project_id}/classification-assignments",
        params={"annotation_id": annotation_id},
    )
    assert listed.status_code == 200, listed.text
    assignments = listed.json()["items"]
    assert len(assignments) == 2
    assert {item["label_set_id"] for item in assignments} == {
        state_set.json()["id"],
        health_set.json()["id"],
    }
    assert {item["source_model_id"] for item in assignments} == {
        state_model_id,
        health_model_id,
    }

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        annotation = session.get(Annotation, annotation_id)
        assert annotation is not None
        assert annotation.label_class_id == class_ids["closed"]
        assert annotation.revision == 1
        assert (
            session.scalar(
                select(AnnotationEvent).where(
                    AnnotationEvent.annotation_id == annotation_id,
                    AnnotationEvent.event_type == "class_changed",
                )
            )
            is None
        )

    exported = client.get(
        f"/api/v1/projects/{project_id}/classification-assignments/export"
    )
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    assert payload["row_count"] == 2
    assert {row["label_set_key"] for row in payload["rows"]} == {
        "polyp-state",
        "health-screen",
    }
    assert all(row["bounding_box"] == [5.0, 5.0, 25.0, 25.0] for row in payload["rows"])


def test_single_label_set_supersedes_only_its_previous_assignment(
    client: TestClient,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    annotation_id = "e52cc1a2-321a-4c12-ad46-1b95a48600e1"
    created = client.post(
        f"/api/v1/projects/{project_id}/classification-label-sets",
        json={
            "key": "species-model",
            "name": "Species model",
            "target_kind": "annotation",
            "cardinality": "single",
            "allowed_class_ids": [class_ids["closed"], class_ids["open"]],
        },
    )
    assert created.status_code == 201, created.text
    label_set_id = created.json()["id"]

    _first_model_id, first_prediction_id = _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="species-model",
        label_class_id=class_ids["open"],
        predicted_label="first",
        model_name="First species classifier",
    )
    first = client.post(
        f"/api/v1/classification-predictions/{first_prediction_id}/accept-assignment",
        json={"label_set_id": label_set_id},
    )
    assert first.status_code == 200, first.text

    _second_model_id, second_prediction_id = _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="species-model",
        label_class_id=class_ids["closed"],
        predicted_label="second",
        model_name="Second species classifier",
    )
    second = client.post(
        f"/api/v1/classification-predictions/{second_prediction_id}/accept-assignment",
        json={"label_set_id": label_set_id},
    )
    assert second.status_code == 200, second.text

    accepted = client.get(
        f"/api/v1/projects/{project_id}/classification-assignments",
        params={"annotation_id": annotation_id, "label_set_id": label_set_id},
    )
    assert accepted.status_code == 200, accepted.text
    assert [item["id"] for item in accepted.json()["items"]] == [second.json()["id"]]

    superseded = client.get(
        f"/api/v1/projects/{project_id}/classification-assignments",
        params={
            "annotation_id": annotation_id,
            "label_set_id": label_set_id,
            "assignment_status": "superseded",
        },
    )
    assert superseded.status_code == 200, superseded.text
    assert [item["id"] for item in superseded.json()["items"]] == [first.json()["id"]]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        label_set = session.get(ClassificationLabelSet, label_set_id)
        assert label_set is not None
        rows = list(
            session.scalars(
                select(ClassificationAssignment).where(
                    ClassificationAssignment.label_set_id == label_set_id
                )
            )
        )
        assert {item.status for item in rows} == {"accepted", "superseded"}
