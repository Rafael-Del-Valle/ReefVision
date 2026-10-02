from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.inference as inference_module
from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.jobs.export import process_export_job
from reefvision.jobs.inference import process_inference_job
from reefvision.main import create_app
from reefvision.services.models import ModelService
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import create_version, save_annotations
from reefvision.tests.test_model_inference import (
    FakeDetectorRegistrationProvider,
    FakeDetectorWorkerProvider,
    register_model,
)


def _editable_annotation_drafts(session_payload: dict[str, object]) -> list[dict[str, object]]:
    annotations = cast(list[dict[str, object]], session_payload["annotations"])
    return [
        {
            "id": annotation["id"],
            "label_class_id": annotation["label_class_id"],
            "x_min": annotation["x_min"],
            "y_min": annotation["y_min"],
            "x_max": annotation["x_max"],
            "y_max": annotation["y_max"],
        }
        for annotation in annotations
    ]


def test_core_scientist_round_trip_preserves_raw_and_corrected_results(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ModelService,
        "_provider_for_purpose",
        lambda self, purpose: FakeDetectorRegistrationProvider(),
    )
    monkeypatch.setattr(
        inference_module,
        "detection_provider_for_name",
        lambda provider_name: FakeDetectorWorkerProvider(),
    )

    project = create_project(client, "Scientist-ready core round trip")
    report = import_one(
        client,
        project["id"],
        filename="core-round-trip.png",
        relative_path="core/core-round-trip.png",
        size=(80, 60),
    )
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]

    manual = save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="in_progress",
        annotations=[
            {
                "id": "0cbfb8d2-9308-47ef-a997-616c81cab15f",
                "label_class_id": label_class_id,
                "x_min": 10,
                "y_min": 5,
                "x_max": 30,
                "y_max": 25,
            }
        ],
    )
    assert manual["image"]["annotation_revision"] == 1

    model = register_model(
        client,
        project["id"],
        purpose="detector",
        filename="fixture-detector.pt",
        display_name="Fixture Detector",
    )
    job_response = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": model["id"], "image_ids": [image_id], "device": "cpu"},
    )
    assert job_response.status_code == 200, job_response.text
    job = job_response.json()

    app = cast(FastAPI, client.app)
    assert process_inference_job(
        app.state.settings,
        app.state.session_factory,
        job["id"],
    ) is True

    proposals_response = client.get(f"/api/v1/images/{image_id}/prediction-proposals")
    assert proposals_response.status_code == 200, proposals_response.text
    proposal = proposals_response.json()["items"][0]
    raw_machine_box = {
        "x_min": proposal["x_min"],
        "y_min": proposal["y_min"],
        "x_max": proposal["x_max"],
        "y_max": proposal["y_max"],
    }
    assert raw_machine_box == {
        "x_min": 5.0,
        "y_min": 4.0,
        "x_max": 32.0,
        "y_max": 28.0,
    }

    accepted_response = client.post(
        f"/api/v1/prediction-proposals/{proposal['id']}/accept",
        json={
            "label_class_id": label_class_id,
            "x_min": 6,
            "y_min": 5,
            "x_max": 31,
            "y_max": 27,
        },
    )
    assert accepted_response.status_code == 200, accepted_response.text
    accepted = accepted_response.json()
    assert accepted["proposal"]["review_status"] == "edited_and_accepted"
    assert accepted["proposal"]["was_edited"] is True
    assert accepted["annotation"]["source_type"] == "accepted_prediction"
    assert accepted["annotation"]["source_prediction_id"] == proposal["id"]
    assert accepted["annotation"]["provenance_json"]["original_predicted_box"] == (
        raw_machine_box
    )

    calibration_response = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.05,
            "unit": "cm",
            "source": "manual_scale_bar",
            "reference_length": 1.0,
            "reference_pixel_length": 20.0,
            "confidence": 1.0,
            "detector": "scientist-confirmed",
        },
    )
    assert calibration_response.status_code == 200, calibration_response.text

    current_session_response = client.get(f"/api/v1/images/{image_id}/annotations")
    assert current_session_response.status_code == 200, current_session_response.text
    current_session = current_session_response.json()
    reviewed = save_annotations(
        client,
        image_id,
        base_revision=current_session["image"]["annotation_revision"],
        annotation_status="reviewed",
        annotations=_editable_annotation_drafts(current_session),
    )
    assert reviewed["image"]["annotation_status"] == "reviewed"
    assert len(reviewed["annotations"]) == 2

    restart_app = create_app(test_settings)
    Base.metadata.create_all(restart_app.state.engine)
    try:
        with TestClient(restart_app) as reopened:
            reopened_session_response = reopened.get(
                f"/api/v1/images/{image_id}/annotations"
            )
            assert reopened_session_response.status_code == 200
            reopened_session = reopened_session_response.json()
            assert reopened_session["image"]["annotation_status"] == "reviewed"
            assert len(reopened_session["annotations"]) == 2

            corrected = next(
                annotation
                for annotation in reopened_session["annotations"]
                if annotation["source_prediction_id"] == proposal["id"]
            )
            assert corrected["source_type"] == "accepted_prediction"
            assert {
                "x_min": corrected["x_min"],
                "y_min": corrected["y_min"],
                "x_max": corrected["x_max"],
                "y_max": corrected["y_max"],
            } == {
                "x_min": 6.0,
                "y_min": 5.0,
                "x_max": 31.0,
                "y_max": 27.0,
            }
            assert corrected["provenance_json"]["original_predicted_box"] == (
                raw_machine_box
            )

            reopened_proposals = reopened.get(
                f"/api/v1/images/{image_id}/prediction-proposals"
            ).json()["items"]
            assert len(reopened_proposals) == 1
            assert reopened_proposals[0]["review_status"] == "edited_and_accepted"
            assert {
                "x_min": reopened_proposals[0]["x_min"],
                "y_min": reopened_proposals[0]["y_min"],
                "x_max": reopened_proposals[0]["x_max"],
                "y_max": reopened_proposals[0]["y_max"],
            } == raw_machine_box

            reopened_calibration = reopened.get(
                f"/api/v1/images/{image_id}/measurement-calibration"
            )
            assert reopened_calibration.status_code == 200
            assert reopened_calibration.json()["distance_per_pixel"] == pytest.approx(
                0.05
            )
            assert reopened_calibration.json()["unit"] == "cm"

            version = create_version(
                reopened,
                project["id"],
                name="Scientist-ready frozen snapshot",
            )
            export_response = reopened.post(
                f"/api/v1/dataset-versions/{version['id']}/exports",
                json={"format": "yolo_detection"},
            )
            assert export_response.status_code == 200, export_response.text
            export_payload = export_response.json()
            assert process_export_job(
                restart_app.state.settings,
                restart_app.state.session_factory,
                export_payload["job"]["id"],
            ) is True

            export_record = reopened.get(
                f"/api/v1/exports/{export_payload['export']['id']}"
            ).json()
            assert export_record["status"] == "succeeded"

            export_root = test_settings.resolved_data_dir / Path(
                export_record["output_path"]
            )
            label_file = next(export_root.glob("labels/*/*.txt"))
            label_lines = set(label_file.read_text(encoding="utf-8").splitlines())
            assert label_lines == {
                "0 0.25000000 0.25000000 0.25000000 0.33333333",
                "0 0.23125000 0.26666667 0.31250000 0.36666667",
            }

            manifest_path = test_settings.resolved_data_dir / Path(
                export_record["manifest_path"]
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest["dataset_version_id"] == version["id"]
            assert manifest["items"][0]["annotation_count"] == 2
    finally:
        restart_app.state.engine.dispose()
