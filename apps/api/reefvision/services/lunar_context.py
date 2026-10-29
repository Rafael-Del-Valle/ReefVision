"""Versioned offline lunar context, never a tide or local sky prediction.

Uses a short geocentric ecliptic-longitude series for the Sun and Moon.
Approximate lunar age is elongation / 360 times the mean synodic month, NOT
an ephemeris-derived time since the most recent conjunction.
"""

from __future__ import annotations

import math
from datetime import datetime

from sqlalchemy.orm import Session

from reefvision.schemas.lunar_context import (
    LunarContextRequest,
    LunarContextResponse,
    LunarPhase,
)
from reefvision.services.scientific_data import ScientificDataService, content_hash

ALGORITHM = "reefvision-low-precision-ecliptic-longitude-1"
SYNODIC_MONTH_DAYS = 29.530588861
PHASES: tuple[LunarPhase, ...] = (
    "new_moon",
    "waxing_crescent",
    "first_quarter",
    "waxing_gibbous",
    "full_moon",
    "waning_gibbous",
    "last_quarter",
    "waning_crescent",
)


def _sin(degrees: float) -> float:
    return math.sin(math.radians(degrees % 360))


def _longitudes(observed_at: datetime) -> tuple[float, float]:
    # UTC-based Julian Date is adequate at this model's low precision.
    julian_date = observed_at.timestamp() / 86400 + 2440587.5
    centuries = (julian_date - 2451545.0) / 36525.0

    solar_mean_longitude = 280.46646 + 36000.76983 * centuries + 0.0003032 * centuries**2
    solar_mean_anomaly = 357.52911 + 35999.05029 * centuries - 0.0001537 * centuries**2
    solar_center = (
        (1.914602 - 0.004817 * centuries - 0.000014 * centuries**2) * _sin(solar_mean_anomaly)
        + (0.019993 - 0.000101 * centuries) * _sin(2 * solar_mean_anomaly)
        + 0.000289 * _sin(3 * solar_mean_anomaly)
    )
    sun_longitude = (solar_mean_longitude + solar_center) % 360

    moon_mean_longitude = 218.3164477 + 481267.88123421 * centuries - 0.0015786 * centuries**2
    elongation = 297.8501921 + 445267.1114034 * centuries
    moon_mean_anomaly = 134.9633964 + 477198.8675055 * centuries
    moon_argument_latitude = 93.2720950 + 483202.0175233 * centuries

    # Truncated periodic terms: lunar ecliptic longitude, degrees.
    moon_correction = (
        6.289 * _sin(moon_mean_anomaly)
        + 1.274 * _sin(2 * elongation - moon_mean_anomaly)
        + 0.658 * _sin(2 * elongation)
        + 0.214 * _sin(2 * moon_mean_anomaly)
        - 0.186 * _sin(solar_mean_anomaly)
        - 0.114 * _sin(2 * moon_argument_latitude)
        + 0.059 * _sin(2 * elongation - 2 * moon_mean_anomaly)
        + 0.057 * _sin(2 * elongation - solar_mean_anomaly - moon_mean_anomaly)
        + 0.053 * _sin(2 * elongation + moon_mean_anomaly)
        + 0.046 * _sin(2 * elongation - solar_mean_anomaly)
        + 0.041 * _sin(solar_mean_anomaly - moon_mean_anomaly)
        - 0.035 * _sin(elongation)
        - 0.031 * _sin(solar_mean_anomaly + moon_mean_anomaly)
        - 0.015 * _sin(2 * moon_argument_latitude - 2 * elongation)
        + 0.011 * _sin(2 * elongation - 4 * moon_mean_anomaly)
    )
    moon_longitude = (moon_mean_longitude + moon_correction) % 360
    return sun_longitude, moon_longitude


def calculate_lunar_context(
    session: Session,
    project_id: str,
    request: LunarContextRequest,
) -> LunarContextResponse:
    ScientificDataService(session).require_project(project_id)

    sun, moon = _longitudes(request.observed_at)
    phase_fraction = ((moon - sun) % 360) / 360
    # Approximate illumination uses longitude elongation, ignoring latitude.
    illuminated = (1 - math.cos(2 * math.pi * phase_fraction)) / 2
    index = int(phase_fraction * 8 + 0.5) % len(PHASES)
    phase = PHASES[index]

    values = {
        "schema_version": "1.1.0",
        "algorithm": ALGORITHM,
        "project_id": project_id,
        "observed_at": request.observed_at.isoformat(),
        "phase": phase,
        "phase_fraction": round(phase_fraction, 8),
        "illuminated_fraction": round(illuminated, 8),
        "approximate_lunar_age_days": round(phase_fraction * SYNODIC_MONTH_DAYS, 4),
        "reference_frame": "geocentric_approximate",
        "computation": "offline_deterministic",
    }
    return LunarContextResponse(
        **values,
        content_sha256=content_hash(values),
        methodological_notes=[
            "Offline geocentric approximation from a truncated longitude series.",
            "Phase and illumination are estimates, not an exact ephemeris.",
            "Approximate lunar age scales elongation by the mean synodic month.",
            "An explicit UTC observation timestamp is required; no time is inferred.",
            "No latitude, longitude, tide height, moonrise or moonset is inferred.",
            "Lunar phase alone does not establish local spring or neap tides.",
            "This on-demand response is not a persisted scientific observation.",
        ],
    )
