from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import MaskAnnotation
from reefvision.tests.test_classification_assignments_phase5 import _seed_prediction
from reefvision.tests.test_classification_phase5 import _seed_classification_project


def _accept_box_assignment(
    client: TestClient,
    *,
    project_id: str,
    image_id: str,
    annotation_id: str,
    label_class_id: str,
) -> None:
    label_set = client.post(
        f"/api/v1/projects/{project_id}/classification-label-sets",
        json={
            "key": "condition-model",
            "name": "Condition model",
            "target_kind": "annotation",
            "cardinality": "single",
            "allowed_class_ids": [label_class_id],
        },
    )
    assert label_set.status_code == 201, label_set.text
    _model_id, prediction_id = _seed_prediction(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set="condition-model",
        label_class_id=label_class_id,
        predicted_label="condition-a",
        model_name="Scientific export classifier",
    )
    accepted = client.post(
        f"/api/v1/classification-predictions/{prediction_id}/accept-assignment",
        json={"label_set_id": label_set.json()["id"]},
    )
    assert accepted.status_code == 200, accepted.text


def test_scientific_export_joins_box_to_one_containing_fragment_mask(
    client: TestClient,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    annotation_id = "e52cc1a2-321a-4c12-ad46-1b95a48600e1"
    _accept_box_assignment(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_class_id=class_ids["open"],
    )

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        fragment = MaskAnnotation(
            image_id=image_id,
            label_class_id=class_ids["closed"],
            geometry_kind="polygon",
            polygon_json=[[0, 0], [50, 0], [50, 50], [0, 50]],
            x_min=0,
            y_min=0,
            x_max=50,
            y_max=50,
            area_pixels=2500,
            measurement_json={
                "centerline_points": [{"x": 0, "y": 25}, {"x": 50, "y": 25}],
                "surface_model": "none",
                "depth_value": None,
                "diameter_value": None,
                "notes": "fragment mask",
            },
            source_type="human",
            provenance_json={"target_role": "coral_fragment"},
            status="verified",
        )
        session.add(fragment)
        session.commit()
        fragment_id = fragment.id

    response = client.get(
        f"/api/v1/projects/{project_id}/classification-assignments/scientific-export"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["row_count"] == 1
    assert payload["matched_measurement_count"] == 1
    assert payload["unmatched_measurement_count"] == 0
    assert payload["ambiguous_measurement_count"] == 0
    row = payload["rows"][0]
    assert row["measurement_join_status"] == "matched"
    assert row["measurement_mask_id"] == fragment_id
    assert row["measurement_candidate_mask_ids"] == [fragment_id]
    assert row["measurements"]["area_pixels"] == 2500
    assert row["measurements"]["perimeter_pixels"] == 200
    assert row["measurements"]["contained_box_count"] == 2
    assert row["measurements"]["total_linear_extension_pixels"] == 50


def test_scientific_export_does_not_guess_between_overlapping_masks(
    client: TestClient,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    annotation_id = "e52cc1a2-321a-4c12-ad46-1b95a48600e1"
    _accept_box_assignment(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_class_id=class_ids["open"],
    )

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        for offset in (0, 2):
            session.add(
                MaskAnnotation(
                    image_id=image_id,
                    label_class_id=class_ids["closed"],
                    geometry_kind="polygon",
                    polygon_json=[
                        [offset, offset],
                        [40 + offset, offset],
                        [40 + offset, 40 + offset],
                        [offset, 40 + offset],
                    ],
                    x_min=offset,
                    y_min=offset,
                    x_max=40 + offset,
                    y_max=40 + offset,
                    area_pixels=1600,
                    measurement_json={
                        "centerline_points": [],
                        "surface_model": "none",
                    },
                    source_type="human",
                    provenance_json={"target_role": "coral_fragment"},
                    status="verified",
                )
            )
        session.commit()

    response = client.get(
        f"/api/v1/projects/{project_id}/classification-assignments/scientific-export"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["matched_measurement_count"] == 0
    assert payload["ambiguous_measurement_count"] == 1
    row = payload["rows"][0]
    assert row["measurement_join_status"] == "ambiguous"
    assert row["measurement_mask_id"] is None
    assert len(row["measurement_candidate_mask_ids"]) == 2
    assert row["measurements"] == {}
    assert any("multiple verified masks" in warning for warning in payload["warnings"])
