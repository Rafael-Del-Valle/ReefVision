"""Deterministic instantaneous streamlines on a geographic rectilinear field.

Inputs must already represent one compatible UTC/depth/source slice in m/s,
with geographic east/north components. Missing/QC-excluded cells are None.
This kernel does not infer those scientific identities or predict trajectories.
"""

from bisect import bisect_right
from dataclasses import dataclass
from itertools import pairwise
from math import cos, hypot, isfinite, pi, radians, sin, sqrt
from typing import Literal

ALGORITHM_VERSION = "wgs84-stationary-bilinear-rk4-v1"
Termination = Literal[
    "outside_domain",
    "missing_cell",
    "stagnation",
    "max_steps",
    "max_length",
    "polar_limit",
    "nonfinite_step",
]
Matrix = tuple[tuple[float | None, ...], ...]


def _finite(value: float) -> bool:
    return not isinstance(value, bool) and isfinite(value)


def _axis(values: tuple[float, ...], bound: float) -> tuple[float, ...]:
    axis = tuple(values)
    if len(axis) < 2 or any(not _finite(v) or abs(v) > bound for v in axis):
        raise ValueError("Axes require at least two finite geographic coordinates")
    if not (all(a < b for a, b in pairwise(axis)) or all(a > b for a, b in pairwise(axis))):
        raise ValueError("Axes must be unique and strictly monotonic")
    return axis


@dataclass(frozen=True)
class CurrentField:
    latitudes: tuple[float, ...]
    longitudes: tuple[float, ...]
    east: Matrix
    north: Matrix

    def __post_init__(self) -> None:
        lat = _axis(self.latitudes, 90)
        lon = _axis(self.longitudes, 180)
        # The current kernel does not unwrap longitude across the dateline.
        # A pair at -179 and +179 degrees represents a two-degree local cell,
        # not a 358-degree interpolation spanning almost the entire Earth.
        # Fail closed rather than deriving scientifically misleading tracks.
        ordered_lon = sorted(lon)
        if any(right - left > 180.0 for left, right in pairwise(ordered_lon)):
            raise ValueError(
                "Current longitude gap exceeds 180 degrees; "
                "antimeridian-spanning grids require regridding before integration"
            )
        matrices = []
        for values in (self.east, self.north):
            rows = tuple(tuple(row) for row in values)
            if len(rows) != len(lat) or any(len(row) != len(lon) for row in rows):
                raise ValueError("Component dimensions must match latitude/longitude axes")
            if any(v is not None and not _finite(v) for row in rows for v in row):
                raise ValueError("Component values must be finite or explicit missing values")
            if lat[0] > lat[-1]:
                rows = rows[::-1]
            if lon[0] > lon[-1]:
                rows = tuple(row[::-1] for row in rows)
            matrices.append(rows)
        object.__setattr__(self, "latitudes", tuple(sorted(lat)))
        object.__setattr__(self, "longitudes", tuple(sorted(lon)))
        object.__setattr__(self, "east", matrices[0])
        object.__setattr__(self, "north", matrices[1])

    def contains(self, latitude: float, longitude: float) -> bool:
        return (
            _finite(latitude)
            and _finite(longitude)
            and self.latitudes[0] <= latitude <= self.latitudes[-1]
            and self.longitudes[0] <= longitude <= self.longitudes[-1]
        )

    def sample(self, latitude: float, longitude: float) -> tuple[float, float] | None:
        """Bilinear sample; all four corners are mandatory even on an edge."""
        if not self.contains(latitude, longitude):
            return None
        i = min(bisect_right(self.latitudes, latitude) - 1, len(self.latitudes) - 2)
        j = min(bisect_right(self.longitudes, longitude) - 1, len(self.longitudes) - 2)
        y = (latitude - self.latitudes[i]) / (self.latitudes[i + 1] - self.latitudes[i])
        x = (longitude - self.longitudes[j]) / (self.longitudes[j + 1] - self.longitudes[j])
        result = []
        for matrix in (self.east, self.north):
            a, b = matrix[i][j], matrix[i][j + 1]
            c, d = matrix[i + 1][j], matrix[i + 1][j + 1]
            if a is None or b is None or c is None or d is None:
                return None
            value = (1 - y) * ((1 - x) * a + x * b) + y * ((1 - x) * c + x * d)
            if not isfinite(value):
                return None
            result.append(value)
        return result[0], result[1]


@dataclass(frozen=True)
class StreamlinePoint:
    latitude: float
    longitude: float
    speed_m_s: float


@dataclass(frozen=True)
class Streamline:
    points: tuple[StreamlinePoint, ...]
    termination: Termination
    length_m: float
    algorithm_version: str = ALGORITHM_VERSION


class _Stop(Exception):
    def __init__(self, reason: Termination):
        self.reason = reason


