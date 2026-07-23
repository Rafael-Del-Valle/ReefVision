from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import (
    ClassificationAssignment,
    ClassificationLabelSet,
    ImageAsset,
    MaskAnnotation,
)
from reefvision.tests.test_annotations import create_project, import_one


def _project_classes(client: TestClient, project_id: str) -> list[dict[str, object]]:
    response = client.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 200, response.text
    return response.json()["label_classes"]


def test_whole_image_snapshot_freezes_group_safe_multilabel_targets(
    client: TestClient,
) -> None:
    project = create_project(client, "Whole image dataset")
    project_id = str(project["id"])
    first = import_one(
        client,
        project_id,
        filename="first.png",
        relative_path="a/first.png",
    )
    second = import_one(
        client,
        project_id,
        filename="second.png",
        relative_path="a/second.png",
    )
    image_ids = [
        str(first["successful"][0]["image_id"]),
        str(second["successful"][0]["image_id"]),
    ]
    classes = _project_classes(client, project_id)
    class_ids = sorted([str(classes[0]["id"]), str(classes[1]["id"])])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        for image_id in image_ids:
            image = session.get(ImageAsset, image_id)
            assert image is not None
            image.group_key = "same-fragment"
        label_set = ClassificationLabelSet(
            project_id=project_id,
            key="whole-image-tags",
            name="Whole image tags",
            target_kind="image",
            cardinality="multi",
            allowed_class_ids_json=class_ids,
        )
        session.add(label_set)
        session.flush()
        for image_id in image_ids:
            for class_id in class_ids:
                session.add(
                    ClassificationAssignment(
                        project_id=project_id,
                        label_set_id=label_set.id,
                        target_kind="image",
                        target_key=f"image:{image_id}",
                        image_id=image_id,
                        label_class_id=class_id,
                        source_type="manual",
                        status="accepted",
                    )
                )
        session.commit()
        label_set_id = label_set.id

    created = client.post(
        f"/api/v1/projects/{project_id}/classification-dataset-snapshots",
        json={
            "name": "Whole image immutable v1",
            "label_set_id": label_set_id,
            "split_seed": 7,
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["snapshot"]["target_kind"] == "image"
    assert payload["snapshot"]["cardinality"] == "multi"
    assert payload["snapshot"]["sample_count"] == 2
    assert len({item["split"] for item in payload["samples"]}) == 1
    assert all(
        item["label_class_ids_json"] == class_ids for item in payload["samples"]
    )
    assert all(item["target_checksum"] for item in payload["samples"])
    assert payload["snapshot"]["manifest_sha256"]

    listed = client.get(
        f"/api/v1/projects/{project_id}/classification-dataset-snapshots"
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [payload["snapshot"]["id"]]


def test_fragment_snapshot_freezes_verified_mask_revision_and_geometry(
    client: TestClient,
) -> None:
    project = create_project(client, "Fragment dataset")
    project_id = str(project["id"])
    imported = import_one(client, project_id)
    image_id = str(imported["successful"][0]["image_id"])
    class_id = str(_project_classes(client, project_id)[0]["id"])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = MaskAnnotation(
            image_id=image_id,
            label_class_id=class_id,
            geometry_kind="polygon",
            polygon_json=[[10, 10], [50, 10], [50, 40], [10, 40]],
            x_min=10,
            y_min=10,
            x_max=50,
            y_max=40,
            area_pixels=1200,
            measurement_json={"centerline_points": [], "surface_model": "none"},
            source_type="human",
            provenance_json={"fragment_key": "fragment-1"},
            status="verified",
            revision=3,
        )
        label_set = ClassificationLabelSet(
            project_id=project_id,
            key="fragment-health",
            name="Fragment health",
            target_kind="fragment",
            cardinality="single",
            allowed_class_ids_json=[class_id],
        )
        session.add_all([mask, label_set])
        session.flush()
        session.add(
            ClassificationAssignment(
                project_id=project_id,
                label_set_id=label_set.id,
                target_kind="fragment",
                target_key="fragment:fragment-1",
                image_id=image_id,
                mask_annotation_id=mask.id,
                fragment_key="fragment-1",
                label_class_id=class_id,
                source_type="manual",
                status="accepted",
            )
        )
        session.commit()
        label_set_id = label_set.id
        mask_id = mask.id

    created = client.post(
        f"/api/v1/projects/{project_id}/classification-dataset-snapshots",
        json={"name": "Fragment immutable v1", "label_set_id": label_set_id},
    )
    assert created.status_code == 201, created.text
    sample = created.json()["samples"][0]
    assert sample["target_kind"] == "fragment"
    assert sample["mask_annotation_id"] == mask_id
    assert sample["fragment_key"] == "fragment-1"
    assert sample["target_revision"] == 3
    assert sample["geometry_json"]["polygon_json"] == [
        [10, 10],
        [50, 10],
        [50, 40],
        [10, 40],
    ]
    assert len(sample["target_checksum"]) == 64
    assert len(sample["sample_sha256"]) == 64
