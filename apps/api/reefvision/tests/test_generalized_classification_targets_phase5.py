from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

import reefvision.jobs.classification_inference as inference_module
from reefvision.db.models import (
    ClassificationAssignment,
    ClassificationPrediction,
    Job,
    MaskAnnotation,
)
from reefvision.ml.classification import ClassificationResult
from reefvision.tests.test_classification_inference_safety_phase5 import (
    _SuccessfulProvider,
    _seed_classifier,
)
from reefvision.tests.test_classification_phase5 import _seed_classification_project


class _InspectingMaskProvider:
    provider_name = "ultralytics"
    provider_version = "test"

    def load_model(self, model_path: Path, device: str) -> None:
        assert model_path.is_file()
        assert device == "cpu"

    def predict(self, image_path: Path, *, device: str) -> ClassificationResult:
        assert device == "cpu"
        with Image.open(image_path) as crop:
            rgb = crop.convert("RGB")
            assert rgb.size == (40, 40)
            assert rgb.getpixel((5, 5)) == (20, 90, 120)
            assert rgb.getpixel((35, 35)) == (0, 0, 0)
        return ClassificationResult(
            label="open",
            class_index=1,
            confidence=0.8,
            probabilities={"closed": 0.2, "open": 0.8, "small": 0.0},
        )

    def unload_model(self) -> None:
        return None


def _process_job(client: TestClient, job_id: str) -> bool:
    app = cast(FastAPI, client.app)
    return inference_module.process_classification_inference_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )


