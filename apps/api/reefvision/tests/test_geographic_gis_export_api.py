"""Task 18C: registered read-only GIS download endpoint tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from reefvision.api.routes import georeferenced_observations as routes
from reefvision.domain.errors import NotFoundError
from reefvision.services.geographic_gis_export import GeographicGISExportError


class FakeObservationService:
    records: ClassVar[list[object]] = []
    error: ClassVar[Exception | None] = None
    calls: ClassVar[list[tuple[str, str | None]]] = []

    def __init__(self, session: object) -> None:
        self.session = session

    def list_for_video(
        self,
        video_id: str,
        *,
        track_id: str | None = None,
        frame_index: int | None = None,
    ) -> list[object]:
        self.calls.append((video_id, track_id))

        if self.error is not None:
            raise self.error

        return self.records

    def to_response(self, record: object) -> object:
        return record


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch) -> type[FakeObservationService]:
    FakeObservationService.records = []
    FakeObservationService.error = None
    FakeObservationService.calls = []

    monkeypatch.setattr(
        routes,
        "GeoReferencedObservationService",
        FakeObservationService,
    )

    monkeypatch.setattr(
        routes,
        "build_geographic_export_enrichments",
        lambda _session, _observations: {},
    )

    return FakeObservationService


def test_geojson_download_uses_persisted_observations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: type[FakeObservationService],
) -> None:
    record = SimpleNamespace(is_stale=False)
    fake_service.records = [record]

    serializer = Mock(return_value=b'{"type":"FeatureCollection","features":[]}')
    monkeypatch.setattr(routes, "geojson_bytes", serializer)

    response = client.get("/api/v1/videos/video-1/geographic-export?format=geojson")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/geo+json")
    assert response.headers["content-disposition"] == (
        'attachment; filename="reefvision-geographic-observations.geojson"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["type"] == "FeatureCollection"

    serializer.assert_called_once_with([record], {})
    assert fake_service.calls == [("video-1", None)]


def test_csv_download_forwards_track_filter(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: type[FakeObservationService],
) -> None:
    serializer = Mock(return_value=b"observation_id,longitude_deg\r\n")
    monkeypatch.setattr(routes, "csv_bytes", serializer)

    response = client.get(
        "/api/v1/videos/video-1/geographic-export",
        params={"format": "csv", "track_id": "track-1"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].endswith('observations.csv"')
    assert response.content.startswith(b"observation_id")
    assert fake_service.calls == [("video-1", "track-1")]
    serializer.assert_called_once_with([], {})


def test_empty_geojson_export_is_valid(
    client: TestClient,
    fake_service: type[FakeObservationService],
) -> None:
    response = client.get("/api/v1/videos/video-1/geographic-export")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "type": "FeatureCollection",
        "features": [],
    }


def test_missing_video_returns_404(
    client: TestClient,
    fake_service: type[FakeObservationService],
) -> None:
    fake_service.error = NotFoundError("Video not found")

    response = client.get("/api/v1/videos/missing/geographic-export")

    assert response.status_code == 404


def test_invalid_format_is_rejected(
    client: TestClient,
    fake_service: type[FakeObservationService],
) -> None:
    response = client.get("/api/v1/videos/video-1/geographic-export?format=kml")

    assert response.status_code == 422
    assert fake_service.calls == []


def test_invalid_export_is_not_returned_as_download(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: type[FakeObservationService],
) -> None:
    def reject(
        _items: object,
        _enrichments: object,
    ) -> bytes:
        raise GeographicGISExportError("Invalid persisted coordinates")

    monkeypatch.setattr(routes, "geojson_bytes", reject)

    response = client.get("/api/v1/videos/video-1/geographic-export")

    assert response.status_code == 400
    assert "Invalid persisted coordinates" in response.text
