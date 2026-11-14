"""Small explicit unit registry; no implicit salinity or coordinate conversions."""

from __future__ import annotations

from math import isfinite

# unit -> (dimension, canonical unit, scale, offset). Offsets apply to values only.
UNITS: dict[str, tuple[str, str, float, float]] = {
    "m": ("length", "m", 1, 0),
    "cm": ("length", "m", 0.01, 0),
    "mm": ("length", "m", 0.001, 0),
    "km": ("length", "m", 1000, 0),
    "m2": ("area", "m2", 1, 0),
    "cm2": ("area", "m2", 0.0001, 0),
    "mm2": ("area", "m2", 0.000001, 0),
    "s": ("time", "s", 1, 0),
    "min": ("time", "s", 60, 0),
    "h": ("time", "s", 3600, 0),
    "m/s": ("speed", "m/s", 1, 0),
    "cm/s": ("speed", "m/s", 0.01, 0),
    "kn": ("speed", "m/s", 1852 / 3600, 0),
    "degC": ("temperature", "degC", 1, 0),
    "degF": ("temperature", "degC", 5 / 9, -160 / 9),
    "K": ("temperature", "degC", 1, -273.15),
    "PSU": ("practical_salinity", "PSU", 1, 0),
    "g/kg": ("mass_salinity", "g/kg", 1, 0),
    "count": ("count", "count", 1, 0),
    "1": ("dimensionless", "1", 1, 0),
    "%": ("dimensionless", "1", 0.01, 0),
    "count/m2": ("count_density", "count/m2", 1, 0),
    "count/cm2": ("count_density", "count/m2", 10000, 0),
    "count/s": ("count_rate", "count/s", 1, 0),
    "count/min": ("count_rate", "count/s", 1 / 60, 0),
    "count/h": ("count_rate", "count/s", 1 / 3600, 0),
    "degree": ("angle", "degree", 1, 0),
    "px": ("pixel_length", "px", 1, 0),
    "px2": ("pixel_area", "px2", 1, 0),
}


def normalize_quantity(value: float, unit: str, *, difference: bool = False) -> tuple[float, str]:
    if unit not in UNITS or not isfinite(value):
        raise ValueError("A finite quantity and a supported explicit unit are required")
    _, canonical, scale, offset = UNITS[unit]
    normalized = value * scale + (0 if difference else offset)
    if not isfinite(normalized):
        raise ValueError("Normalized quantity exceeds the finite numeric range")
    return normalized, canonical
