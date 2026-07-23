from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import Annotation, ClassificationAssignment, ClassificationLabelSet
from reefvision.tests.test_classification_assignments_phase5 import _seed_prediction
from reefvision.tests.test_classification_phase5 import _seed_classification_project


def test_existing_review_endpoint_keeps_different_tasks_independent(
    client: TestClient,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    annotation_id = "e52cc1a2-321a-4c12-ad46-1b95a48600e1"

    first_model_id, first_prediction_id = _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="polyp-state",
        label_class_id=class_ids["open"],
        predicted_label="open",
        model_name="State classifier",
    )
    second_model_id, second_prediction_id = _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="health-condition",
        label_class_id=class_ids["small"],
        predicted_label="healthy",
        model_name="Health classifier review route",
    )

    first = client.post(
        f"/api/v1/classification-predictions/{first_prediction_id}/review",
        json={"action": "accept"},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/v1/classification-predictions/{second_prediction_id}/review",
        json={"action": "accept"},
    )
    assert second.status_code == 200, second.text

    repeated = client.post(
        f"/api/v1/classification-predictions/{first_prediction_id}/review",
        json={"action": "accept"},
    )
    assert repeated.status_code == 200, repeated.text

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        annotation = session.get(Annotation, annotation_id)
        assert annotation is not None
        assert annotation.label_class_id == class_ids["closed"]
        assert annotation.revision == 1

        assignments = list(
            session.scalars(
                select(ClassificationAssignment).where(
                    ClassificationAssignment.annotation_id == annotation_id,
                    ClassificationAssignment.status == "accepted",
                )
            )
        )
        assert len(assignments) == 2
        assert {item.source_model_id for item in assignments} == {
            first_model_id,
            second_model_id,
        }
        assert len({item.label_set_id for item in assignments}) == 2
        label_sets = list(
            session.scalars(
                select(ClassificationLabelSet).where(
                    ClassificationLabelSet.id.in_([item.label_set_id for item in assignments])
                )
            )
        )
        assert {item.key for item in label_sets} == {
            "polyp-state",
            "health-condition",
        }
        assert all(not item.replaces_primary_class for item in label_sets)
