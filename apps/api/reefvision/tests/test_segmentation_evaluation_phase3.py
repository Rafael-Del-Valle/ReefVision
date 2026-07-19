from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, ModelRegistration, PredictionProposal
from reefvision.tests.test_annotations import create_project, import_one


def test_segmentation_evaluation_matches_instances_and_counts_false_positives(
    client: TestClient,
) -> None:
    project = create_project(client, "Segmentation evaluation")
    imported = import_one(client, str(project["id"]), size=(40, 40))
    image_id = str(imported["successful"][0]["image_id"])
    label_class_id = str(project["label_classes"][0]["id"])
    mask_id = "3c5b78b5-9765-4f38-b4b8-617dd5e77054"

    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": label_class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 5, "y": 5},
                        {"x": 15, "y": 5},
                        {"x": 15, "y": 15},
                        {"x": 5, "y": 15},
                    ],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=str(project["id"]),
            purpose="segmenter",
            display_name="Evaluation segmenter",
            source_filename="segmenter.pt",
            managed_path=f"projects/{project['id']}/models/segmenter.pt",
            sha256="d" * 64,
            file_size_bytes=1,
            framework="ultralytics",
            task="segment",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            metadata_json={},
        )
        session.add(model)
        session.flush()
        job = Job(
            project_id=str(project["id"]),
            job_type="inference",
            status="succeeded",
            request_json={},
            result_json={},
        )
        session.add(job)
        session.flush()
        session.add_all(
            [
                PredictionProposal(
                    project_id=str(project["id"]),
                    image_id=image_id,
                    model_id=model.id,
                    inference_job_id=job.id,
                    model_checksum=model.sha256,
                    label_class_id=label_class_id,
                    predicted_label="coral",
                    predicted_index=0,
                    confidence=0.95,
                    geometry_kind="polygon",
                    polygon_json=[[5, 5], [15, 5], [15, 15], [5, 15]],
                    x_min=5,
                    y_min=5,
                    x_max=15,
                    y_max=15,
                    review_status="pending",
                    inference_settings_json={},
                    provenance_json={},
                ),
                PredictionProposal(
                    project_id=str(project["id"]),
                    image_id=image_id,
                    model_id=model.id,
                    inference_job_id=job.id,
                    model_checksum=model.sha256,
                    label_class_id=label_class_id,
                    predicted_label="coral",
                    predicted_index=0,
                    confidence=0.8,
                    geometry_kind="polygon",
                    polygon_json=[[25, 25], [35, 25], [35, 35], [25, 35]],
                    x_min=25,
                    y_min=25,
                    x_max=35,
                    y_max=35,
                    review_status="pending",
                    inference_settings_json={},
                    provenance_json={},
                ),
                PredictionProposal(
                    project_id=str(project["id"]),
                    image_id=image_id,
                    model_id=model.id,
                    inference_job_id=job.id,
                    model_checksum=model.sha256,
                    label_class_id=label_class_id,
                    predicted_label="coral",
                    predicted_index=0,
                    confidence=0.1,
                    geometry_kind="polygon",
                    polygon_json=[[1, 25], [5, 25], [5, 30], [1, 30]],
                    x_min=1,
                    y_min=25,
                    x_max=5,
                    y_max=30,
                    review_status="pending",
                    inference_settings_json={},
                    provenance_json={},
                ),
            ]
        )
        session.commit()
        model_id = model.id

    response = client.post(
        f"/api/v1/projects/{project['id']}/segmentation-evaluations",
        json={
            "model_id": model_id,
            "image_ids": [image_id],
            "confidence_threshold": 0.25,
            "match_iou_threshold": 0.5,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ground_truth_count"] == 1
    assert payload["prediction_count"] == 2
    assert payload["matched_count"] == 1
    assert payload["false_positive_count"] == 1
    assert payload["false_negative_count"] == 0
    assert payload["instance_precision"] == pytest.approx(0.5)
    assert payload["instance_recall"] == pytest.approx(1.0)
    assert payload["mean_iou"] == pytest.approx(1.0)
    assert payload["mean_dice"] == pytest.approx(1.0)
    assert len(payload["per_class"]) == 1
    assert payload["per_class"][0]["label_class_id"] == label_class_id
    assert payload["matches"][0]["ground_truth_mask_id"] == mask_id
