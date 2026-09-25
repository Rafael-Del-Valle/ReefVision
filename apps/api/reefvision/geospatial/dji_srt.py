"""Tolerant DJI SRT text parser. No file I/O or inference dependencies."""

import re
from html import unescape
from math import isfinite
from typing import Literal

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.models import TelemetrySample

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_TIME = r"\d{2,}:[0-5]\d:[0-5]\d[,.]\d{3}"
_CUE = re.compile(rf"^\s*(\d+)\s*\n\s*({_TIME})\s*-->\s*({_TIME})[^\n]*\n", re.M)
_BLOCK_START = re.compile(r"^[ \t]*\d+[ \t]*\n", re.M)
_VALUE = re.compile(rf"^({_NUMBER})(?:\s*/\s*({_NUMBER}))?\s*([a-zA-Z/°]*)$")
_FIELD = re.compile(r"(?<![\w.])([a-zA-Z][\w.]*)\s*[:=]\s*([^\]\[\n,]+)")
_ALIASES = {
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon", "lng", "longtitude"),
    "relative_altitude_m": ("rel_alt", "relative_altitude", "relativealtitude", "height", "h"),
    "absolute_altitude_m": ("abs_alt", "absolute_altitude", "absolutealtitude", "gps_altitude"),
    "gimbal_yaw_deg": ("gb_yaw", "gimbal_yaw", "gimbalyawdegree"),
    "gimbal_pitch_deg": ("gb_pitch", "gimbal_pitch", "gimbalpitchdegree"),
    "gimbal_roll_deg": ("gb_roll", "gimbal_roll", "gimbalrolldegree"),
    "aircraft_yaw_deg": ("drone_yaw", "aircraft_yaw", "flightyawdegree", "heading"),
    "aircraft_pitch_deg": ("drone_pitch", "aircraft_pitch", "flightpitchdegree"),
    "aircraft_roll_deg": ("drone_roll", "aircraft_roll", "flightrolldegree"),
    "horizontal_speed_mps": ("hspeed", "h_speed", "horizontal_speed", "h.s"),
    "vertical_speed_mps": ("vspeed", "v_speed", "vertical_speed", "v.s"),
    "iso": ("iso",),
    "shutter_speed_s": ("shutter", "shutter_speed"),
    "focal_length_mm": ("focal_length", "focal_length_mm"),
    "digital_zoom_ratio": ("dzoom_ratio", "digital_zoom", "digital_zoom_ratio", "zoom_ratio"),
    "frame_number": ("frameid", "framecnt", "frame_number", "framecount"),
}


def _seconds(timestamp: str) -> float:
    hours, minutes, seconds = timestamp.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _value(raw: str, field: str) -> float | int | None:
    match = _VALUE.fullmatch(raw.strip())
    if not match:
        return None
    number = float(match[1])
    if match[2]:
        denominator = float(match[2])
        if not denominator or field != "shutter_speed_s":
            return None
        number /= denominator
    unit = match[3].casefold()
    if field.endswith("_mps"):
        factors = {"": 1, "m/s": 1, "mps": 1, "km/h": 1 / 3.6, "mph": 0.44704}
    elif field.endswith("_m"):
        factors = {"": 1, "m": 1, "ft": 0.3048}
    elif field.endswith("_deg") or field in {"latitude", "longitude"}:
        factors = {"": 1, "°": 1, "deg": 1}
    elif field == "shutter_speed_s":
        factors = {"": 1, "s": 1, "ms": 0.001}
    elif field == "focal_length_mm":
        factors = {"": 1, "mm": 1}
    else:
        factors = {"": 1}
    if unit not in factors:
        return None
    number *= factors[unit]
    if not isfinite(number):
        return None
    if field == "latitude" and not -90 <= number <= 90:
        return None
    if field == "longitude" and not -180 <= number <= 180:
        return None
    if field in {"iso", "shutter_speed_s", "focal_length_mm", "digital_zoom_ratio"} and number <= 0:
        return None
    if field in {"horizontal_speed_mps", "frame_number"} and number < 0:
        return None
    if field in {"iso", "frame_number"}:
        return int(number) if number.is_integer() else None
    return number