def _velocity(field: CurrentField, lat: float, lon: float) -> tuple[float, float, float]:
    if not isfinite(lat) or not isfinite(lon):
        raise _Stop("nonfinite_step")
    if not field.contains(lat, lon):
        raise _Stop("outside_domain")
    if abs(lat) >= 85:
        raise _Stop("polar_limit")
    velocity = field.sample(lat, lon)
    if velocity is None:
        raise _Stop("missing_cell")
    east, north = velocity
    speed = hypot(east, north)
    if not isfinite(speed):
        raise _Stop("nonfinite_step")
    # WGS84 meridional and prime-vertical radii; angular rates in degrees/s.
    phi = radians(lat)
    eccentricity_squared = 6.6943799901413165e-3
    denominator = 1 - eccentricity_squared * sin(phi) ** 2
    prime = 6378137.0 / sqrt(denominator)
    meridian = 6378137.0 * (1 - eccentricity_squared) / denominator**1.5
    return north / meridian * 180 / pi, east / (prime * cos(phi)) * 180 / pi, speed


def integrate_streamline(
    field: CurrentField,
    latitude: float,
    longitude: float,
    *,
    step_seconds: float = 60,
    max_steps: int = 1000,
    max_length_m: float = 100000,
    stagnation_m_s: float = 1e-9,
) -> Streamline:
    """Forward RK4 in a frozen field; reject whole steps crossing unsupported cells.

    Steps are capped to a quarter of the smallest grid spacing using global
    component bounds, so RK4 stages cannot leap across a missing grid cell.
    Length uses RK4 quadrature of speed, a numerical estimate rather than a
    measured distance. No boundary clipping, longitude wrapping or extrapolation.
    Limits cap runtime/output. Polar integration is unsupported above 85 degrees.
    """
    if (
        not _finite(latitude)
        or not _finite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValueError("Seed must be finite WGS84 latitude/longitude")
    if (
        not _finite(step_seconds)
        or not 0 < step_seconds <= 3600
        or isinstance(max_steps, bool)
        or not isinstance(max_steps, int)
        or not 1 <= max_steps <= 10000
        or not _finite(max_length_m)
        or not 0 < max_length_m <= 1e6
        or not _finite(stagnation_m_s)
        or stagnation_m_s < 0
    ):
        raise ValueError("Integration limits must be finite, positive and bounded")
    points: list[StreamlinePoint] = []
    length = 0.0
    lat, lon = latitude, longitude
    # Conservative global angular-rate bounds, including the highest supported
    # latitude. Bilinear component magnitudes cannot exceed their corner bounds.
    maximum_east = (
        max(abs(v) for row in field.east for v in row if v is not None)
        if any(v is not None for row in field.east for v in row)
        else 0.0
    )
    maximum_north = (
        max(abs(v) for row in field.north for v in row if v is not None)
        if any(v is not None for row in field.north for v in row)
        else 0.0
    )
    minimum_lat_spacing = min(b - a for a, b in pairwise(field.latitudes))
    minimum_lon_spacing = min(b - a for a, b in pairwise(field.longitudes))
    poleward_latitude = min(85.0, max(abs(field.latitudes[0]), abs(field.latitudes[-1])))
    east_rate_bound = maximum_east / (6378137 * cos(radians(poleward_latitude))) * 180 / pi
    north_rate_bound = maximum_north / 6335439.3272928195 * 180 / pi
    h = step_seconds
    if east_rate_bound > 0:
        h = min(h, minimum_lon_spacing / east_rate_bound / 4)
    if north_rate_bound > 0:
        h = min(h, minimum_lat_spacing / north_rate_bound / 4)
    try:
        first = _velocity(field, lat, lon)
        points.append(StreamlinePoint(lat, lon, first[2]))
        for _ in range(max_steps):
            k1 = _velocity(field, lat, lon)
            if k1[2] <= stagnation_m_s:
                raise _Stop("stagnation")
            if not isfinite(h) or h <= 0:
                raise _Stop("nonfinite_step")
            k2 = _velocity(field, lat + h * k1[0] / 2, lon + h * k1[1] / 2)
            k3 = _velocity(field, lat + h * k2[0] / 2, lon + h * k2[1] / 2)
            k4 = _velocity(field, lat + h * k3[0], lon + h * k3[1])
            next_lat = lat + h * (k1[0] / 6 + k2[0] / 3 + k3[0] / 3 + k4[0] / 6)
            next_lon = lon + h * (k1[1] / 6 + k2[1] / 3 + k3[1] / 3 + k4[1] / 6)
            endpoint = _velocity(field, next_lat, next_lon)
            distance = h * (k1[2] / 6 + k2[2] / 3 + k3[2] / 3 + k4[2] / 6)
            if not isfinite(distance):
                raise _Stop("nonfinite_step")
            if length + distance > max_length_m:
                raise _Stop("max_length")
            lat, lon = next_lat, next_lon
            length += distance
            points.append(StreamlinePoint(lat, lon, endpoint[2]))
        return Streamline(tuple(points), "max_steps", length)
    except _Stop as stop:
        return Streamline(tuple(points), stop.reason, length)
