"""Task 19F georeferenced-observation recomputation API."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from reefvision.api.routes import (
    georeferenced_observations as routes,
)
from reefvision.schemas.georeferenced_observation_api import (
    GeoReferencedObservationRecomputeResponse,
)


def test_recompute_route_is_registered_as_post() -> None:
    path = "/videos/{video_id}/georeferenced-observations/recompute"

    matches = [route for route in routes.router.routes if getattr(route, "path", None) == path]

    assert len(matches) == 1
    assert "POST" in matches[0].methods


def test_recompute_route_uses_request_settings_and_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_id = str(uuid4())
    settings = object()
    session = object()

    captured: dict[str, object] = {}

    class FakeService:
        def __init__(
            self,
            supplied_session: object,
            supplied_settings: object,
        ) -> None:
            captured["session"] = supplied_session
            captured["settings"] = supplied_settings

        def recompute_video(
            self,
            supplied_video_id: str,
        ) -> GeoReferencedObservationRecomputeResponse:
            captured["video_id"] = supplied_video_id

            return GeoReferencedObservationRecomputeResponse(
                video_id=supplied_video_id,
                configuration_hash="a" * 64,
                invalidated_count=2,
                stale_count=2,
                recomputed_count=2,
                unchanged_count=1,
                replacements=[],
            )

    monkeypatch.setattr(
        routes,
        "GeoreferencedObservationRecomputationService",
        FakeService,
    )

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))

    response = routes.recompute_video_georeferenced_observations(
        video_id,
        request,  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )

    assert captured == {
        "session": session,
        "settings": settings,
        "video_id": video_id,
    }

    assert response.recomputed_count == 2
    assert response.invalidated_count == 2
