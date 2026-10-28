from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, ModelRegistration, PredictionProposal
from reefvision.tests.test_annotations import create_project, import_one


def _import_images(client: TestClient, project_id: str) -> tuple[str, str]:
    first = import_one(
        client,
        project_id,
        filename="first.png",
        relative_path="round/first.png",
    )
    second = import_one(
        client,
        project_id,
        filename="second.png",
        relative_path="round/second.png",
        size=(81, 60),
    )
    assert first["successful"] and second["successful"]
    return (
        str(first["successful"][0]["image_id"]),
        str(second["successful"][0]["image_id"]),
    )


def _seed_detector_proposals(
    client: TestClient,
    project: dict[str, Any],
    confidence_by_image: dict[str, float],
) -> str:
    app = cast(FastAPI, client.app)
    label_class_id = str(project["label_classes"][0]["id"])
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=str(project["id"]),
            purpose="detector",
            display_name="Active-learning detector",
            source_filename="active-learning.pt",
            managed_path=f"{project['storage_root']}/models/active-learning.pt",
            sha256="c" * 64,
            file_size_bytes=123,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={"mapping": {"coral": label_class_id}},
            input_size_json={"width": 640, "height": 640},
            metadata_json={},
        )
        job = Job(
            project_id=str(project["id"]),
            job_type="inference",
            status="succeeded",
            progress_current=len(confidence_by_image),
            progress_total=len(confidence_by_image),
            request_json={},
            result_json={},
        )
        session.add_all([model, job])
        session.flush()
        for index, (image_id, confidence) in enumerate(confidence_by_image.items()):
            session.add(
                PredictionProposal(
                    project_id=str(project["id"]),
                    image_id=image_id,
                    model_id=model.id,
                    inference_job_id=job.id,
                    model_checksum=model.sha256,
                    label_class_id=label_class_id,
                    predicted_label="coral",
                    predicted_index=0,
                    confidence=confidence,
                    x_min=1 + index,
                    y_min=2,
                    x_max=20 + index,
                    y_max=25,
                    review_status="pending",
                    inference_settings_json={"confidence": 0.01},
                    provenance_json={"source": "phase7-acceptance"},
                )
            )
        session.commit()
        return model.id


def _mark_image_reviewed(
    client: TestClient,
    project: dict[str, Any],
    image_id: str,
) -> None:
    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": "6ab320fc-4fe9-487a-b480-e151d879a2fe",
                    "label_class_id": str(project["label_classes"][0]["id"]),
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 30,
                    "y_max": 25,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["image"]["annotation_status"] == "reviewed"


def test_uncertainty_uses_real_prediction_confidence_and_explains_selection(
    client: TestClient,
) -> None:
    project = create_project(client, "Active learning uncertainty")
    low_confidence_image, high_confidence_image = _import_images(client, project["id"])
    model_id = _seed_detector_proposals(
        client,
        project,
        {
            low_confidence_image: 0.15,
            high_confidence_image: 0.92,
        },
    )

    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Confidence-driven round",
            "strategy": "uncertainty",
            "requested_size": 1,
            "model_ids": [model_id],
        },
    )
    assert response.status_code == 201, response.text
    round_record = response.json()
    selected = round_record["selection_manifest_json"]["items"]
    assert len(selected) == 1
    assert selected[0]["image_id"] == low_confidence_image
    assert selected[0]["reason_summary"]
    assert selected[0]["score_breakdown"]
    assert selected[0]["signal_values"]
    assert len(round_record["selection_sha256"]) == 64

    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Equivalent round",
            "strategy": "uncertainty",
            "requested_size": 1,
            "model_ids": [model_id],
        },
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == round_record["id"]


@pytest.mark.parametrize("strategy", ["hybrid", "uncertainty", "rare_class", "quality"])
def test_every_acquisition_strategy_emits_explainable_manifest(
    client: TestClient,
    strategy: str,
) -> None:
    project = create_project(client, f"Active learning {strategy}")
    first_image, second_image = _import_images(client, project["id"])
    model_id = _seed_detector_proposals(
        client,
        project,
        {first_image: 0.35, second_image: 0.75},
    )

    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": f"{strategy} round",
            "strategy": strategy,
            "requested_size": 1,
            "model_ids": [model_id],
        },
    )
    assert response.status_code == 201, response.text
    item = response.json()["selection_manifest_json"]["items"][0]
    assert item["reason_summary"]
    assert isinstance(item["score_breakdown"], list)
    assert isinstance(item["signal_values"], dict)


