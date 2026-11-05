from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from geographiclib.geodesic import Geodesic

from reefvision.geospatial.geodesy import geodesic_distance_m
from reefvision.schemas.geographic_movement_analytics import (
    GeographicCoordinate,
    GeographicMovementObservation,
    GeographicMovementSegment,
    GeographicTrackAnalytics,
)

SUPPORTED_GEOGRAPHIC_CRS = "EPSG:4326"


class GeographicMovementAnalyticsError(ValueError):
    """Base exception for invalid movement-analytics inputs."""


class UnsupportedGeographicCRSError(
    GeographicMovementAnalyticsError,
):
    """Raised when movement analytics receive an unsupported CRS."""


class GeographicMovementInputError(
    GeographicMovementAnalyticsError,
):
    """Raised when observations cannot form the requested trajectory."""


def _normalized_crs(crs: str) -> str:
    return crs.strip().upper()


def _require_supported_crs(crs: str) -> None:
    normalized = _normalized_crs(crs)

    if normalized != SUPPORTED_GEOGRAPHIC_CRS:
        raise UnsupportedGeographicCRSError(
            "Geographic movement analytics currently support only "
            f"{SUPPORTED_GEOGRAPHIC_CRS}; received {crs!r}."
        )


def _validate_coordinate(
    latitude_deg: float,
    longitude_deg: float,
) -> None:
    if not math.isfinite(latitude_deg):
        raise GeographicMovementInputError("Latitude must be finite.")

    if not math.isfinite(longitude_deg):
        raise GeographicMovementInputError("Longitude must be finite.")

    if not -90.0 <= latitude_deg <= 90.0:
        raise GeographicMovementInputError("Latitude must be between -90 and 90 degrees.")

    if not -180.0 <= longitude_deg <= 180.0:
        raise GeographicMovementInputError("Longitude must be between -180 and 180 degrees.")


def geographic_distance_m(
    start_latitude_deg: float,
    start_longitude_deg: float,
    end_latitude_deg: float,
    end_longitude_deg: float,
) -> float:
    """Return ellipsoidal WGS84 distance using the shared robust inverse solver."""

    _validate_coordinate(start_latitude_deg, start_longitude_deg)
    _validate_coordinate(end_latitude_deg, end_longitude_deg)

    return geodesic_distance_m(
        start_latitude_deg,
        start_longitude_deg,
        end_latitude_deg,
        end_longitude_deg,
    )


def _coordinate(
    observation: GeographicMovementObservation,
) -> GeographicCoordinate:
    return GeographicCoordinate(
        latitude_deg=observation.latitude_deg,
        longitude_deg=observation.longitude_deg,
        crs=observation.crs,
    )


def calculate_movement_segment(
    start: GeographicMovementObservation,
    end: GeographicMovementObservation,
    *,
    cumulative_distance_before_m: float = 0.0,
) -> GeographicMovementSegment:
    """Calculate one movement segment between consecutive persisted observations."""

    if cumulative_distance_before_m < 0.0:
        raise GeographicMovementInputError(
            "Cumulative distance before a segment cannot be negative."
        )

    if start.track_id is None or end.track_id is None:
        raise GeographicMovementInputError("Movement segments require non-null track IDs.")

    if start.track_id != end.track_id:
        raise GeographicMovementInputError(
            "Movement segment observations must belong to the same track."
        )

    if start.video_asset_id != end.video_asset_id:
        raise GeographicMovementInputError(
            "Movement segment observations must belong to the same video."
        )

    if end.frame_index < start.frame_index:
        raise GeographicMovementInputError(
            "Movement segment observations must be in nondecreasing frame order."
        )

    _require_supported_crs(start.crs)
    _require_supported_crs(end.crs)

    if _normalized_crs(start.crs) != _normalized_crs(end.crs):
        raise GeographicMovementInputError("Movement segment observations must use the same CRS.")

    distance_m = geographic_distance_m(
        start.latitude_deg,
        start.longitude_deg,
        end.latitude_deg,
        end.longitude_deg,
    )
    geodesic = Geodesic.WGS84.Inverse(
        start.latitude_deg,
        start.longitude_deg,
        end.latitude_deg,
        end.longitude_deg,
    )
    # The initial azimuth describes displacement between sampled locations;
    # it does not estimate the organism's body orientation or intervening path.
    initial_bearing_deg = float(geodesic["azi1"]) % 360.0 if geodesic["s12"] > 0.0 else None

    distance_uncertainty_m: float | None = None
    bearing_uncertainty_deg: float | None = None
    uncertainty_method = None
    uncertainty_reason: str | None = None
    if start.horizontal_sigma_m is None or end.horizontal_sigma_m is None:
        uncertainty_reason = "missing_endpoint_standard_uncertainty"
    elif (
        not start.uncertainty_correlation_group_id
        or not end.uncertainty_correlation_group_id
        or start.uncertainty_correlation_group_id == end.uncertainty_correlation_group_id
    ):
        uncertainty_reason = "unknown_or_shared_endpoint_correlation"
    else:
        distance_uncertainty_m = math.hypot(
            start.horizontal_sigma_m, end.horizontal_sigma_m
        )
        uncertainty_method = "independent_isotropic_first_order"
        if distance_m > 5.0 * distance_uncertainty_m:
            bearing_uncertainty_deg = math.degrees(distance_uncertainty_m / distance_m)
        else:
            uncertainty_reason = "bearing_geometry_ill_conditioned"

    elapsed_time_s = end.frame_time_s - start.frame_time_s

    if elapsed_time_s > 0.0:
        speed_m_s: float | None = distance_m / elapsed_time_s
        speed_valid = True
        invalid_reason = None
        speed_uncertainty_m_s = (
            distance_uncertainty_m / elapsed_time_s
            if distance_uncertainty_m is not None
            else None
        )
    else:
        speed_m_s = None
        speed_valid = False
        invalid_reason = "non_positive_elapsed_time"
        speed_uncertainty_m_s = None
        if distance_uncertainty_m is not None:
            uncertainty_reason = "non_positive_elapsed_time"

    return GeographicMovementSegment(
        track_id=start.track_id,
        video_asset_id=start.video_asset_id,
        start_observation_id=start.observation_id,
        end_observation_id=end.observation_id,
        start_frame_index=start.frame_index,
        end_frame_index=end.frame_index,
        start_frame_time_s=start.frame_time_s,
        end_frame_time_s=end.frame_time_s,
        elapsed_time_s=elapsed_time_s,
        start_location=_coordinate(start),
        end_location=_coordinate(end),
        distance_m=distance_m,
        speed_m_s=speed_m_s,
        initial_bearing_deg=initial_bearing_deg,
        distance_standard_uncertainty_m=distance_uncertainty_m,
        speed_standard_uncertainty_m_s=speed_uncertainty_m_s,
        bearing_standard_uncertainty_deg=bearing_uncertainty_deg,
        uncertainty_method=uncertainty_method,
        uncertainty_unavailable_reason=uncertainty_reason,
        cumulative_distance_m=(cumulative_distance_before_m + distance_m),
        speed_valid=speed_valid,
        invalid_reason=invalid_reason,
    )


