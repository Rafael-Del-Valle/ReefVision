from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from reefvision.api.dependencies import get_db_session
from reefvision.api.routes.geographic_movement_analytics import router
from reefvision.domain.errors import (
    NotFoundError,
    ValidationError,
)
from reefvision.services.georeferenced_observations import (
    GeoReferencedObservationService,
)


class FakeSession:
    def __init__(
        self,
        *,
        track: object | None,
    ) -> None:
        self.track = track

    def get(
        self,
        _model: object,
        _identifier: object,
    ) -> object | None:
        return self.track


def persisted_observation(
    observation_id: str,
    *,
    frame_index: int,
    frame_time_s: float,
    latitude_deg: float,
    longitude_deg: float,
    crs: str = "EPSG:4326",
    is_stale: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=observation_id,
        track_id="track-1",
        video_id="video-1",
        frame_index=frame_index,
        frame_time_s=frame_time_s,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        crs=crs,
        is_stale=is_stale,
    )


def build_test_app(
    session: FakeSession,
) -> FastAPI:
    app = FastAPI()

    def override_session() -> Generator[
        FakeSession,
        None,
        None,
    ]:
        yield session

    app.dependency_overrides[get_db_session] = override_session

    @app.exception_handler(NotFoundError)
    async def handle_not_found(
        _request: Request,
        exc: NotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "detail": str(exc),
            },
        )

    @app.exception_handler(ValidationError)
    async def handle_validation(
        _request: Request,
        exc: ValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "detail": str(exc),
            },
        )

    app.include_router(
        router,
        prefix="/api/v1",
    )

    return app


@pytest.fixture
def track() -> SimpleNamespace:
    return SimpleNamespace(
        id="track-1",
        video_id="video-1",
        deleted_at=None,
    )


