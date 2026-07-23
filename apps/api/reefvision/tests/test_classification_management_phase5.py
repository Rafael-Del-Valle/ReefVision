from __future__ import annotations

import io

import numpy as np
from fastapi.testclient import TestClient

from reefvision.tests.test_classification_assignments_phase5 import _seed_prediction
from reefvision.tests.test_classification_phase5 import _seed_classification_project


def test_bulk_review_reports_per_prediction_outcomes(client: TestClient) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    annotation_id = "e52cc1a2-321a-4c12-ad46-1b95a48600e1"
    label_set = client.post(
        f"/api/v1/projects/{project_id}/classification-label-sets",
        json={
            "key": "bulk-state",
            "name": "Bulk state",
            "target_kind": "annotation",
            "cardinality": "multi",
            "allowed_class_ids": [class_ids["open"], class_ids["closed"]],
        },
    )
    assert label_set.status_code == 201, label_set.text
    _, open_prediction = _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="bulk-state",
        label_class_id=class_ids["open"],
        predicted_label="open",
        model_name="Bulk open classifier",
    )
    _, closed_prediction = _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="bulk-state",
        label_class_id=class_ids["closed"],
        predicted_label="closed",
        model_name="Bulk closed classifier",
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/classification-predictions/bulk-review",
        json={
            "prediction_ids": [open_prediction, closed_prediction, "missing-prediction"],
            "action": "accept",
            "label_set_id": label_set.json()["id"],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requested_count"] == 3
    assert payload["accepted_count"] == 2
    assert payload["failed_count"] == 1
    assert {item["outcome"] for item in payload["items"]} == {"accepted", "failed"}

    assignments = client.get(
        f"/api/v1/projects/{project_id}/classification-assignments",
        params={"label_set_id": label_set.json()["id"]},
    )
    assert assignments.status_code == 200, assignments.text
    assert len(assignments.json()["items"]) == 2


def test_model_comparison_groups_competing_predictions_by_target(client: TestClient) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    annotation_id = "e52cc1a2-321a-4c12-ad46-1b95a48600e1"
    _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="comparison-state",
        label_class_id=class_ids["open"],
        predicted_label="open",
        model_name="Comparison model A",
    )
    _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="comparison-state",
        label_class_id=class_ids["closed"],
        predicted_label="closed",
        model_name="Comparison model B",
    )

    response = client.get(
        f"/api/v1/projects/{project_id}/classification-model-comparison",
        params={"label_set": "comparison-state", "minimum_models": 2},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["target_count"] == 1
    assert payload["agreement_count"] == 0
    assert payload["disagreement_count"] == 1
    target = payload["targets"][0]
    assert target["target_kind"] == "annotation"
    assert target["model_count"] == 2
    assert target["agreement"] is False
    assert {item["model_name"] for item in target["predictions"]} == {
        "Comparison model A",
        "Comparison model B",
    }


def test_scientific_classification_downloads_csv_and_npz(client: TestClient) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    annotation_id = "e52cc1a2-321a-4c12-ad46-1b95a48600e1"
    label_set = client.post(
        f"/api/v1/projects/{project_id}/classification-label-sets",
        json={
            "key": "download-state",
            "name": "Download state",
            "target_kind": "annotation",
            "cardinality": "single",
            "allowed_class_ids": [class_ids["open"]],
        },
    )
    assert label_set.status_code == 201, label_set.text
    _, prediction_id = _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="download-state",
        label_class_id=class_ids["open"],
        predicted_label="open",
        model_name="Download classifier",
    )
    accepted = client.post(
        f"/api/v1/classification-predictions/{prediction_id}/accept-assignment",
        json={"label_set_id": label_set.json()["id"]},
    )
    assert accepted.status_code == 200, accepted.text
    assignment_id = accepted.json()["id"]

    csv_response = client.get(
        f"/api/v1/projects/{project_id}/classification-assignments/scientific-export.csv"
    )
    assert csv_response.status_code == 200, csv_response.text
    assert csv_response.headers["content-type"].startswith("text/csv")
    csv_text = csv_response.content.decode("utf-8-sig")
    assert "assignment_id" in csv_text
    assert assignment_id in csv_text
    assert "download-state" in csv_text

    npz_response = client.get(
        f"/api/v1/projects/{project_id}/classification-assignments/scientific-export.npz"
    )
    assert npz_response.status_code == 200, npz_response.text
    with np.load(io.BytesIO(npz_response.content), allow_pickle=False) as archive:
        assert archive["assignment_id"].tolist() == [assignment_id]
        assert archive["label_set_key"].tolist() == ["download-state"]
        assert archive["label_class_id"].tolist() == [class_ids["open"]]
        assert archive["bounding_box"].shape == (1, 4)
        assert "manifest_json" in archive.files