def test_completed_review_creates_idempotent_feedback_dataset(
    client: TestClient,
) -> None:
    project = create_project(client, "Active learning feedback")
    low_confidence_image, high_confidence_image = _import_images(client, project["id"])
    model_id = _seed_detector_proposals(
        client,
        project,
        {
            low_confidence_image: 0.10,
            high_confidence_image: 0.95,
        },
    )
    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Feedback round",
            "strategy": "uncertainty",
            "requested_size": 1,
            "model_ids": [model_id],
        },
    )
    assert response.status_code == 201, response.text
    round_record = response.json()
    selected = round_record["selection_manifest_json"]["items"][0]
    assert selected["image_id"] == low_confidence_image

    item_id = selected["queue_item_id"]
    # Queue bookkeeping requires explicit researcher confirmation. A missing
    # confirmation must not count toward active-learning feedback readiness.
    unconfirmed = client.post(f"/api/v1/review-queue-items/{item_id}/complete")
    assert unconfirmed.status_code == 422, unconfirmed.text
    before_confirmation = client.get(
        f"/api/v1/active-learning-rounds/{round_record['id']}/feedback"
    )
    assert before_confirmation.status_code == 200, before_confirmation.text
    assert before_confirmation.json()["completed_count"] == 0

    completed = client.post(
        f"/api/v1/review-queue-items/{item_id}/complete",
        json={"actor": "active-learning reviewer", "review_confirmed": True},
    )
    assert completed.status_code == 200, completed.text

    feedback = client.get(f"/api/v1/active-learning-rounds/{round_record['id']}/feedback")
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["completed_count"] == 1
    assert feedback.json()["completion_fraction"] == 1.0
    assert feedback.json()["feedback_dataset_version_id"] is None

    premature = client.post(f"/api/v1/active-learning-rounds/{round_record['id']}/complete")
    assert premature.status_code == 409, premature.text
    assert "marked reviewed" in premature.json()["detail"].lower()

    _mark_image_reviewed(client, project, low_confidence_image)
    finalized = client.post(f"/api/v1/active-learning-rounds/{round_record['id']}/complete")
    assert finalized.status_code == 200, finalized.text
    finalized_payload = finalized.json()
    assert finalized_payload["status"] == "complete"
    feedback_dataset_id = finalized_payload["feedback_summary_json"]["feedback_dataset_version_id"]
    manifest_sha256 = finalized_payload["feedback_summary_json"]["feedback_manifest_sha256"]
    assert len(feedback_dataset_id) == 36
    assert len(manifest_sha256) == 64
    assert finalized_payload["feedback_summary_json"]["completed_image_ids"] == [
        low_confidence_image
    ]

    versions = client.get(f"/api/v1/projects/{project['id']}/dataset-versions")
    assert versions.status_code == 200, versions.text
    feedback_versions = [
        version for version in versions.json() if version["id"] == feedback_dataset_id
    ]
    assert len(feedback_versions) == 1
    feedback_version = feedback_versions[0]
    assert feedback_version["status"] == "complete"
    assert feedback_version["image_count"] == 1
    assert feedback_version["annotation_count"] == 1
    assert feedback_version["manifest_sha256"] == manifest_sha256

    refreshed_feedback = client.get(f"/api/v1/active-learning-rounds/{round_record['id']}/feedback")
    assert refreshed_feedback.status_code == 200, refreshed_feedback.text
    assert refreshed_feedback.json()["feedback_dataset_version_id"] == feedback_dataset_id
    assert refreshed_feedback.json()["feedback_manifest_sha256"] == manifest_sha256

    repeated = client.post(f"/api/v1/active-learning-rounds/{round_record['id']}/complete")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["feedback_summary_json"]["feedback_dataset_version_id"] == (
        feedback_dataset_id
    )
    versions_after_repeat = client.get(f"/api/v1/projects/{project['id']}/dataset-versions")
    assert versions_after_repeat.status_code == 200, versions_after_repeat.text
    assert (
        sum(version["id"] == feedback_dataset_id for version in versions_after_repeat.json()) == 1
    )


def test_active_learning_rejects_foreign_models(client: TestClient) -> None:
    project = create_project(client, "Active learning scope")
    import_one(client, project["id"], filename="sample.png", relative_path="sample.png")

    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Bad model scope",
            "strategy": "hybrid",
            "requested_size": 1,
            "model_ids": ["00000000-0000-0000-0000-000000000000"],
        },
    )
    assert response.status_code == 400
