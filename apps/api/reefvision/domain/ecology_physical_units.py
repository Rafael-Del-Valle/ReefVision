"""Shared physical-length unit policy for source-linked ecological evidence.

Units remain user-entered calibration labels; this only enforces dimensional
eligibility. It does not verify calibration accuracy or measurement provenance.
"""

from __future__ import annotations

PHYSICAL_LENGTH_UNITS = frozenset(
    {
        "nm",
        "nanometer",
        "nanometers",
        "nanometre",
        "nanometres",
        "um",
        "μm",
        "micrometer",
        "micrometers",
        "micrometre",
        "micrometres",
        "mm",
        "millimeter",
        "millimeters",
        "millimetre",
        "millimetres",
        "cm",
        "centimeter",
        "centimeters",
        "centimetre",
        "centimetres",
        "m",
        "meter",
        "meters",
        "metre",
        "metres",
        "km",
        "kilometer",
        "kilometers",
        "kilometre",
        "kilometres",
        "in",
        "inch",
        "inches",
        "ft",
        "foot",
        "feet",
        "yd",
        "yard",
        "yards",
    }
)


def is_ecological_physical_length_unit(unit: str) -> bool:
    """Reject pixels, times, arbitrary labels and padded units, without conversion."""
    return bool(unit) and unit == unit.strip() and unit.casefold() in PHYSICAL_LENGTH_UNITS
