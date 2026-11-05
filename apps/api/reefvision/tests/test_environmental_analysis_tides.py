"""NOAA tidal samples remain records while composite context remains an analysis."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import ScientificRecord
from reefvision.domain.errors import ValidationError
from reefvision.schemas.environmental_context import NOAATideImportRequest
from reefvision.services.environmental_context import EnvironmentalContextService
from reefvision.tests.test_annotations import create_project


def prediction_fixture() -> dict:
    return {
        "metadata": {
            "id": "8665530",
            "name": "Synthetic Charleston",
            "lat": "32.7808",
            "lon": "-79.9236",
        },
        "predictions": [
            {"t": "2026-04-03 12:54", "v": "0.50"},
            {"t": "2026-04-03 13:00", "v": "0.55"},
            {"t": "2026-04-03 13:06", "v": "0.62"},
        ],
    }


def observation_fixture() -> dict:
    return {
        "metadata": {
            "id": "8665530",
            "name": "Synthetic Charleston",
            "lat": "32.7808",
            "lon": "-79.9236",
        },
        "data": [
            {
                "t": "2026-04-03 13:00",
                "v": "0.58",
                "s": "0.02",
                "f": "0,0,0,0",
                "q": "v",
            }
        ],
    }


def _import_tides(
    client: TestClient, project_id: str
) -> tuple[object, object, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.params["datum"] == "MLLW"
        assert request.url.params["time_zone"] == "gmt"
        assert request.url.params["units"] == "metric"
        product = request.url.params["product"]
        return httpx.Response(
            200,
            json=prediction_fixture() if product == "predictions" else observation_fixture(),
        )

    now = datetime(2026, 4, 4, tzinfo=UTC)
    with (
        client.app.state.session_factory() as session,
        httpx.Client(transport=httpx.MockTransport(transport)) as http,
    ):
        service = EnvironmentalContextService(session, http=http, now=now)
        predicted = service.import_noaa_tides(
            project_id,
            NOAATideImportRequest(
                station_id="8665530",
                day="2026-04-03",
                product="predictions",
                datum="MLLW",
            ),
        )
        observed = service.import_noaa_tides(
            project_id,
            NOAATideImportRequest(
                station_id="8665530",
                day="2026-04-03",
                product="water_level",
                datum="MLLW",
            ),
        )
    return predicted, observed, calls


def test_noaa_predictions_and_observations_are_distinct_cached_records(
    client: TestClient,
) -> None:
    project = create_project(client, "NOAA tide records")
    predicted, observed, calls = _import_tides(client, project["id"])
    assert len(calls) == 2
    assert {item.variable for item in predicted.items} == {"predicted_water_level"}
    assert {item.source_kind for item in predicted.items} == {"modeled"}
    assert {item.variable for item in observed.items} == {"observed_water_level"}
    assert {item.source_kind for item in observed.items} == {"observed"}
    assert observed.items[0].uncertainty is not None
    assert observed.items[0].uncertainty.value == pytest.approx(0.02)
    for item in [*predicted.items, *observed.items]:
        metadata = item.provenance.source_metadata
        assert metadata["station"]["id"] == "8665530"
        assert metadata["datum"] == "MLLW"
        assert metadata["product"] in {"predictions", "water_level"}

    with client.app.state.session_factory() as session:
        offline = EnvironmentalContextService(
            session, now=datetime(2026, 4, 6, tzinfo=UTC)
        ).import_noaa_tides(
            project["id"],
            NOAATideImportRequest(
                station_id="8665530",
                day="2026-04-03",
                product="predictions",
                datum="MLLW",
                offline=True,
            ),
        )
    assert offline.cache_status == "stale_offline"
    assert [item.id for item in offline.items] == [item.id for item in predicted.items]


def test_tidal_context_keeps_observed_and_predicted_evidence_separate(
    client: TestClient,
) -> None:
    project = create_project(client, "Tidal context")
    predicted, observed, _ = _import_tides(client, project["id"])
    response = client.post(
        f"/api/v1/projects/{project['id']}/environment/analyses/tidal-context",
        json={
            "name": "Charleston context",
            "observed_at": "2026-04-03T13:00:00Z",
            "location": {"latitude": 32.7808, "longitude": -79.9236},
            "station_id": "8665530",
            "datum": "MLLW",
            "max_time_delta_s": 900,
            "max_distance_m": 1000,
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["definition"]["analysis_kind"] == "tidal_context"
    result = data["result"]
    assert result["payload"]["observed"]["record_id"] == str(observed.items[0].id)
    assert result["payload"]["observed"]["evidence_kind"] == "observed"
    assert result["payload"]["predicted"]["record_id"] == str(predicted.items[1].id)
    assert result["payload"]["predicted"]["evidence_kind"] == "predicted"
    assert result["payload"]["predicted_stage"] == "rising_predicted"
    assert result["payload"]["station"]["datum"] == "MLLW"
    assert result["payload"]["station"]["distance_m"] == pytest.approx(0)
    assert set(result["source_record_ids"]) == {
        str(item.id) for item in [*predicted.items, *observed.items]
    }
    assert "causal" not in result["payload"]["methodological_notes"][0].lower()


def test_environmental_analysis_currentness_detects_corrupt_source_evidence(
    client: TestClient,
) -> None:
    project = create_project(client, "Tidal currentness")
    _import_tides(client, project["id"])
    response = client.post(
        f"/api/v1/projects/{project['id']}/environment/analyses/tidal-context",
        json={
            "name": "Current Charleston context",
            "observed_at": "2026-04-03T13:00:00Z",
            "location": {"latitude": 32.7808, "longitude": -79.9236},
            "station_id": "8665530",
            "datum": "MLLW",
            "max_time_delta_s": 900,
            "max_distance_m": 1000,
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()["result"]
    validation_url = (
        f"/api/v1/projects/{project['id']}/environment/analyses/results/{result['id']}/validation"
    )
    current = client.get(validation_url)
    assert current.status_code == 200, current.text
    assert current.json() == {
        "result_id": result["id"],
        "current": True,
        "result_sha256": result["content_sha256"],
        "reasons": [],
    }

    source_id = result["source_record_ids"][0]
    with client.app.state.session_factory() as session:
        source = session.get(ScientificRecord, source_id)
        assert source is not None
        source.payload_json = {**source.payload_json, "unit": "tampered"}
        session.commit()

    stale = client.get(validation_url)
    assert stale.status_code == 200, stale.text
    assert stale.json()["current"] is False
    assert stale.json()["reasons"] == [f"source_record_invalid:{source_id}"]


def test_tidal_context_enforces_station_datum_time_and_distance(client: TestClient) -> None:
    project = create_project(client, "Bounded tidal context")
    _import_tides(client, project["id"])
    base = f"/api/v1/projects/{project['id']}/environment/analyses/tidal-context"
    request = {
        "name": "Invalid match",
        "observed_at": "2026-04-03T13:00:00Z",
        "location": {"latitude": 32.7808, "longitude": -79.9236},
        "station_id": "8665530",
        "datum": "MLLW",
        "max_time_delta_s": 60,
        "max_distance_m": 1000,
    }
    wrong_station = client.post(base, json={**request, "station_id": "8724580"})
    assert wrong_station.status_code == 400, wrong_station.text
    wrong_datum = client.post(base, json={**request, "datum": "MSL"})
    assert wrong_datum.status_code == 400, wrong_datum.text
    far = client.post(
        base,
        json={**request, "location": {"latitude": 0, "longitude": 0}, "max_distance_m": 10},
    )
    assert far.status_code == 400, far.text
    late = client.post(
        base,
        json={**request, "observed_at": "2026-04-04T13:00:00Z"},
    )
    assert late.status_code == 400, late.text


@pytest.mark.parametrize(
    "raw",
    [
        {"error": {"message": "No data was found"}},
        {**prediction_fixture(), "metadata": {**prediction_fixture()["metadata"], "id": "0"}},
        {**prediction_fixture(), "predictions": []},
        {**prediction_fixture(), "predictions": [{"t": "2026-04-03 13:00", "v": "NaN"}]},
    ],
)
def test_noaa_tide_provider_errors_never_create_records(client: TestClient, raw: dict) -> None:
    project = create_project(client, "Invalid NOAA tides")
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
        ) as http,
        pytest.raises(ValidationError),
    ):
        EnvironmentalContextService(session, http=http).import_noaa_tides(
            project["id"],
            NOAATideImportRequest(
                station_id="8665530",
                day="2026-04-03",
                product="predictions",
                datum="MLLW",
            ),
        )
    records = client.get(f"/api/v1/projects/{project['id']}/scientific-records")
    assert records.json()["total"] == 0


def test_noaa_tide_expired_refresh_failure_preserves_offline_cache(client: TestClient) -> None:
    project = create_project(client, "NOAA tide refresh")
    predicted, _, _ = _import_tides(client, project["id"])
    request = NOAATideImportRequest(
        station_id="8665530",
        day="2026-04-03",
        product="predictions",
        datum="MLLW",
    )
    with (
        client.app.state.session_factory() as session,
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as http,
    ):
        service = EnvironmentalContextService(
            session, http=http, now=datetime(2026, 4, 6, tzinfo=UTC)
        )
        with pytest.raises(ValidationError):
            service.import_noaa_tides(project["id"], request)
        cached = service.import_noaa_tides(
            project["id"], request.model_copy(update={"offline": True})
        )
    assert cached.cache_status == "stale_offline"
    assert cached.items[0].id == predicted.items[0].id
