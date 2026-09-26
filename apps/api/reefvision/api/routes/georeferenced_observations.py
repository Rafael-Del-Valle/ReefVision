"""Read-only API routes for persisted geo-referenced observations."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import GeoReferencedObservation as GeoReferencedObservationRecord
from reefvision.domain.errors import ValidationError
from reefvision.schemas.georeferenced_observation import (
    GeoReferencedObservation,
)
from reefvision.schemas.georeferenced_observation_api import (
    GeoReferencedObservationListResponse,
    GeoReferencedObservationRecomputeResponse,
)
from reefvision.services.geographic_gis_export import (
    GeographicGISExportError,
    csv_bytes,
    geojson_bytes,
)
from reefvision.services.geographic_gis_export_enrichment import (
    build_geographic_export_enrichments,
)
from reefvision.services.georeferenced_observation_recomputation import (
    GeoreferencedObservationRecomputationService,
)
from reefvision.services.georeferenced_observations import (
    GeoReferencedObservationService,
)

router = APIRouter(tags=["georeferencing"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _collection(
    service: GeoReferencedObservationService,
    records: list[GeoReferencedObservationRecord],
) -> GeoReferencedObservationListResponse:
    items = [
        service.to_summary(record)
        for record in records
        if not record.is_stale
    ]

    return GeoReferencedObservationListResponse(
        items=items,
        count=len(items),
    )


@router.get(
    "/georeferenced-observations/{observation_id}",
    response_model=GeoReferencedObservation,
)
def get_georeferenced_observation(
    observation_id: str,
    session: DbSession,
) -> GeoReferencedObservation:
    service = GeoReferencedObservationService(session)

    return service.to_response(service.get(observation_id))


@router.get(
    "/videos/{video_id}/georeferenced-observations",
    response_model=GeoReferencedObservationListResponse,
)
def list_video_georeferenced_observations(
    video_id: str,
    session: DbSession,
    track_id: Annotated[
        str | None,
        Query(),
    ] = None,
    frame_index: Annotated[
        int | None,
        Query(ge=0),
    ] = None,
) -> GeoReferencedObservationListResponse:
    service = GeoReferencedObservationService(session)

    records = service.list_for_video(
        video_id,
        track_id=track_id,
        frame_index=frame_index,
    )

    return _collection(
        service,
        records,
    )


@router.get(
    "/video-tracks/{track_id}/georeferenced-observations",
    response_model=GeoReferencedObservationListResponse,
)
def list_track_georeferenced_observations(
    track_id: str,
    session: DbSession,
) -> GeoReferencedObservationListResponse:
    service = GeoReferencedObservationService(session)

    return _collection(
        service,
        service.list_for_track(track_id),
    )


@router.get(
    "/videos/{video_id}/frames/{frame_index}/georeferenced-observations",
    response_model=GeoReferencedObservationListResponse,
)
def list_frame_georeferenced_observations(
    video_id: str,
    frame_index: int,
    session: DbSession,
) -> GeoReferencedObservationListResponse:
    service = GeoReferencedObservationService(session)

    return _collection(
        service,
        service.list_for_frame(
            video_id,
            frame_index,
        ),
    )


@router.get("/videos/{video_id}/geographic-export")
def export_video_geographic_observations(
    video_id: str,
    session: DbSession,
    export_format: Annotated[
        Literal["geojson", "csv"],
        Query(alias="format"),
    ] = "geojson",
    track_id: Annotated[str | None, Query()] = None,
) -> Response:
    """Download canonical persisted observations without recalculation."""
    service = GeoReferencedObservationService(session)

    records = service.list_for_video(
        video_id,
        track_id=track_id,
    )

    observations = [
        service.to_response(record)
        for record in records
        if not record.is_stale
    ]

    enrichments = build_geographic_export_enrichments(
        session,
        observations,
    )

    try:
        if export_format == "geojson":
            content = geojson_bytes(observations, enrichments)
            media_type = "application/geo+json"
            extension = "geojson"
        else:
            content = csv_bytes(observations, enrichments)
            media_type = "text/csv"
            extension = "csv"
    except GeographicGISExportError as exc:
        raise ValidationError(str(exc)) from exc

    filename = f"reefvision-geographic-observations.{extension}"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/videos/{video_id}/georeferenced-observations/recompute",
    response_model=GeoReferencedObservationRecomputeResponse,
)
def recompute_video_georeferenced_observations(
    video_id: str,
    request: Request,
    session: DbSession,
) -> GeoReferencedObservationRecomputeResponse:
    """Atomically replace stale geographic observations."""
    return GeoreferencedObservationRecomputationService(
        session,
        request.app.state.settings,
    ).recompute_video(video_id)