def test_geographic_analytics_success(
    track: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = [
        persisted_observation(
            "observation-2",
            frame_index=20,
            frame_time_s=3.0,
            latitude_deg=32.7501,
            longitude_deg=-79.9299,
        ),
        persisted_observation(
            "observation-1",
            frame_index=10,
            frame_time_s=1.0,
            latitude_deg=32.75,
            longitude_deg=-79.93,
        ),
    ]

    def list_for_track(
        _self: GeoReferencedObservationService,
        track_id: str,
    ) -> list[object]:
        assert track_id == "track-1"
        return observations

    monkeypatch.setattr(
        GeoReferencedObservationService,
        "list_for_track",
        list_for_track,
    )

    session = FakeSession(track=track)

    with TestClient(build_test_app(session)) as client:
        response = client.get("/api/v1/video-tracks/track-1/geographic-analytics")

    assert response.status_code == 200

    payload = response.json()

    assert payload["track_id"] == "track-1"
    assert payload["video_asset_id"] == "video-1"
    assert payload["observation_count"] == 2
    assert payload["segment_count"] == 1
    assert payload["first_frame_index"] == 10
    assert payload["last_frame_index"] == 20
    assert payload["first_frame_time_s"] == 1.0
    assert payload["last_frame_time_s"] == 3.0
    assert payload["elapsed_time_s"] == 2.0
    assert payload["total_distance_m"] > 0.0
    assert payload["net_displacement_m"] > 0.0
    assert payload["mean_speed_m_s"] > 0.0
    assert len(payload["segments"]) == 1

    segment = payload["segments"][0]

    assert segment["start_observation_id"] == "observation-1"
    assert segment["end_observation_id"] == "observation-2"


def test_geographic_analytics_empty_observations(
    track: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GeoReferencedObservationService,
        "list_for_track",
        lambda _self, _track_id: [],
    )

    session = FakeSession(track=track)

    with TestClient(build_test_app(session)) as client:
        response = client.get("/api/v1/video-tracks/track-1/geographic-analytics")

    assert response.status_code == 200

    payload = response.json()

    assert payload["track_id"] == "track-1"
    assert payload["video_asset_id"] == "video-1"
    assert payload["observation_count"] == 0
    assert payload["segment_count"] == 0
    assert payload["total_distance_m"] == 0.0
    assert payload["net_displacement_m"] == 0.0
    assert payload["mean_speed_m_s"] is None
    assert payload["max_segment_speed_m_s"] is None
    assert payload["segments"] == []


@pytest.mark.parametrize("all_stale", [False, True], ids=["mixed-fresh", "all-stale"])
def test_geographic_analytics_excludes_stale_observations(
    track: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    all_stale: bool,
) -> None:
    observations = [
        persisted_observation(
            "fresh-start",
            frame_index=0,
            frame_time_s=0.0,
            latitude_deg=0.0,
            longitude_deg=0.0,
            is_stale=all_stale,
        ),
        persisted_observation(
            "stale-outlier",
            frame_index=10,
            frame_time_s=1.0,
            latitude_deg=20.0,
            longitude_deg=20.0,
            is_stale=True,
        ),
        persisted_observation(
            "fresh-end",
            frame_index=20,
            frame_time_s=2.0,
            latitude_deg=0.0,
            longitude_deg=0.001,
            is_stale=all_stale,
        ),
    ]
    monkeypatch.setattr(
        GeoReferencedObservationService,
        "list_for_track",
        lambda _self, _track_id: observations,
    )

    with TestClient(build_test_app(FakeSession(track=track))) as client:
        response = client.get("/api/v1/video-tracks/track-1/geographic-analytics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["observation_count"] == (0 if all_stale else 2)
    if all_stale:
        assert payload["segments"] == []
        assert payload["mean_speed_m_s"] is None
        assert payload["total_distance_m"] == 0.0
    else:
        assert payload["total_distance_m"] == pytest.approx(111.319490793, abs=1e-5)
        assert payload["mean_speed_m_s"] == pytest.approx(55.6597453965, abs=1e-5)
        assert payload["segments"][0]["start_observation_id"] == "fresh-start"
        assert payload["segments"][0]["end_observation_id"] == "fresh-end"
        assert payload["segments"][0]["initial_bearing_deg"] == pytest.approx(90.0)


def test_geographic_analytics_missing_track_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_list(
        _self: GeoReferencedObservationService,
        _track_id: str,
    ) -> list[object]:
        raise AssertionError("Persistence lookup must not run for a missing track.")

    monkeypatch.setattr(
        GeoReferencedObservationService,
        "list_for_track",
        unexpected_list,
    )

    session = FakeSession(track=None)

    with TestClient(build_test_app(session)) as client:
        response = client.get("/api/v1/video-tracks/missing/geographic-analytics")

    assert response.status_code == 404
    assert response.json() == {"detail": "Video track not found"}


def test_geographic_analytics_validation_error_returns_400(
    track: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = [
        persisted_observation(
            "observation-1",
            frame_index=10,
            frame_time_s=1.0,
            latitude_deg=32.75,
            longitude_deg=-79.93,
            crs="EPSG:3857",
        ),
        persisted_observation(
            "observation-2",
            frame_index=20,
            frame_time_s=2.0,
            latitude_deg=32.7501,
            longitude_deg=-79.9299,
            crs="EPSG:3857",
        ),
    ]

    monkeypatch.setattr(
        GeoReferencedObservationService,
        "list_for_track",
        lambda _self, _track_id: observations,
    )

    session = FakeSession(track=track)

    with TestClient(build_test_app(session)) as client:
        response = client.get("/api/v1/video-tracks/track-1/geographic-analytics")

    assert response.status_code == 400

    detail = response.json()["detail"]

    assert "EPSG:4326" in detail
    assert "EPSG:3857" in detail


def test_geographic_analytics_route_is_registered_on_full_app() -> None:
    from reefvision.main import app

    expected_path = "/api/v1/video-tracks/{track_id}/geographic-analytics"

    openapi = app.openapi()

    assert expected_path in openapi["paths"]
    assert "get" in openapi["paths"][expected_path]

    def override_session() -> Generator[
        FakeSession,
        None,
        None,
    ]:
        yield FakeSession(track=None)

    app.dependency_overrides[get_db_session] = override_session

    client = TestClient(app)

    try:
        response = client.get("/api/v1/video-tracks/missing/geographic-analytics")
    finally:
        client.close()

        app.dependency_overrides.pop(
            get_db_session,
            None,
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Video track not found"}
