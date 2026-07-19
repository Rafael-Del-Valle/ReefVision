from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ClassificationPrediction, ModelRegistration
from reefvision.tests.test_classification_phase5 import _seed_classification_project


def test_classification_evaluation_reports_confusion_f1_and_calibration(
    client: TestClient,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=str(project["id"]),
            purpose="classifier",
            display_name="Evaluation classifier",
            source_filename="evaluation.pt",
            managed_path=f"projects/{project['id']}/models/evaluation.pt",
            sha256="e" * 64,
            file_size_bytes=1,
            framework="ultralytics",
            task="classify",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            metadata_json={},
        )
        session.add(model)
        session.flush()
        session.add_all(
            [
                ClassificationPrediction(
                    project_id=str(project["id"]),
                    image_id=image_id,
                    annotation_id="e52cc1a2-321a-4c12-ad46-1b95a48600e1",
                    model_id=model.id,
                    label_set="evaluation",
                    classification_mode="multiclass",
                    x_min=5,
                    y_min=5,
                    x_max=25,
                    y_max=25,
                    predicted_label="closed",
                    predicted_index=0,
                    label_class_id=class_ids["closed"],
                    confidence=0.9,
                    probabilities_json={"closed": 0.9},
                    review_status="pending",
                    inference_settings_json={},
                    provenance_json={},
                ),
                ClassificationPrediction(
                    project_id=str(project["id"]),
                    image_id=image_id,
                    annotation_id="fb9be3b0-c268-4df0-b187-0f93fe53cd98",
                    model_id=model.id,
                    label_set="evaluation",
                    classification_mode="multiclass",
                    x_min=30,
                    y_min=5,
                    x_max=50,
                    y_max=25,
                    predicted_label="closed",
                    predicted_index=0,
                    label_class_id=class_ids["closed"],
                    confidence=0.8,
                    probabilities_json={"closed": 0.8},
                    review_status="pending",
                    inference_settings_json={},
                    provenance_json={},
                ),
                ClassificationPrediction(
                    project_id=str(project["id"]),
                    image_id=image_id,
                    annotation_id="1f09dc11-7dfd-4ead-859b-9cb2d30a7bd4",
                    model_id=model.id,
                    label_set="evaluation",
                    classification_mode="multiclass",
                    x_min=60,
                    y_min=5,
                    x_max=65,
                    y_max=10,
                    predicted_label="small",
                    predicted_index=2,
                    label_class_id=class_ids["small"],
                    confidence=0.6,
                    probabilities_json={"small": 0.6},
                    review_status="pending",
                    inference_settings_json={},
                    provenance_json={},
                ),
            ]
        )
        session.commit()
        model_id = model.id

    response = client.post(
        f"/api/v1/projects/{project['id']}/classification-evaluations",
        json={
            "model_id": model_id,
            "review_statuses": ["pending"],
            "label_set": "evaluation",
            "calibration_bin_count": 5,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["sample_count"] == 3
    assert payload["correct_count"] == 2
    assert payload["accuracy"] == pytest.approx(2 / 3)
    assert payload["macro_precision"] == pytest.approx(0.5)
    assert payload["macro_recall"] == pytest.approx(2 / 3)
    assert payload["macro_f1"] == pytest.approx(5 / 9)
    assert payload["weighted_f1"] == pytest.approx(5 / 9)
    assert payload["mean_confidence"] == pytest.approx(0.7666666667)
    assert payload["expected_calibration_error"] == pytest.approx(11 / 30)
    assert payload["top_label_brier_score"] == pytest.approx(0.27)

    confusion = {
        (item["actual_label_class_id"], item["predicted_label_class_id"]): item[
            "count"
        ]
        for item in payload["confusion_matrix"]
    }
    assert confusion[(class_ids["closed"], class_ids["closed"])] == 1
    assert confusion[(class_ids["open"], class_ids["closed"])] == 1
    assert confusion[(class_ids["small"], class_ids["small"])] == 1

    by_class = {item["label_class_id"]: item for item in payload["per_class"]}
    assert by_class[class_ids["closed"]]["precision"] == pytest.approx(0.5)
    assert by_class[class_ids["closed"]]["recall"] == pytest.approx(1)
    assert by_class[class_ids["open"]]["f1"] == pytest.approx(0)
    assert by_class[class_ids["small"]]["f1"] == pytest.approx(1)
