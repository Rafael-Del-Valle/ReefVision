from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import (
    Annotation,
    ComputedMetricResult,
    ImageAsset,
    Job,
    LabelClass,
    MaskAnnotation,
    ModelRegistration,
    PredictionProposal,
)
from reefvision.tests.test_annotations import create_project, import_one


def _import(client: TestClient, project_id: str, index: int) -> str:
    report = import_one(
        client,
        project_id,
        filename=f"reef-{index}.png",
        relative_path=f"survey/reef-{index}.png",
        size=(80 + index, 60),
    )
    return str(report["successful"][0]["image_id"])


def _save(
    client: TestClient,
    image_id: str,
    labels: list[str],
    *,
    status: str = "reviewed",
    masks: list[tuple[str, str]] | None = None,
) -> None:
    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": status,
            "annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": label,
                    "x_min": 2 + index,
                    "y_min": 2,
                    "x_max": 12 + index,
                    "y_max": 12,
                }
                for index, label in enumerate(labels)
            ],
            "mask_annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": label,
                    "geometry_kind": "polygon",
                    **({"status": "draft"} if mask_status == "draft" else {}),
                    "points": [
                        {"x": 20, "y": 2},
                        {"x": 30, "y": 2},
                        {"x": 30, "y": 12},
                        {"x": 20, "y": 12},
                    ],
                }
                for label, mask_status in (masks or [])
            ],
        },
    )
    assert response.status_code == 200, response.text


