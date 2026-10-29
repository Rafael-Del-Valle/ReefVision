from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from geographiclib.geodesic import Geodesic

from reefvision.schemas.geographic_movement_analytics import (
    GeographicCoordinate,
    GeographicMovementObservation,
    GeographicMovementSegment,
    GeographicTrackAnalytics,
)

SUPPORTED_GEOGRAPHIC_CRS = "EPSG:4326"

# WGS84 ellipsoid constants.
_WGS84_SEMI_MAJOR_AXIS_M = 6_378_137.0
_WGS84_FLATTENING = 1.0 / 298.257223563
_WGS84_SEMI_MINOR_AXIS_M = (1.0 - _WGS84_FLATTENING) * _WGS84_SEMI_MAJOR_AXIS_M


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
    """Return ellipsoidal WGS84 distance in meters using Vincenty's inverse method."""

    _validate_coordinate(
        start_latitude_deg,
        start_longitude_deg,
    )
    _validate_coordinate(
        end_latitude_deg,
        end_longitude_deg,
    )

    if start_latitude_deg == end_latitude_deg and start_longitude_deg == end_longitude_deg:
        return 0.0

    a = _WGS84_SEMI_MAJOR_AXIS_M
    b = _WGS84_SEMI_MINOR_AXIS_M
    f = _WGS84_FLATTENING

    phi_1 = math.radians(start_latitude_deg)
    phi_2 = math.radians(end_latitude_deg)
    longitude_delta = math.radians(end_longitude_deg - start_longitude_deg)

    reduced_1 = math.atan((1.0 - f) * math.tan(phi_1))
    reduced_2 = math.atan((1.0 - f) * math.tan(phi_2))

    sin_reduced_1 = math.sin(reduced_1)
    cos_reduced_1 = math.cos(reduced_1)
    sin_reduced_2 = math.sin(reduced_2)
    cos_reduced_2 = math.cos(reduced_2)

    lambda_value = longitude_delta

    sin_sigma = 0.0
    cos_sigma = 0.0
    sigma = 0.0
    sin_alpha = 0.0
    cos_sq_alpha = 0.0
    cos_two_sigma_mid = 0.0

    for _ in range(200):
        sin_lambda = math.sin(lambda_value)
        cos_lambda = math.cos(lambda_value)

        sin_sigma = math.sqrt(
            (cos_reduced_2 * sin_lambda) ** 2
            + (cos_reduced_1 * sin_reduced_2 - sin_reduced_1 * cos_reduced_2 * cos_lambda) ** 2
        )

        if sin_sigma == 0.0:
            return 0.0

        cos_sigma = sin_reduced_1 * sin_reduced_2 + cos_reduced_1 * cos_reduced_2 * cos_lambda

        sigma = math.atan2(
            sin_sigma,
            cos_sigma,
        )

        sin_alpha = cos_reduced_1 * cos_reduced_2 * sin_lambda / sin_sigma

        cos_sq_alpha = 1.0 - sin_alpha * sin_alpha

        if cos_sq_alpha == 0.0:
            cos_two_sigma_mid = 0.0
        else:
            cos_two_sigma_mid = cos_sigma - (2.0 * sin_reduced_1 * sin_reduced_2 / cos_sq_alpha)

        coefficient_c = f / 16.0 * cos_sq_alpha * (4.0 + f * (4.0 - 3.0 * cos_sq_alpha))

        previous_lambda = lambda_value

        lambda_value = longitude_delta + (1.0 - coefficient_c) * f * sin_alpha * (
            sigma
            + coefficient_c
            * sin_sigma
            * (
                cos_two_sigma_mid
                + coefficient_c * cos_sigma * (-1.0 + 2.0 * cos_two_sigma_mid * cos_two_sigma_mid)
            )
        )

        if abs(lambda_value - previous_lambda) <= 1e-12:
            break
    else:
        raise GeographicMovementInputError("WGS84 inverse distance calculation did not converge.")

    reduced_parameter = cos_sq_alpha * (a * a - b * b) / (b * b)

    coefficient_a = 1.0 + reduced_parameter / 16_384.0 * (
        4096.0
        + reduced_parameter * (-768.0 + reduced_parameter * (320.0 - 175.0 * reduced_parameter))
    )

    coefficient_b = (
        reduced_parameter
        / 1024.0
        * (
            256.0
            + reduced_parameter * (-128.0 + reduced_parameter * (74.0 - 47.0 * reduced_parameter))
        )
    )

    delta_sigma = (
        coefficient_b
        * sin_sigma
        * (
            cos_two_sigma_mid
            + coefficient_b
            / 4.0
            * (
                cos_sigma * (-1.0 + 2.0 * cos_two_sigma_mid * cos_two_sigma_mid)
                - coefficient_b
                / 6.0
                * cos_two_sigma_mid
                * (-3.0 + 4.0 * sin_sigma * sin_sigma)
                * (-3.0 + 4.0 * cos_two_sigma_mid * cos_two_sigma_mid)
            )
        )
    )

    distance_m = b * coefficient_a * (sigma - delta_sigma)

    if distance_m < 0.0:
        raise GeographicMovementInputError("Calculated geographic distance cannot be negative.")

    return distance_m


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

    elapsed_time_s = end.frame_time_s - start.frame_time_s

    if elapsed_time_s > 0.0:
        speed_m_s: float | None = distance_m / elapsed_time_s
        speed_valid = True
        invalid_reason = None
    else:
        speed_m_s = None
        speed_valid = False
        invalid_reason = "non_positive_elapsed_time"

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
