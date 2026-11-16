"""Offline lunar phase: scientific boundaries and stable API provenance."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project

NEW_MOON = "2024-04-08T18:20:00Z"
FULL_MOON = "2024-03-25T07:00:00Z"


def _endpoint(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/environment/lunar-context"


@pytest.mark.parametrize(
    ("timestamp", "phase", "fraction_limit"),
    [
        (NEW_MOON, "new_moon", 0.08),
        (FULL_MOON, "full_moon", 0.15),
    ],
)
def test_known_phase_reference_windows(
    client: TestClient, timestamp: str, phase: str, fraction_limit: float
) -> None:
    project = create_project(client, "Lunar study")
    response = client.post(_endpoint(project["id"]), json={"observed_at": timestamp})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["phase"] == phase
    assert data["reference_frame"] == "geocentric_approximate"
    assert data["computation"] == "offline_deterministic"
    assert 0 <= data["illuminated_fraction"] <= 1
    assert len(data["content_sha256"]) == 64
    if phase == "new_moon":
        assert data["illuminated_fraction"] < fraction_limit
    else:
        assert data["illuminated_fraction"] > 1 - fraction_limit


def test_equivalent_utc_instants_are_identical_and_repeatable(client: TestClient) -> None:
    project = create_project(client, "Timezone study")
    url = _endpoint(project["id"])
    utc = client.post(url, json={"observed_at": NEW_MOON})
    offset = client.post(url, json={"observed_at": "2024-04-08T14:20:00-04:00"})
    repeated = client.post(url, json={"observed_at": NEW_MOON})
    assert utc.status_code == offset.status_code == repeated.status_code == 200
    assert utc.json() == offset.json() == repeated.json()
    assert utc.json()["observed_at"].endswith("Z")
    records = client.get(f"/api/v1/projects/{project['id']}/scientific-records")
    assert records.status_code == 200
    assert records.json()["total"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"observed_at": "2024-04-08T18:20:00"},
        {"observed_at": "2024-02-30T18:20:00Z"},
        {"observed_at": "1899-01-01T00:00:00Z"},
        {"observed_at": "2101-01-01T00:00:00Z"},
        {"observed_at": NEW_MOON, "assumed_location": "Charleston"},
        {},
    ],
)
def test_ambiguous_unsupported_or_unrequested_inputs_rejected(
    client: TestClient, payload: dict[str, str]
) -> None:
    project = create_project(client)
    response = client.post(_endpoint(project["id"]), json=payload)
    assert response.status_code == 422, response.text


def test_no_cross_project_or_missing_project_context(client: TestClient) -> None:
    project = create_project(client)
    url = _endpoint(project["id"])
    assert client.post(url, json={"observed_at": NEW_MOON}).status_code == 200
    assert client.post(_endpoint(str(uuid4())), json={"observed_at": NEW_MOON}).status_code == 404
