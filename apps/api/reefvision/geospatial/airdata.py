"""AirData flight-log parser normalized to ReefVision telemetry samples."""

from __future__ import annotations

import csv
import io
from math import isfinite

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.models import TelemetrySample

_TIME_COLUMN = "time(millisecond)"
_FIELD_COLUMNS = {
    "latitude": "latitude",
    "longitude": "longitude",
    "relative_altitude_m": "height_above_takeoff(meters)",
    "gimbal_yaw_deg": "gimbal_heading(degrees)",
    "gimbal_pitch_deg": "gimbal_pitch(degrees)",
    "gimbal_roll_deg": "gimbal_roll(degrees)",
    "aircraft_yaw_deg": "compass_heading(degrees)",
}


def _optional_float(value: object) -> float | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if isfinite(parsed) else None


def parse_airdata_csv(text: str) -> list[TelemetrySample]:
    """Parse an AirData CSV using flight-relative milliseconds as sample time.

    AirData gimbal_heading(degrees) is the absolute camera-yaw signal.
    compass_heading(degrees) is retained separately as aircraft yaw.

    Returned times are flight-relative, not automatically video-relative.
    Callers must provide an independently established AirData-to-video offset
    when combining these samples with video-relative SRT telemetry.
    """

    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        raw_fieldnames = reader.fieldnames or []
        fieldnames = [name.strip() for name in raw_fieldnames if name is not None]
        if len(fieldnames) != len(raw_fieldnames) or len(fieldnames) != len(set(fieldnames)):
            raise ValidationError("AirData CSV header contains missing or duplicate columns")
        reader.fieldnames = fieldnames
        columns = set(fieldnames)
    except csv.Error as exc:
        raise ValidationError("Malformed AirData CSV header") from exc
    if _TIME_COLUMN not in columns:
        raise ValidationError("AirData CSV is missing time(millisecond)")
    recognized = {column for column in _FIELD_COLUMNS.values() if column in columns}
    if not recognized:
        raise ValidationError("AirData CSV contains no recognized telemetry fields")

    samples: list[TelemetrySample] = []
    try:
        for row_index, row in enumerate(reader):
            elapsed_ms = _optional_float(row.get(_TIME_COLUMN))
            if elapsed_ms is None or elapsed_ms < 0:
                continue
            values: dict[str, object] = {}
            for field, column in _FIELD_COLUMNS.items():
                value = _optional_float(row.get(column))
                if value is not None:
                    values[field] = value
            if not values:
                continue
            try:
                samples.append(
                    TelemetrySample.model_validate(
                        {
                            "sample_index": row_index,
                            "time_s": elapsed_ms / 1000.0,
                            **values,
                        }
                    )
                )
            except ValueError:
                # One malformed row must not poison otherwise valid flight telemetry.
                continue
    except csv.Error as exc:
        raise ValidationError("Malformed AirData CSV rows") from exc

    if not samples:
        raise ValidationError("No valid AirData telemetry samples found in CSV")
    return samples
