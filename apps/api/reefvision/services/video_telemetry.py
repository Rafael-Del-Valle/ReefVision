"""Video telemetry parsing and source-precedence helpers."""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from reefvision.domain.errors import ValidationError

TelemetrySource = Literal["airdata", "dji_srt"]
CameraYawSource = Literal["airdata_gimbal_heading", "srt_gb_yaw"]
HeightSource = Literal["airdata_height_above_takeoff", "srt_rel_alt"]
PositionSource = Literal["airdata", "dji_srt"]

_AIRDATA_REQUIRED_COLUMNS = {
    "time(millisecond)",
    "datetime(utc)",
    "latitude",
    "longitude",
    "height_above_takeoff(meters)",
    "gimbal_heading(degrees)",
    "gimbal_pitch(degrees)",
    "gimbal_roll(degrees)",
}

_SRT_FRAME_RE = re.compile(r"FrameCnt:\s*(?P<value>\d+)")
_SRT_RANGE_RE = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})\s*-->"
)
_SRT_TIMESTAMP_RE = re.compile(r"(?P<value>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)")
_SRT_FIELD_PATTERNS = {
    "latitude": re.compile(r"\[latitude:\s*(?P<value>[-+]?\d+(?:\.\d+)?)\]"),
    "longitude": re.compile(r"\[longitude:\s*(?P<value>[-+]?\d+(?:\.\d+)?)\]"),
    "rel_alt": re.compile(r"\[rel_alt:\s*(?P<value>[-+]?\d+(?:\.\d+)?)"),
    "gb_yaw": re.compile(r"gb_yaw:\s*(?P<value>[-+]?\d+(?:\.\d+)?)"),
    "gb_pitch": re.compile(r"gb_pitch:\s*(?P<value>[-+]?\d+(?:\.\d+)?)"),
    "gb_roll": re.compile(r"gb_roll:\s*(?P<value>[-+]?\d+(?:\.\d+)?)"),
}


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    source: TelemetrySource
    elapsed_seconds: float | None
    absolute_time_utc: datetime | None
    source_timestamp_text: str | None
    frame_counter: int | None
    latitude: float | None
    longitude: float | None
    relative_height_m: float | None
    camera_yaw_deg: float | None
    camera_pitch_deg: float | None
    camera_roll_deg: float | None
    aircraft_heading_deg: float | None = None
    is_video: bool | None = None


@dataclass(frozen=True, slots=True)
class ResolvedTelemetrySample:
    elapsed_seconds: float | None
    absolute_time_utc: datetime | None
    latitude: float | None
    longitude: float | None
    camera_height_m: float | None
    camera_yaw_deg: float | None
    camera_pitch_deg: float | None
    camera_roll_deg: float | None
    project_height_offset_m: float
    position_source: PositionSource | None
    height_source: HeightSource | None
    camera_yaw_source: CameraYawSource | None
    camera_pitch_source: TelemetrySource | None
    camera_roll_source: TelemetrySource | None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise ValidationError(f"Telemetry value is not numeric: {text}") from exc
    if not math.isfinite(number):
        raise ValidationError("Telemetry values must be finite")
    return number


def _normalize_heading(value: float | None) -> float | None:
    if value is None:
        return None
    return value % 360.0


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValidationError("AirData datetime(utc) is required")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"Invalid AirData UTC timestamp: {text}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_bool(value: object) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    if not text:
        return None
    if text in {"1", "true", "yes", "recording"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    return None


def parse_airdata_csv(content: str) -> list[TelemetrySample]:
    """Parse an AirData flight CSV without performing filesystem I/O.

    AirData's gimbal_heading(degrees) is treated as the camera-yaw signal.
    Timestamps are reconstructed the same way DVM does: the first UTC timestamp
    plus each row's time(millisecond) offset.
    """

    reader = csv.DictReader(io.StringIO(content))
    fieldnames = set(reader.fieldnames or [])
    missing = sorted(_AIRDATA_REQUIRED_COLUMNS - fieldnames)
    if missing:
        raise ValidationError(
            "AirData CSV is missing required columns: " + ", ".join(missing)
        )

    rows = list(reader)
    if not rows:
        raise ValidationError("AirData CSV contains no telemetry rows")

    first_utc = _parse_utc(str(rows[0].get("datetime(utc)") or ""))
    samples: list[TelemetrySample] = []
    for row in rows:
        elapsed_ms = _optional_float(row.get("time(millisecond)"))
        if elapsed_ms is None:
            continue
        absolute_time_utc = first_utc + timedelta(milliseconds=elapsed_ms)
        samples.append(
            TelemetrySample(
                source="airdata",
                elapsed_seconds=elapsed_ms / 1000.0,
                absolute_time_utc=absolute_time_utc,
                source_timestamp_text=str(row.get("datetime(utc)") or "").strip() or None,
                frame_counter=None,
                latitude=_optional_float(row.get("latitude")),
                longitude=_optional_float(row.get("longitude")),
                relative_height_m=_optional_float(
                    row.get("height_above_takeoff(meters)")
                ),
                camera_yaw_deg=_normalize_heading(
                    _optional_float(row.get("gimbal_heading(degrees)"))
                ),
                camera_pitch_deg=_optional_float(row.get("gimbal_pitch(degrees)")),
                camera_roll_deg=_optional_float(row.get("gimbal_roll(degrees)")),
                aircraft_heading_deg=_normalize_heading(
                    _optional_float(row.get("compass_heading(degrees)"))
                ),
                is_video=_parse_bool(row.get("isVideo")),
            )
        )
    if not samples:
        raise ValidationError("AirData CSV contains no usable telemetry rows")
    return samples


def _srt_elapsed_seconds(match: re.Match[str]) -> float:
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("ms")) / 1000.0
    )


