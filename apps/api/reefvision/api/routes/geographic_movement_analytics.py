"""Geographic movement analytics API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.geographic_movement_analytics import (
    GeographicTrackAnalytics,
)
from reefvision.services.geographic_movement_analytics import (
    GeographicMovementAnalyticsError,
)
from reefvision.services.geographic_movement_analytics_persistence import (
    PersistedObservationMappingError,
    calculate_persisted_track_summary,
)
from reefvision.services.georeferenced_observations import (
    GeoReferencedObservationService,
)

router = APIRouter()

DbSession = Annotated[
    Session,
    Depends(get_db_session),
]


@router.get(
    "/video-tracks/{track_id}/geographic-analytics",
    response_model=GeographicTrackAnalytics,
)
def geographic_track_analytics(
    track_id: str,
    session: DbSession,
) -> GeographicTrackAnalytics:
    """Return geographic movement analytics from persisted observations."""

    track = session.get(
        VideoTrack,
        track_id,
    )

    if track is None or track.deleted_at is not None:
        raise NotFoundError("Video track not found")

    persisted_observations = GeoReferencedObservationService(session).list_for_track(track_id)

    try:
        return calculate_persisted_track_summary(
            track_id=str(track.id),
            video_asset_id=str(track.video_id),
            persisted_observations=(persisted_observations),
        )
    except (
        GeographicMovementAnalyticsError,
        PersistedObservationMappingError,
    ) as exc:
        raise ValidationError(str(exc)) from exc
