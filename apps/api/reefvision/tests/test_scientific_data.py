from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project, import_one


def observation(**overrides):
    return {
        "variable": "water_temperature",
        "value": 68.0,
        "unit": "degF",
        "observed_at": "2026-04-03T08:00:00-05:00",
        "source_kind": "observed",
        "location": {"latitude": 32.75, "longitude": -79.93},
        "provenance": {
            "source": "laboratory sensor",
            "dataset_id": "feeding-trial-2026",
            "acquired_at": "2026-04-03T13:01:00Z",
        },
        **overrides,
    }


def test_records_preserve_original_units_utc_uncertainty_and_persist(client: TestClient):
    project = create_project(client)
    url = f"/api/v1/projects/{project['id']}/scientific-records"
    payload = observation(uncertainty={"value": 1.8, "kind": "standard_deviation"})
    response = client.post(url, json={"records": [payload]})
    assert response.status_code == 201, response.text
    item = response.json()["items"][0]
    assert item["value"] == 68
    assert item["unit"] == "degF"
    assert item["normalized_value"] == pytest.approx(20)
    assert item["normalized_unit"] == "degC"
    assert item["normalized_uncertainty"] == pytest.approx(1)
    assert item["observed_at"] == "2026-04-03T13:00:00Z"
    assert item["depth_m"] is None
    assert item["source_kind"] == "observed"
    assert len(item["content_sha256"]) == 64
    assert client.get(url).json()["items"] == [item]


@pytest.mark.parametrize(
    "patch",
    [
        {"observed_at": "2026-04-03T13:00:00"},
        {"unit": "fathoms"},
        {"value": "NaN"},
        {"location": {"latitude": 95, "longitude": 0}},
        {"location": {"latitude": 32, "longitude": 0, "crs": "EPSG:3857"}},
        {"depth_m": -1},
        {"source_kind": "guessed"},
        {"subject": {"frame_index": 1}},
        {"uncertainty": {"value": -1, "kind": "standard_deviation"}},
        {"provenance": {"source": " ", "acquired_at": "2026-04-03T13:00:00Z"}},
    ],
)
def test_invalid_scientific_values_are_rejected(client: TestClient, patch):
    project = create_project(client)
    response = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records",
        json={"records": [observation(**patch)]},
    )
    assert response.status_code == 422, response.text


def test_batch_rejects_cross_project_and_missing_ids_atomically(client: TestClient):
    project = create_project(client)
    other = create_project(client, "Other")
    image_id = import_one(client, other["id"])["successful"][0]["image_id"]
    url = f"/api/v1/projects/{project['id']}/scientific-records"
    for subject in ({"image_id": image_id}, {"model_run_id": str(uuid4())}):
        response = client.post(url, json={"records": [observation(), observation(subject=subject)]})
        assert response.status_code == 400, response.text
        assert client.get(url).json()["total"] == 0


def test_image_pixels_and_calibration_are_bound_to_original_image(client: TestClient):
    project = create_project(client)
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    calibration_url = f"/api/v1/images/{image_id}/measurement-calibration"
    assert (
        client.put(calibration_url, json={"distance_per_pixel": 0.1, "unit": "mm"}).status_code
        == 200
    )
    url = f"/api/v1/projects/{project['id']}/scientific-records"
    payload = observation(
        subject={"image_id": image_id}, pixel={"x": 40, "y": 30, "frame": "image_pixels"}
    )
    response = client.post(url, json={"records": [payload]})
    assert response.status_code == 201, response.text
    record = response.json()["items"][0]
    assert record["calibration_snapshot"]["distance_per_pixel"] == 0.1
    assert record["calibration_current"] is True
    assert (
        client.put(calibration_url, json={"distance_per_pixel": 0.2, "unit": "mm"}).status_code
        == 200
    )
    stored = client.get(url).json()["items"][0]
    assert stored["calibration_snapshot"] == record["calibration_snapshot"]
    assert stored["calibration_current"] is False
    invalid = deepcopy(payload)
    invalid["pixel"]["x"] = 81
    assert client.post(url, json={"records": [invalid]}).status_code == 400


def test_tampered_scientific_record_is_not_returned_as_valid(client: TestClient):
    from reefvision.db.models.scientific_record import ScientificRecord

    project = create_project(client)
    url = f"/api/v1/projects/{project['id']}/scientific-records"
    item = client.post(url, json={"records": [observation()]}).json()["items"][0]
    with client.app.state.session_factory() as session:
        row = session.get(ScientificRecord, item["id"])
        row.payload_json = {**row.payload_json, "value": 999}
        session.commit()
    assert client.get(url).status_code == 409


def test_exchange_selects_scientific_format_for_enriched_project(client: TestClient):
    project = create_project(client)
    url = f"/api/v1/projects/{project['id']}/scientific-records"
    assert client.post(url, json={"records": [observation()]}).status_code == 201
    response = client.post(f"/api/v1/projects/{project['id']}/exchange-packages", json={})
    assert response.status_code == 202, response.text
    assert response.json()["package"]["format_version"] == "1.1"