def calculate_track_summary(
    *,
    track_id: str,
    video_asset_id: str,
    observations: Sequence[GeographicMovementObservation],
) -> GeographicTrackAnalytics:
    """Calculate deterministic movement analytics for one track."""

    if not track_id:
        raise GeographicMovementInputError("track_id is required.")

    if not video_asset_id:
        raise GeographicMovementInputError("video_asset_id is required.")

    matching = [observation for observation in observations if observation.track_id == track_id]

    for observation in matching:
        if observation.video_asset_id != video_asset_id:
            raise GeographicMovementInputError(
                "Track observations must belong to the requested video."
            )

        _require_supported_crs(observation.crs)

    ordered = sorted(
        matching,
        key=lambda observation: (
            observation.frame_index,
            observation.frame_time_s,
            observation.observation_id,
        ),
    )

    if not ordered:
        return GeographicTrackAnalytics(
            track_id=track_id,
            video_asset_id=video_asset_id,
            observation_count=0,
            segment_count=0,
            total_distance_m=0.0,
            net_displacement_m=0.0,
        )

    first = ordered[0]
    last = ordered[-1]

    segments: list[GeographicMovementSegment] = []

    cumulative_distance_m = 0.0

    for start, end in pairwise(
        ordered,
    ):
        segment = calculate_movement_segment(
            start,
            end,
            cumulative_distance_before_m=(cumulative_distance_m),
        )

        segments.append(segment)

        cumulative_distance_m = segment.cumulative_distance_m

    if len(ordered) == 1:
        net_displacement_m = 0.0
    else:
        net_displacement_m = geographic_distance_m(
            first.latitude_deg,
            first.longitude_deg,
            last.latitude_deg,
            last.longitude_deg,
        )

    elapsed_time_s = last.frame_time_s - first.frame_time_s

    if elapsed_time_s > 0.0:
        mean_speed_m_s: float | None = cumulative_distance_m / elapsed_time_s
    else:
        mean_speed_m_s = None

    valid_speeds = [segment.speed_m_s for segment in segments if segment.speed_m_s is not None]

    max_segment_speed_m_s = max(valid_speeds) if valid_speeds else None

    return GeographicTrackAnalytics(
        track_id=track_id,
        video_asset_id=video_asset_id,
        observation_count=len(ordered),
        segment_count=len(segments),
        first_frame_index=(first.frame_index),
        last_frame_index=(last.frame_index),
        first_frame_time_s=(first.frame_time_s),
        last_frame_time_s=(last.frame_time_s),
        elapsed_time_s=(elapsed_time_s),
        total_distance_m=(cumulative_distance_m),
        net_displacement_m=(net_displacement_m),
        mean_speed_m_s=(mean_speed_m_s),
        max_segment_speed_m_s=(max_segment_speed_m_s),
        start_location=_coordinate(first),
        end_location=_coordinate(last),
        segments=segments,
    )