def _srt_field(block: str, name: str) -> float | None:
    match = _SRT_FIELD_PATTERNS[name].search(block)
    return _optional_float(match.group("value")) if match else None


def parse_dji_srt(content: str) -> list[TelemetrySample]:
    """Parse DJI SRT telemetry for fallback camera pose and position.

    gb_yaw is preserved as a fallback candidate only. Some DJI exports, including
    the validated WhaleDrone flight, behave more like aircraft heading than true
    gimbal/camera heading during pan motion; provenance must therefore be retained.
    """

    normalized = content.replace("\r\n", "\n").strip()
    if not normalized:
        raise ValidationError("DJI SRT telemetry is empty")

    samples: list[TelemetrySample] = []
    for block in re.split(r"\n\s*\n", normalized):
        frame_match = _SRT_FRAME_RE.search(block)
        range_match = _SRT_RANGE_RE.search(block)
        if frame_match is None or range_match is None:
            continue
        timestamp_match = _SRT_TIMESTAMP_RE.search(block)
        samples.append(
            TelemetrySample(
                source="dji_srt",
                elapsed_seconds=_srt_elapsed_seconds(range_match),
                absolute_time_utc=None,
                source_timestamp_text=(
                    timestamp_match.group("value") if timestamp_match else None
                ),
                frame_counter=int(frame_match.group("value")),
                latitude=_srt_field(block, "latitude"),
                longitude=_srt_field(block, "longitude"),
                relative_height_m=_srt_field(block, "rel_alt"),
                camera_yaw_deg=_normalize_heading(_srt_field(block, "gb_yaw")),
                camera_pitch_deg=_srt_field(block, "gb_pitch"),
                camera_roll_deg=_srt_field(block, "gb_roll"),
            )
        )
    if not samples:
        raise ValidationError("DJI SRT contains no usable telemetry samples")
    return samples


def resolve_preferred_telemetry(
    *,
    airdata: TelemetrySample | None,
    srt: TelemetrySample | None,
    project_height_offset_m: float = 0.0,
) -> ResolvedTelemetrySample:
    """Resolve one already-time-aligned AirData/SRT sample pair.

    AirData is preferred for camera pose and position when populated. SRT is the
    fallback. The project height offset is applied after selecting the source
    relative height, so dataset/project-specific datum corrections stay explicit.
    """

    if not math.isfinite(project_height_offset_m):
        raise ValidationError("Project height offset must be finite")

    def choose(
        air_value: float | None,
        srt_value: float | None,
    ) -> tuple[float | None, TelemetrySource | None]:
        if air_value is not None:
            return air_value, "airdata"
        if srt_value is not None:
            return srt_value, "dji_srt"
        return None, None

    latitude: float | None = None
    longitude: float | None = None
    position_source: PositionSource | None = None
    if airdata is not None and airdata.latitude is not None and airdata.longitude is not None:
        latitude, longitude = airdata.latitude, airdata.longitude
        position_source = "airdata"
    elif srt is not None and srt.latitude is not None and srt.longitude is not None:
        latitude, longitude = srt.latitude, srt.longitude
        position_source = "dji_srt"

    raw_height, height_source_base = choose(
        airdata.relative_height_m if airdata else None,
        srt.relative_height_m if srt else None,
    )
    camera_height_m = (
        raw_height + project_height_offset_m if raw_height is not None else None
    )
    height_source: HeightSource | None = None
    if height_source_base == "airdata":
        height_source = "airdata_height_above_takeoff"
    elif height_source_base == "dji_srt":
        height_source = "srt_rel_alt"

    camera_yaw, yaw_source_base = choose(
        airdata.camera_yaw_deg if airdata else None,
        srt.camera_yaw_deg if srt else None,
    )
    camera_yaw_source: CameraYawSource | None = None
    if yaw_source_base == "airdata":
        camera_yaw_source = "airdata_gimbal_heading"
    elif yaw_source_base == "dji_srt":
        camera_yaw_source = "srt_gb_yaw"

    camera_pitch, camera_pitch_source = choose(
        airdata.camera_pitch_deg if airdata else None,
        srt.camera_pitch_deg if srt else None,
    )
    camera_roll, camera_roll_source = choose(
        airdata.camera_roll_deg if airdata else None,
        srt.camera_roll_deg if srt else None,
    )

    timing_sample = airdata or srt
    return ResolvedTelemetrySample(
        elapsed_seconds=timing_sample.elapsed_seconds if timing_sample else None,
        absolute_time_utc=timing_sample.absolute_time_utc if timing_sample else None,
        latitude=latitude,
        longitude=longitude,
        camera_height_m=camera_height_m,
        camera_yaw_deg=camera_yaw,
        camera_pitch_deg=camera_pitch,
        camera_roll_deg=camera_roll,
        project_height_offset_m=project_height_offset_m,
        position_source=position_source,
        height_source=height_source,
        camera_yaw_source=camera_yaw_source,
        camera_pitch_source=camera_pitch_source,
        camera_roll_source=camera_roll_source,
    )