def test_whole_image_classifier_creates_reviewable_image_assignment(
    client: TestClient,
    monkeypatch,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    model_id = _seed_classifier(client, project_id=project_id, class_ids=class_ids)
    queued = client.post(
        f"/api/v1/projects/{project_id}/classification-inference-jobs",
        json={
            "model_id": model_id,
            "target_kind": "image",
            "image_ids": [image_id],
            "device": "cpu",
            "label_set": "whole-image-condition",
        },
    )
    assert queued.status_code == 201, queued.text
    monkeypatch.setattr(
        inference_module,
        "UltralyticsClassificationProvider",
        _SuccessfulProvider,
    )
    assert _process_job(client, str(queued.json()["id"]))

    predictions = client.get(
        f"/api/v1/projects/{project_id}/classification-predictions",
        params={"model_id": model_id},
    )
    assert predictions.status_code == 200, predictions.text
    item = predictions.json()["items"][0]
    assert item["target_kind"] == "image"
    assert item["target_key"] == f"image:{image_id}"
    assert item["annotation_id"] is None
    assert item["mask_annotation_id"] is None
    assert item["x_min"] == 0
    assert item["y_min"] == 0
    assert item["x_max"] == 100
    assert item["y_max"] == 80

    accepted = client.post(
        f"/api/v1/classification-predictions/{item['id']}/review",
        json={"action": "accept"},
    )
    assert accepted.status_code == 200, accepted.text
    assignments = client.get(
        f"/api/v1/projects/{project_id}/classification-assignments",
        params={"image_id": image_id},
    )
    assert assignments.status_code == 200, assignments.text
    assignment = assignments.json()["items"][0]
    assert assignment["target_kind"] == "image"
    assert assignment["target_key"] == f"image:{image_id}"


def test_fragment_classifier_masks_background_and_preserves_fragment_identity(
    client: TestClient,
    monkeypatch,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    model_id = _seed_classifier(client, project_id=project_id, class_ids=class_ids)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = MaskAnnotation(
            image_id=image_id,
            label_class_id=class_ids["closed"],
            geometry_kind="polygon",
            polygon_json=[[10, 10], [50, 10], [10, 50]],
            x_min=10,
            y_min=10,
            x_max=50,
            y_max=50,
            area_pixels=800,
            measurement_json={"centerline_points": [], "surface_model": "none"},
            source_type="human",
            provenance_json={"fragment_key": "fragment-A"},
            status="verified",
        )
        session.add(mask)
        session.commit()
        mask_id = mask.id

    queued = client.post(
        f"/api/v1/projects/{project_id}/classification-inference-jobs",
        json={
            "model_id": model_id,
            "target_kind": "fragment",
            "mask_annotation_ids": [mask_id],
            "minimum_crop_size_px": 1,
            "padding_fraction": 0,
            "mask_background": "black",
            "device": "cpu",
            "label_set": "fragment-condition",
        },
    )
    assert queued.status_code == 201, queued.text
    monkeypatch.setattr(
        inference_module,
        "UltralyticsClassificationProvider",
        _InspectingMaskProvider,
    )
    assert _process_job(client, str(queued.json()["id"]))

    with app.state.session_factory() as session:
        prediction = session.scalar(
            select(ClassificationPrediction).where(
                ClassificationPrediction.inference_job_id == str(queued.json()["id"])
            )
        )
        assert prediction is not None
        assert prediction.target_kind == "fragment"
        assert prediction.target_key == "fragment:fragment-A"
        assert prediction.mask_annotation_id == mask_id
        assert prediction.fragment_key == "fragment-A"
        prediction_id = prediction.id

    accepted = client.post(
        f"/api/v1/classification-predictions/{prediction_id}/review",
        json={"action": "accept"},
    )
    assert accepted.status_code == 200, accepted.text
    with app.state.session_factory() as session:
        assignment = session.scalar(
            select(ClassificationAssignment).where(
                ClassificationAssignment.source_prediction_id == prediction_id
            )
        )
        assert assignment is not None
        assert assignment.target_kind == "fragment"
        assert assignment.mask_annotation_id == mask_id
        assert assignment.fragment_key == "fragment-A"


def test_changed_mask_revision_blocks_fragment_assignment(
    client: TestClient,
    monkeypatch,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    model_id = _seed_classifier(client, project_id=project_id, class_ids=class_ids)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = MaskAnnotation(
            image_id=image_id,
            label_class_id=class_ids["closed"],
            geometry_kind="polygon",
            polygon_json=[[10, 10], [50, 10], [10, 50]],
            x_min=10,
            y_min=10,
            x_max=50,
            y_max=50,
            area_pixels=800,
            measurement_json={"centerline_points": [], "surface_model": "none"},
            source_type="human",
            provenance_json={"fragment_key": "fragment-stale"},
            status="verified",
        )
        session.add(mask)
        session.commit()
        mask_id = mask.id

    queued = client.post(
        f"/api/v1/projects/{project_id}/classification-inference-jobs",
        json={
            "model_id": model_id,
            "target_kind": "fragment",
            "mask_annotation_ids": [mask_id],
            "minimum_crop_size_px": 1,
            "mask_background": "keep",
            "device": "cpu",
            "label_set": "fragment-stale-check",
        },
    )
    assert queued.status_code == 201, queued.text
    monkeypatch.setattr(
        inference_module,
        "UltralyticsClassificationProvider",
        _SuccessfulProvider,
    )
    assert _process_job(client, str(queued.json()["id"]))

    with app.state.session_factory() as session:
        prediction = session.scalar(
            select(ClassificationPrediction).where(
                ClassificationPrediction.inference_job_id == str(queued.json()["id"])
            )
        )
        mask = session.get(MaskAnnotation, mask_id)
        assert prediction is not None
        assert mask is not None
        prediction_id = prediction.id
        mask.revision += 1
        session.commit()

    accepted = client.post(
        f"/api/v1/classification-predictions/{prediction_id}/review",
        json={"action": "accept"},
    )
    assert accepted.status_code == 409, accepted.text
    with app.state.session_factory() as session:
        job = session.get(Job, str(queued.json()["id"]))
        prediction = session.get(ClassificationPrediction, prediction_id)
        assignment = session.scalar(
            select(ClassificationAssignment).where(
                ClassificationAssignment.source_prediction_id == prediction_id
            )
        )
        assert job is not None and job.status == "succeeded"
        assert prediction is not None and prediction.review_status == "pending"
        assert assignment is None
