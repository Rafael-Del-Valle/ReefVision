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


def test_exchange_refuses_to_silently_drop_scientific_records(client: TestClient):
    project = create_project(client)
    url = f"/api/v1/projects/{project['id']}/scientific-records"
    assert client.post(url, json={"records": [observation()]}).status_code == 201
    response = client.post(f"/api/v1/projects/{project['id']}/exchange-packages", json={})
    assert response.status_code == 400, response.text
    assert "scientific" in response.json()["detail"].lower()


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
