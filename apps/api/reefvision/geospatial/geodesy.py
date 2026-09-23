"""Local true-east/north displacement and WGS84 ellipsoidal distance."""

from math import atan2, degrees, hypot, isfinite

from geographiclib.geodesic import Geodesic

from reefvision.domain.errors import ValidationError


def _valid_location(latitude: float, longitude: float) -> None:
    if (
        not isfinite(latitude)
        or not isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValidationError("Geographic coordinates must be finite WGS84 latitude/longitude")


def offset_to_geographic(
    latitude: float, longitude: float, east_offset_m: float, north_offset_m: float
) -> tuple[float, float]:
    """Map a local offset using true azimuth and ellipsoidal surface distance.

    This azimuthal-equidistant convention avoids UTM grid convergence/zone issues.
    Projection callers enforce their own planar-distance bound.
    """
    _valid_location(latitude, longitude)
    if not isfinite(east_offset_m) or not isfinite(north_offset_m):
        raise ValidationError("Local geographic offsets must be finite")
    distance = hypot(east_offset_m, north_offset_m)
    if not isfinite(distance):
        raise ValidationError("Local geographic distance must be finite")
    result = Geodesic.WGS84.Direct(
        latitude, longitude, degrees(atan2(east_offset_m, north_offset_m)), distance
    )
    lat, lon = float(result["lat2"]), float(result["lon2"])
    _valid_location(lat, lon)
    return lat, lon


def geodesic_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    _valid_location(lat1, lon1)
    _valid_location(lat2, lon2)
    return float(Geodesic.WGS84.Inverse(lat1, lon1, lat2, lon2)["s12"])
