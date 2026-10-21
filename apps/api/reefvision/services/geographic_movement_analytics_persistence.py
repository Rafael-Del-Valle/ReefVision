from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TypeVar, cast

from reefvision.schemas.geographic_movement_analytics import (
    GeographicMovementObservation,
    GeographicTrackAnalytics,
)
from reefvision.services.geographic_movement_analytics import (
    calculate_track_summary,
)

_MISSING = object()
T = TypeVar("T")


class PersistedObservationMappingError(ValueError):
    """Raised when a persisted observation cannot be mapped safely."""


def _read_value(
    source: object,
    *names: str,
) -> object:
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                return cast(object | None, source[name])

    for name in names:
        value = getattr(
            source,
            name,
            _MISSING,
        )

        if value is not _MISSING:
            return value

    joined = ", ".join(names)

    raise PersistedObservationMappingError(
        f"Persisted georeferenced observation is missing required field ({joined})."
    )


def _read_optional_value(
    source: object,
    *names: str,
) -> object | None:
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                value: object | None = source[name]
                return value

    for name in names:
        value = getattr(
            source,
            name,
            _MISSING,
        )

        if value is not _MISSING:
            return value

    return None


def _required_string(
    value: object,
    *,
    field_name: str,
) -> str:
    if value is None:
        raise PersistedObservationMappingError(f"{field_name} cannot be null.")

    result = str(value).strip()

    if not result:
        raise PersistedObservationMappingError(f"{field_name} cannot be empty.")

    return result


def _optional_string(
    value: object,
) -> str | None:
    if value is None:
        return None

    result = str(value).strip()

    if not result:
        return None

    return result


def _required_int(
    value: object,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise PersistedObservationMappingError(f"{field_name} must be an integer.")

    try:
        if not isinstance(
            value,
            (str, bytes, bytearray, int, float),
        ):
            raise TypeError("Persisted numeric value has unsupported type")
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PersistedObservationMappingError(f"{field_name} must be an integer.") from exc

    return result


def _required_float(
    value: object,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise PersistedObservationMappingError(f"{field_name} must be numeric.")

    try:
        if not isinstance(
            value,
            (str, bytes, bytearray, int, float),
        ):
            raise TypeError("Persisted numeric value has unsupported type")
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PersistedObservationMappingError(f"{field_name} must be numeric.") from exc

    return result


def _location_source(
    persisted: object,
) -> object | None:
    return _read_optional_value(
        persisted,
        "location",
        "geographic_location",
        "location_json",
        "geographic_location_json",
    )


def _latitude_value(
    persisted: object,
) -> object:
    value = _read_optional_value(
        persisted,
        "latitude_deg",
        "latitude",
        "location_latitude_deg",
    )

    if value is not None:
        return value

    location = _location_source(persisted)

    if location is not None:
        return _read_value(
            location,
            "latitude_deg",
            "latitude",
        )

    raise PersistedObservationMappingError(
        "Persisted georeferenced observation is missing required latitude."
    )


def _longitude_value(
    persisted: object,
) -> object:
    value = _read_optional_value(
        persisted,
        "longitude_deg",
        "longitude",
        "location_longitude_deg",
    )

    if value is not None:
        return value

    location = _location_source(persisted)

    if location is not None:
        return _read_value(
            location,
            "longitude_deg",
            "longitude",
        )

    raise PersistedObservationMappingError(
        "Persisted georeferenced observation is missing required longitude."
    )


def _crs_value(
    persisted: object,
) -> object:
    value = _read_optional_value(
        persisted,
        "crs",
        "geographic_crs",
        "coordinate_reference_system",
    )

    if value is not None:
        return value

    location = _location_source(persisted)

    if location is not None:
        return _read_value(
            location,
            "crs",
            "geographic_crs",
            "coordinate_reference_system",
        )

    raise PersistedObservationMappingError(
        "Persisted georeferenced observation is missing required CRS."
    )


def geographic_movement_observation_from_persisted(
    persisted: object,
) -> GeographicMovementObservation:
    """Convert one persisted georeferenced record to the pure analytics input."""

    observation_id = _required_string(
        _read_value(
            persisted,
            "observation_id",
            "id",
        ),
        field_name="observation_id",
    )

    track_id = _optional_string(
        _read_value(
            persisted,
            "track_id",
        )
    )

    video_asset_id = _required_string(
        _read_value(
            persisted,
            "video_asset_id",
            "video_id",
        ),
        field_name="video_asset_id",
    )

    frame_index = _required_int(
        _read_value(
            persisted,
            "frame_index",
        ),
        field_name="frame_index",
    )

    frame_time_s = _required_float(
        _read_value(
            persisted,
            "frame_time_s",
            "frame_time_seconds",
        ),
        field_name="frame_time_s",
    )

    latitude_deg = _required_float(
        _latitude_value(persisted),
        field_name="latitude_deg",
    )

    longitude_deg = _required_float(
        _longitude_value(persisted),
        field_name="longitude_deg",
    )

    crs = _required_string(
        _crs_value(persisted),
        field_name="crs",
    )

    return GeographicMovementObservation(
        observation_id=observation_id,
        track_id=track_id,
        video_asset_id=video_asset_id,
        frame_index=frame_index,
        frame_time_s=frame_time_s,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        crs=crs,
    )


def geographic_movement_observations_from_persisted(
    persisted_observations: Iterable[object],
) -> list[GeographicMovementObservation]:
    """Map only explicitly fresh rows, preserving their ordering and values.

    Stale results and records with unknown lifecycle state cannot contribute
    geographic distance, speed, or bearing to a current analysis.
    """

    return [
        geographic_movement_observation_from_persisted(persisted)
        for persisted in persisted_observations
        if _read_optional_value(persisted, "is_stale") is False
    ]


def calculate_persisted_track_summary(
    *,
    track_id: str,
    video_asset_id: str,
    persisted_observations: Iterable[object],
) -> GeographicTrackAnalytics:
    """Run the existing pure analytics against persisted observation records."""

    observations = geographic_movement_observations_from_persisted(persisted_observations)

    return calculate_track_summary(
        track_id=track_id,
        video_asset_id=video_asset_id,
        observations=observations,
    )
