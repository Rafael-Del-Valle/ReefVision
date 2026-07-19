from __future__ import annotations

import json
import zipfile
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ClassificationPrediction,
    ImageAsset,
    ModelRegistration,
)
from reefvision.jobs.export import process_export_job
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import create_version


def _seed_classification_project(
    client: TestClient,
) -> tuple[dict[str, object], str, dict[str, str]]:
    project = create_project(client, "Phase 5 classification")
    report = import_one(client, str(project["id"]), size=(100, 80))
    image_id = str(report["successful"][0]["image_id"])
    classes = cast(list[dict[str, object]], project["label_classes"])
    class_ids = {
        "closed": str(classes[0]["id"]),
        "open": str(classes[2]["id"]),
        "small": str(classes[3]["id"]),
    }
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": "e52cc1a2-321a-4c12-ad46-1b95a48600e1",
                    "label_class_id": class_ids["closed"],
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 25,
                    "y_max": 25,
                },
                {
                    "id": "fb9be3b0-c268-4df0-b187-0f93fe53cd98",
                    "label_class_id": class_ids["open"],
                    "x_min": 30,
                    "y_min": 5,
                    "x_max": 50,
                    "y_max": 25,
                },
                {
                    "id": "1f09dc11-7dfd-4ead-859b-9cb2d30a7bd4",
                    "label_class_id": class_ids["small"],
                    "x_min": 60,
                    "y_min": 5,
                    "x_max": 65,
                    "y_max": 10,
                },
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    return project, image_id, class_ids


def test_classification_preview_and_export_remove_small_crops(
    client: TestClient,
) -> None:
    project, _image_id, _class_ids = _seed_classification_project(client)
    version = create_version(client, str(project["id"]), name="Classification crops")

    preview = client.post(
        f"/api/v1/projects/{project['id']}/classification-preview",
        json={
            "dataset_version_id": version["id"],
            "mode": "binary_state",
            "minimum_crop_size_px": 10,
        },
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["eligible_crop_count"] == 2
    assert payload["removed_during_preprocessing_count"] == 1
    assert {item["key"] for item in payload["classes"]} == {"open", "closed"}
    assert any("removed during preprocessing" in item for item in payload["warnings"])

    created = client.post(
        f"/api/v1/dataset-versions/{version['id']}/exports",
        json={
            "format": "classification_binary_state",
            "minimum_crop_size_px": 10,
            "padding_fraction": 0,
        },
    )
    assert created.status_code == 200, created.text
    export = created.json()["export"]
    job = created.json()["job"]
    app = cast(FastAPI, client.app)
    assert process_export_job(app.state.settings, app.state.session_factory, job["id"])

    archive_path = app.state.settings.resolved_data_dir / export["archive_path"]
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("export-manifest.json"))
    assert any(name.startswith("train/open/") for name in names)
    assert any(name.startswith("train/closed/") for name in names)
    assert manifest["classification_mode"] == "binary_state"
    assert manifest["preview"]["removed_during_preprocessing_count"] == 1
    assert "removed during preprocessing" in manifest["preprocessing_note"]


def test_classification_training_run_is_queued_with_immutable_provenance(
    client: TestClient,
) -> None:
    project, _image_id, _class_ids = _seed_classification_project(client)
    version = create_version(client, str(project["id"]), name="Classifier training")

    response = client.post(
        f"/api/v1/projects/{project['id']}/classification-training-runs",
        json={
            "dataset_version_id": version["id"],
            "mode": "multiclass",
            "minimum_crop_size_px": 10,
            "run_name": "Six-class coral state",
            "architecture": "yolov8n-cls.yaml",
            "epochs": 1,
            "batch": 2,
            "imgsz": 64,
        },
    )

    assert response.status_code == 201, response.text
    run = response.json()
    assert run["task"] == "classify"
    assert run["status"] == "queued"
    assert run["dataset_version_id"] == version["id"]
    assert run["preflight_report"]["eligible_crop_count"] == 2
    assert run["training_config"]["classification_mode"] == "multiclass"
    assert run["training_config"]["minimum_crop_size_px"] == 10
    assert run["initial_checkpoint_source"] == "scratch"
    assert run["resolved_model_checksum"] is None


def test_accepting_classification_prediction_changes_class_with_audit_event(
    client: TestClient,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=str(project["id"]),
            purpose="classifier",
            display_name="Test classifier",
            source_filename="classifier.pt",
            managed_path=f"projects/{project['id']}/models/classifier.pt",
            sha256="a" * 64,
            file_size_bytes=1,
            framework="ultralytics",
            task="classify",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={
                "classification_mode": "multiclass",
                "mapping": {"c002_Muricea_Open": class_ids["open"]},
            },
            metadata_json={},
        )
        session.add(model)
        session.flush()
        prediction = ClassificationPrediction(
            project_id=str(project["id"]),
            image_id=image_id,
            annotation_id="e52cc1a2-321a-4c12-ad46-1b95a48600e1",
            model_id=model.id,
            label_set="default",
            classification_mode="multiclass",
            x_min=5,
            y_min=5,
            x_max=25,
            y_max=25,
            predicted_label="c002_Muricea_Open",
            predicted_index=1,
            label_class_id=class_ids["open"],
            confidence=0.92,
            probabilities_json={"c002_Muricea_Open": 0.92},
            review_status="pending",
            inference_settings_json={"minimum_crop_size_px": 10},
            provenance_json={"model_checksum": model.sha256},
        )
        session.add(prediction)
        session.commit()
        prediction_id = prediction.id

    response = client.post(
        f"/api/v1/classification-predictions/{prediction_id}/review",
        json={"action": "accept"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["review_status"] == "accepted"
    assert response.json()["accepted_label_class_id"] == class_ids["open"]

    with app.state.session_factory() as session:
        annotation = session.get(
            Annotation,
            "e52cc1a2-321a-4c12-ad46-1b95a48600e1",
        )
        image = session.get(ImageAsset, image_id)
        assert annotation is not None
        assert image is not None
        assert annotation.label_class_id == class_ids["open"]
        assert annotation.source_type == "accepted_prediction"
        assert annotation.revision == 2
        assert image.annotation_revision == 2
        event = (
            session.query(AnnotationEvent)
            .filter_by(annotation_id=annotation.id, event_type="class_changed")
            .one()
        )
        assert event.before_json["label_class_id"] == class_ids["closed"]
        assert event.after_json["label_class_id"] == class_ids["open"]


def test_image_level_classification_labels_are_reviewable_metadata(
    client: TestClient,
) -> None:
    _project, image_id, class_ids = _seed_classification_project(client)
    created = client.post(
        f"/api/v1/images/{image_id}/labels",
        json={
            "label_class_id": class_ids["open"],
            "label_set": "whole-image-state",
        },
    )
    assert created.status_code == 201, created.text
    label = created.json()
    assert label["source_type"] == "human"
    listed = client.get(f"/api/v1/images/{image_id}/labels")
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [label["id"]]
    deleted = client.delete(f"/api/v1/image-labels/{label['id']}")
    assert deleted.status_code == 204
