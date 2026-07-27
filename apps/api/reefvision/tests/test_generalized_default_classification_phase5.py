from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

import reefvision.jobs.classification_inference as inference_module
from reefvision.db.models import ClassificationAssignment, ClassificationLabelSet
from reefvision.tests.test_classification_inference_safety_phase5 import (
    _seed_classifier,
    _SuccessfulProvider,
)
from reefvision.tests.test_classification_phase5 import _seed_classification_project


def test_default_whole_image_review_creates_non_destructive_assignment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
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
            "label_set": "default",
        },
    )
    assert queued.status_code == 201, queued.text
    monkeypatch.setattr(
        inference_module,
        "UltralyticsClassificationProvider",
        _SuccessfulProvider,
    )
    app = cast(FastAPI, client.app)
    assert inference_module.process_classification_inference_job(
        app.state.settings,
        app.state.session_factory,
        str(queued.json()["id"]),
    )

    predictions = client.get(
        f"/api/v1/projects/{project_id}/classification-predictions",
        params={"model_id": model_id},
    )
    assert predictions.status_code == 200, predictions.text
    prediction_id = predictions.json()["items"][0]["id"]
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
        assert assignment.target_kind == "image"
        label_set = session.get(ClassificationLabelSet, assignment.label_set_id)
        assert label_set is not None
        assert label_set.key == "default-image"
        assert label_set.target_kind == "image"
        assert not label_set.replaces_primary_class