def _definition(
    client: TestClient,
    project_id: str,
    *,
    source_kind: str = "verified_annotations",
    grouping_level: str = "image",
    label_class_ids: list[str] | None = None,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/computed-aggregate-definitions",
        json={
            "name": "Reviewed organism count",
            "source_kind": source_kind,
            "grouping_level": grouping_level,
            "label_class_ids": label_class_ids or [],
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _preview(client: TestClient, project_id: str, definition_id: str, image_ids: list[str]):
    return client.post(
        f"/api/v1/projects/{project_id}/computed-aggregate-definitions/{definition_id}/preview",
        json={"image_ids": image_ids},
    )


def _calculate(client: TestClient, project_id: str, definition_id: str, image_ids: list[str]):
    return client.post(
        f"/api/v1/projects/{project_id}/computed-aggregate-definitions/{definition_id}/calculate",
        json={"image_ids": image_ids},
    )


def test_empty_preview_and_zero_observation_calculation_refusal(client: TestClient) -> None:
    project = create_project(client, "Empty aggregate")
    image_id = _import(client, project["id"], 1)
    client.patch(
        f"/api/v1/images/{image_id}",
        json={"annotation_status": "reviewed", "group_key": None},
    )
    definition = _definition(client, project["id"])

    preview = _preview(client, project["id"], definition["id"], [image_id])
    assert preview.status_code == 200, preview.text
    assert preview.json()["observation_count"] == 0
    assert preview.json()["image_count"] == 1
    assert preview.json()["independent_unit_count"] == 1

    calculated = client.post(
        f"/api/v1/projects/{project['id']}/computed-aggregate-definitions/"
        f"{definition['id']}/calculate",
        json={"image_ids": [image_id]},
    )
    assert calculated.status_code == 400
    assert "zero" in calculated.json()["detail"].lower()


def test_selection_rejects_duplicates_and_cross_project_images(client: TestClient) -> None:
    project = create_project(client, "Selection aggregate")
    other = create_project(client, "Foreign aggregate")
    image_id = _import(client, project["id"], 2)
    foreign_id = _import(client, other["id"], 3)
    definition = _definition(client, project["id"])

    assert (
        _preview(client, project["id"], definition["id"], [image_id, image_id]).status_code == 422
    )
    response = _preview(client, project["id"], definition["id"], [foreign_id])
    assert response.status_code == 400
    assert "project" in response.json()["detail"].lower()


def test_reviewed_eligibility_and_source_separation(client: TestClient) -> None:
    project = create_project(client, "Evidence aggregate")
    labels = [str(item["id"]) for item in project["label_classes"][:2]]
    reviewed_id = _import(client, project["id"], 4)
    annotated_id = _import(client, project["id"], 5)
    _save(
        client,
        reviewed_id,
        [labels[0], labels[0], labels[1]],
        masks=[(labels[0], "verified"), (labels[1], "draft")],
    )
    _save(client, annotated_id, [labels[0]], status="annotated")

    boxes = _definition(client, project["id"], label_class_ids=[labels[0]])
    box_preview = _preview(client, project["id"], boxes["id"], [reviewed_id])
    assert box_preview.status_code == 200, box_preview.text
    assert box_preview.json()["observation_count"] == 2
    assert box_preview.json()["counts_by_class"] == [
        {"label_class_id": labels[0], "label_name": "Muricea Closed", "count": 2}
    ]

    masks = _definition(client, project["id"], source_kind="verified_masks")
    mask_preview = _preview(client, project["id"], masks["id"], [reviewed_id])
    assert mask_preview.status_code == 200, mask_preview.text
    assert mask_preview.json()["observation_count"] == 1

    unreviewed = _preview(client, project["id"], boxes["id"], [annotated_id])
    assert unreviewed.status_code == 400
    assert "reviewed" in unreviewed.json()["detail"].lower()


def test_image_and_group_key_independent_units_are_literal(client: TestClient) -> None:
    project = create_project(client, "Replicate aggregate")
    label = str(project["label_classes"][0]["id"])
    first = _import(client, project["id"], 6)
    second = _import(client, project["id"], 7)
    third = _import(client, project["id"], 8)
    _save(client, first, [label, label])
    _save(client, second, [label])
    _save(client, third, [label, label, label])
    for image_id, group_key in ((first, "colony-a"), (second, "colony-a"), (third, "colony-b")):
        response = client.patch(
            f"/api/v1/images/{image_id}",
            json={"annotation_status": "reviewed", "group_key": group_key},
        )
        assert response.status_code == 200, response.text

    image_definition = _definition(client, project["id"])
    image_result = _preview(
        client, project["id"], image_definition["id"], [first, second, third]
    ).json()
    assert image_result["observation_count"] == 6
    assert image_result["independent_unit_count"] == 3
    assert image_result["mean_per_independent_unit"] == 2

    group_definition = _definition(client, project["id"], grouping_level="image_group_key")
    grouped = _preview(client, project["id"], group_definition["id"], [first, second, third])
    assert grouped.status_code == 200, grouped.text
    payload = grouped.json()
    assert payload["independent_unit_count"] == 2
    assert payload["mean_per_independent_unit"] == 3
    assert [(item["unit_key"], item["observation_count"]) for item in payload["groups"]] == [
        ("colony-a", 3),
        ("colony-b", 3),
    ]

    response = client.patch(
        f"/api/v1/images/{third}",
        json={"annotation_status": "reviewed", "group_key": None},
    )
    assert response.status_code == 200
    missing = _preview(client, project["id"], group_definition["id"], [third])
    assert missing.status_code == 400
    assert "group key" in missing.json()["detail"].lower()


def test_pending_proposals_are_reported_but_never_counted(client: TestClient) -> None:
    project = create_project(client, "Proposal exclusion")
    image_id = _import(client, project["id"], 9)
    label_id = str(project["label_classes"][0]["id"])
    _save(client, image_id, [label_id])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project["id"],
            purpose="detector",
            display_name="Detector",
            source_filename="detector.pt",
            managed_path="models/detector.pt",
            sha256="c" * 64,
            file_size_bytes=1,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            input_size_json={},
            metadata_json={},
        )
        job = Job(project_id=project["id"], job_type="inference", status="succeeded")
        session.add_all([model, job])
        session.flush()
        session.add(
            PredictionProposal(
                project_id=project["id"],
                image_id=image_id,
                model_id=model.id,
                inference_job_id=job.id,
                model_checksum=model.sha256,
                label_class_id=label_id,
                predicted_label="coral",
                confidence=0.9,
                x_min=1,
                y_min=1,
                x_max=10,
                y_max=10,
                review_status="pending",
                inference_settings_json={},
            )
        )
        session.commit()

    definition = _definition(client, project["id"])
    payload = _preview(client, project["id"], definition["id"], [image_id]).json()
    assert payload["observation_count"] == 1
    assert payload["excluded_proposals_by_status"] == {"pending": 1}


def test_calculation_persists_immutable_typed_result_and_lists_separately(
    client: TestClient,
) -> None:
    project = create_project(client, "Persist aggregate")
    image_id = _import(client, project["id"], 10)
    label_id = str(project["label_classes"][0]["id"])
    _save(client, image_id, [label_id])
    definition = _definition(client, project["id"])
    response = client.post(
        f"/api/v1/projects/{project['id']}/computed-aggregate-definitions/"
        f"{definition['id']}/calculate",
        json={"image_ids": [image_id]},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["result_kind"] == "annotation_aggregate"
    assert result["observation_count"] == 1
    assert len(result["content_sha256"]) == 64
    assert client.get(f"/api/v1/projects/{project['id']}/computed-aggregate-results").json() == {
        "items": [result],
        "total": 1,
    }
    assert (
        client.get(f"/api/v1/projects/{project['id']}/computed-metric-results").json()["total"] == 0
    )


def test_result_validation_detects_deleted_and_reclassified_annotations(
    client: TestClient,
) -> None:
    project = create_project(client, "Aggregate currentness")
    image_id = _import(client, project["id"], 11)
    first_label = str(project["label_classes"][0]["id"])
    second_label = str(project["label_classes"][1]["id"])
    _save(client, image_id, [first_label, first_label])
    definition = _definition(client, project["id"])
    result = _calculate(client, project["id"], definition["id"], [image_id]).json()
    url = f"/api/v1/projects/{project['id']}/computed-aggregate-results/{result['id']}/validation"

    current = client.get(url)
    assert current.status_code == 200, current.text
    assert current.json() == {
        "result_id": result["id"],
        "current": True,
        "saved_evidence_sha256": result["evidence_sha256"],
        "current_evidence_sha256": result["evidence_sha256"],
        "reasons": [],
    }

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        rows = session.query(Annotation).filter_by(image_id=image_id).order_by(Annotation.id).all()
        rows[0].label_class_id = second_label
        rows[0].revision += 1
        rows[1].deleted_at = rows[1].updated_at
        session.commit()

    stale = client.get(url)
    assert stale.status_code == 200, stale.text
    assert stale.json()["current"] is False
    assert stale.json()["current_evidence_sha256"] != result["evidence_sha256"]
    assert any("label_changed" in reason for reason in stale.json()["reasons"])
    assert any("missing" in reason for reason in stale.json()["reasons"])


def test_result_validation_detects_mask_and_image_contract_changes(client: TestClient) -> None:
    project = create_project(client, "Mask currentness")
    image_id = _import(client, project["id"], 12)
    label_id = str(project["label_classes"][0]["id"])
    _save(client, image_id, [], masks=[(label_id, "verified")])
    response = client.patch(
        f"/api/v1/images/{image_id}",
        json={"annotation_status": "reviewed", "group_key": "colony-a"},
    )
    assert response.status_code == 200, response.text
    definition = _definition(
        client, project["id"], source_kind="verified_masks", grouping_level="image_group_key"
    )
    result = _calculate(client, project["id"], definition["id"], [image_id]).json()
    url = f"/api/v1/projects/{project['id']}/computed-aggregate-results/{result['id']}/validation"
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.query(MaskAnnotation).filter_by(image_id=image_id).one()
        mask.status = "draft"
        mask.revision += 1
        image = session.get(ImageAsset, image_id)
        image.group_key = "colony-b"
        image.annotation_status = "annotated"
        session.commit()

    stale = client.get(url).json()
    assert stale["current"] is False
    assert any("status_changed" in reason for reason in stale["reasons"])
    assert any("group_key_changed" in reason for reason in stale["reasons"])
    assert any("review_status_changed" in reason for reason in stale["reasons"])

    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        session.delete(image)
        session.commit()
    missing = client.get(url).json()
    assert missing["current"] is False
    assert f"image_missing:{image_id}" in missing["reasons"]


def test_result_validation_detects_class_label_taxonomy_change(client: TestClient) -> None:
    project = create_project(client, "Aggregate label currentness")
    image_id = _import(client, project["id"], 16)
    label_id = str(project["label_classes"][0]["id"])
    _save(client, image_id, [label_id])
    definition = _definition(client, project["id"])
    result = _calculate(client, project["id"], definition["id"], [image_id]).json()
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        label = session.get(LabelClass, label_id)
        label.name = "Renamed taxon"
        session.commit()

    response = client.get(
        f"/api/v1/projects/{project['id']}/computed-aggregate-results/{result['id']}/validation"
    )
    assert response.status_code == 200, response.text
    assert response.json()["current"] is False
    assert response.json()["reasons"] == [f"label_name_changed:{label_id}"]


def test_result_validation_rejects_tampered_result_checksum(client: TestClient) -> None:
    project = create_project(client, "Tampered aggregate")
    image_id = _import(client, project["id"], 13)
    label_id = str(project["label_classes"][0]["id"])
    _save(client, image_id, [label_id])
    definition = _definition(client, project["id"])
    result = _calculate(client, project["id"], definition["id"], [image_id]).json()
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        row = session.get(ComputedMetricResult, result["id"])
        row.payload_json = {**row.payload_json, "observation_count": 999}
        session.commit()

    response = client.get(
        f"/api/v1/projects/{project['id']}/computed-aggregate-results/{result['id']}/validation"
    )
    assert response.status_code == 409
    assert "checksum" in response.json()["detail"].lower()


def test_aggregate_csv_preserves_overall_group_class_and_sample_size_provenance(
    client: TestClient,
) -> None:
    project = create_project(client, "Aggregate CSV")
    first = _import(client, project["id"], 14)
    second = _import(client, project["id"], 15)
    labels = [str(item["id"]) for item in project["label_classes"][:2]]
    _save(client, first, [labels[0], labels[1]])
    _save(client, second, [labels[0]])
    for image_id in (first, second):
        response = client.patch(
            f"/api/v1/images/{image_id}",
            json={"annotation_status": "reviewed", "group_key": "colony-a"},
        )
        assert response.status_code == 200
    definition = _definition(client, project["id"], grouping_level="image_group_key")
    result = _calculate(client, project["id"], definition["id"], [first, second]).json()

    exported = client.get(f"/api/v1/projects/{project['id']}/computed-aggregate-results.csv")
    assert exported.status_code == 200, exported.text
    assert "text/csv" in exported.headers["content-type"]
    lines = exported.text.splitlines()
    assert len(lines) == 3
    assert "row_kind" in lines[0]
    assert "independent_unit_count" in lines[0]
    assert "independence_contract" in lines[0]
    assert "observation_ids_json" in lines[0]
    assert result["content_sha256"] in lines[1]
    assert result["evidence_sha256"] in lines[1]
    assert "overall" in lines[1]
    assert "colony-a" in lines[2]
    assert "one_unit_per_image_group_key" in lines[1]
    assert labels[0] in lines[1] and labels[1] in lines[1]
    assert first in lines[1] and second in lines[1]