def _fields(body: str, gps_order: Literal["lon_lat", "lat_lon"]) -> dict[str, object]:
    body = unescape(re.sub(r"<[^>]*>", "", body))
    # Normalize compact labels before parsing; retain the entire value/unit token.
    body = re.sub(
        rf"(?<![\w.])(h\.s|v\.s|iso|ss|h)\s+(?={_NUMBER})",
        r"\1: ",
        body,
        flags=re.I,
    )
    # Split combined brackets, e.g. [rel_alt: 10 abs_alt: 40].
    body = re.sub(r"\s+(?=[a-zA-Z][\w.]*\s*[:=])", "][", body)
    # Legacy tuples also delimit scalar fields, regardless of their order.
    body = re.sub(r"\s+(?=[a-zA-Z][\w.]*\s*\()", "][", body)
    raw = {match[1].casefold(): match[2].strip() for match in _FIELD.finditer(body)}
    values: dict[str, object] = {}
    for field, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in raw:
                raw_value = raw[alias]

                # Legacy focal_length values without an explicit unit are
                # intentionally retained as raw-only. Modern DJI focal_len
                # is handled separately below because M3T SRT uses bare
                # numeric focal indicators.
                if (
                    field == "focal_length_mm"
                    and alias == "focal_length"
                    and not raw_value.casefold().endswith("mm")
                ):
                    continue

                parsed = _value(raw_value, field)
                if parsed is not None:
                    values[field] = parsed
                    break
    if "shutter_speed_s" not in values and "ss" in raw:
        values["shutter_speed_s"] = _value(f"1/{raw['ss']}", "shutter_speed_s")
    focal_source = next(
        (key for key in ("focal_len", "focal_length", "focal_length_mm") if key in raw),
        None,
    )
    focal = raw.get(focal_source) if focal_source is not None else None

    if focal is not None:
        values["focal_length_raw"] = focal

        # DJI focal_len may be a bare numeric focal indicator.
        # Legacy focal_length remains raw-only unless it has an
        # explicit mm suffix.
        if "focal_length_mm" not in values and (
            focal_source == "focal_len"
            or focal_source == "focal_length_mm"
            or focal.casefold().endswith("mm")
        ):
            values["focal_length_mm"] = _value(focal, "focal_length_mm")
    gps = re.search(r"\bGPS\s*\(([^)]+)\)", body, re.I)
    if gps:
        components = gps[1].split(",")
        keys = ["longitude", "latitude"] if gps_order == "lon_lat" else ["latitude", "longitude"]
        for field, component in zip([*keys, "absolute_altitude_m"], components, strict=False):
            value = _value(component, field)
            if value is not None:
                values.setdefault(field, value)
    for prefix, target in (("G", "gimbal"), ("F", "aircraft")):
        attitude = re.search(rf"\b{prefix}\.PRY\s*\(([^)]+)\)", body, re.I)
        if attitude:
            for axis, component in zip(
                ("pitch", "roll", "yaw"), attitude[1].split(","), strict=False
            ):
                field = f"{target}_{axis}_deg"
                value = _value(component, field)
                if value is not None:
                    values.setdefault(field, value)
    # Preserve legacy DJI bare focal_len semantics. M3T-style bare
    # focal_len is only numerically useful when paired with digital-zoom
    # telemetry, which allows base focal = focal_len / dzoom_ratio.
    if (
        "focal_len" in raw
        and values.get("digital_zoom_ratio") is None
        and not raw["focal_len"].casefold().endswith("mm")
    ):
        values.pop("focal_length_mm", None)

    return values


def parse_dji_srt(
    text: str, *, gps_order: Literal["lon_lat", "lat_lon"] = "lon_lat"
) -> list[TelemetrySample]:
    """Skip malformed cues; reject files with no recognized telemetry samples.

    GPS tuple order is explicit because older DJI dialects disagree. No range
    heuristic silently swaps coordinates. Named lat/lon fields are unambiguous.
    """
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    blocks = list(_BLOCK_START.finditer(text))
    samples = []
    for index, block in enumerate(blocks):
        end = blocks[index + 1].start() if index + 1 < len(blocks) else len(text)
        block_text = text[block.start() : end]
        cue = _CUE.match(block_text)
        if cue is None:
            continue
        try:
            start_s, end_s = _seconds(cue[2]), _seconds(cue[3])
            sample_index = int(cue[1])
        except (ValueError, OverflowError):
            continue
        if not isfinite(start_s) or not isfinite(end_s) or end_s < start_s:
            continue
        body = re.split(r"\n\s*\n", block_text[cue.end() :], maxsplit=1)[0]
        values = _fields(body, gps_order)
        if not any(value is not None for key, value in values.items() if key != "frame_number"):
            continue
        samples.append(
            TelemetrySample.model_validate(
                {
                    "sample_index": sample_index,
                    "time_s": start_s,
                    **values,
                }
            )
        )
    if not samples:
        raise ValidationError("No valid DJI telemetry samples found in SRT")
    return samples