def test_scientific_lists_are_scoped_paginated_and_filterable(client: TestClient):
    project = create_project(client)
    url = f"/api/v1/projects/{project['id']}/scientific-records"
    assert (
        client.post(
            url, json={"records": [observation(), observation(source_kind="modeled")]}
        ).status_code
        == 201
    )
    page = client.get(url, params={"limit": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert client.get(url, params={"source_kind": "observed"}).json()["total"] == 1
    assert client.get(url, params={"offset": 1}).json()["items"][0]["id"] != page["items"][0]["id"]


def test_model_run_must_match_job_kind_media_and_object_lineage(client, monkeypatch):
    from sqlalchemy import select

    import reefvision.jobs.inference as inference_module
    from reefvision.db.models import Job, MaskAnnotation, PredictionProposal
    from reefvision.jobs.inference import process_inference_job
    from reefvision.services.models import ModelService
    from reefvision.tests.test_model_inference import (
        FakeDetectorRegistrationProvider,
        FakeDetectorWorkerProvider,
        register_model,
    )

    monkeypatch.setattr(
        ModelService, "_provider_for_purpose", lambda *_: FakeDetectorRegistrationProvider()
    )
    monkeypatch.setattr(
        inference_module, "detection_provider_for_name", lambda _: FakeDetectorWorkerProvider()
    )
    project = create_project(client)
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    model = register_model(
        client, project["id"], purpose="detector", filename="fixture.pt", display_name="Fixture"
    )
    run = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": model["id"], "image_ids": [image_id], "device": "cpu"},
    ).json()
    assert process_inference_job(
        client.app.state.settings, client.app.state.session_factory, run["id"]
    )
    with client.app.state.session_factory() as session:
        prediction = session.scalar(
            select(PredictionProposal).where(PredictionProposal.inference_job_id == run["id"])
        )
        prediction_id = prediction.id
        unrelated = Job(
            project_id=project["id"], job_type="inference", request_json={"image_ids": [image_id]}
        )
        export = Job(project_id=project["id"], job_type="export")
        foreign_media = Job(
            project_id=project["id"], job_type="inference", request_json={"image_ids": []}
        )
        mask = MaskAnnotation(image_id=image_id, provenance_json={"inference_job_id": run["id"]})
        human_mask = MaskAnnotation(image_id=image_id)
        session.add_all([unrelated, export, foreign_media, mask, human_mask])
        session.commit()
        unrelated_id, export_id, foreign_media_id, mask_id = (
            unrelated.id,
            export.id,
            foreign_media.id,
            mask.id,
        )
        human_mask_id = human_mask.id
    accepted = client.post(
        f"/api/v1/prediction-proposals/{prediction_id}/accept",
        json={"label_class_id": project["label_classes"][0]["id"]},
    )
    assert accepted.status_code == 200, accepted.text
    annotation_id = accepted.json()["annotation"]["id"]
    url = f"/api/v1/projects/{project['id']}/scientific-records"
    invalid_subjects = [
        {"image_id": image_id, "model_run_id": export_id},
        {"image_id": image_id, "model_run_id": foreign_media_id},
        {"image_id": image_id, "mask_id": human_mask_id, "model_run_id": unrelated_id},
        *[
            {"image_id": image_id, object_key: object_id, "model_run_id": unrelated_id}
            for object_key, object_id in (
                ("prediction_id", prediction_id),
                ("annotation_id", annotation_id),
                ("mask_id", mask_id),
            )
        ],
    ]
    for subject in invalid_subjects:
        response = client.post(url, json={"records": [observation(subject=subject)]})
        assert response.status_code == 400, (subject, response.text)
    assert client.get(url).json()["total"] == 0
    for object_key, object_id in (
        ("prediction_id", prediction_id),
        ("annotation_id", annotation_id),
        ("mask_id", mask_id),
    ):
        response = client.post(
            url,
            json={
                "records": [
                    observation(
                        subject={
                            "image_id": image_id,
                            object_key: object_id,
                            "model_run_id": run["id"],
                        }
                    )
                ]
            },
        )
        assert response.status_code == 201, response.text


def test_track_model_run_must_match_track_and_video(client, monkeypatch):
    from reefvision.db.models import Job, VideoTrack
    from reefvision.tests.test_video_track_exchange_phase6 import _track, _video

    project = create_project(client)
    video = _video(client, project["id"], monkeypatch, "survey.mp4")
    track = _track(client, video["id"], project["label_classes"][0]["id"])
    with client.app.state.session_factory() as session:
        run = Job(
            project_id=project["id"],
            job_type="video_tracking",
            request_json={"video_id": video["id"]},
        )
        unrelated = Job(
            project_id=project["id"],
            job_type="video_tracking",
            request_json={"video_id": video["id"]},
        )
        foreign_media = Job(
            project_id=project["id"],
            job_type="video_tracking",
            request_json={"video_id": str(uuid4())},
        )
        session.add_all([run, unrelated, foreign_media])
        session.flush()
        session.get(VideoTrack, track["id"]).source_job_id = run.id
        session.commit()
        run_id, unrelated_id, foreign_media_id = run.id, unrelated.id, foreign_media.id
    url = f"/api/v1/projects/{project['id']}/scientific-records"
    for subject in (
        {"video_id": video["id"], "track_id": track["id"], "model_run_id": unrelated_id},
        {"video_id": video["id"], "model_run_id": foreign_media_id},
    ):
        response = client.post(url, json={"records": [observation(subject=subject)]})
        assert response.status_code == 400, response.text
    response = client.post(
        url,
        json={
            "records": [
                observation(
                    subject={
                        "video_id": video["id"],
                        "track_id": track["id"],
                        "model_run_id": run_id,
                    }
                )
            ]
        },
    )
    assert response.status_code == 201, response.text
