from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ClassificationCrop
from reefvision.jobs.export import process_export_job
from reefvision.tests.test_classification_phase5 import _seed_classification_project
from reefvision.tests.test_dataset_versions import create_version


def test_classification_export_registers_crops_for_qa(client: TestClient) -> None:
    project, _image_id, _class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    version = create_version(client, project_id, name="QA crop export")

    created = client.post(
        f"/api/v1/dataset-versions/{version['id']}/exports",
        json={
            "format": "classification_binary_state",
            "minimum_crop_size_px": 10,
            "padding_fraction": 0,
        },
    )
    assert created.status_code == 200, created.text
    export = created.json()["export"]
    job = created.json()["job"]
    app = cast(FastAPI, client.app)

    assert process_export_job(
        app.state.settings,
        app.state.session_factory,
        job["id"],
    )

    with app.state.session_factory() as session:
        crops = list(
            session.scalars(
                select(ClassificationCrop)
                .where(ClassificationCrop.export_id == export["id"])
                .order_by(ClassificationCrop.label_class_id, ClassificationCrop.id)
            )
        )
        crop_ids = [crop.id for crop in crops]
        assert len(crops) == 2
        assert all(
            (app.state.settings.resolved_data_dir / crop.managed_path).is_file()
            for crop in crops
        )

    response = client.post(
        f"/api/v1/projects/{project_id}/classification-crops/qa",
        json={
            "crop_ids": crop_ids,
            "minimum_width_px": 10,
            "minimum_height_px": 10,
            "minimum_area_px": 100,
            "maximum_aspect_ratio": 10,
            "minimum_brightness": 0,
            "maximum_brightness": 255,
            "minimum_contrast_std": 0,
            "minimum_sharpness": 0,
            "maximum_dark_fraction": 1,
            "maximum_bright_fraction": 1,
            "duplicate_policy": "warning",
            "persist_report": False,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["crop_count"] == 2
    assert payload["valid_crop_count"] == 2
    assert payload["error_count"] == 0
    assert len(payload["input_checksum"]) == 64
    assert len(payload["report_checksum"]) == 64
