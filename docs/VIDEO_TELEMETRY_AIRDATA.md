# AirData telemetry precedence for georeferencing

## Scope

This module adds AirData flight-log parsing and a source-precedence contract for
video georeferencing. It does not add maps, detection/track georeferencing, or a
new telemetry upload workflow.

## Source precedence

When an AirData sample and a DJI SRT sample have already been aligned to the
same video time:

1. Prefer AirData `gimbal_heading(degrees)` for camera yaw.
2. Prefer AirData gimbal pitch and roll when populated.
3. Prefer AirData latitude/longitude and height-above-takeoff when populated.
4. Fall back field-by-field to DJI SRT data when AirData is unavailable.
5. Record provenance for every resolved pose field.

DJI SRT `gb_yaw` is explicitly labeled `srt_gb_yaw` when used as a fallback.
It must not be silently treated as equivalent to AirData gimbal heading because
validated DJI datasets can expose aircraft-like heading behavior in that field
during gimbal pan motion.

## Project height offset

Projects now persist `georeference_height_offset_m`, defaulting to `0.0`.

The resolver applies the offset only after choosing the source relative-height
sample:

```text
camera_height_m = selected_relative_height_m + project_height_offset_m
```

This keeps survey-, launch-, and datum-specific corrections explicit. The
WhaleDrone validation used a +5.0 m DVM project/takeoff offset, but ReefVision
does not hard-code that value.

## Parsing

`parse_airdata_csv(content)` parses AirData CSV text using the standard library.
It reconstructs UTC sample timestamps from the first `datetime(utc)` value plus
`time(millisecond)`, matching DroneVideoMeasure's AirData loader behavior.

`parse_dji_srt(content)` is included as a fallback parser for branches that do
not yet contain the newer local SRT telemetry module. When integrating this work
with the newer georeferencing branch, keep the existing tested SRT parser and use
the AirData parser plus `resolve_preferred_telemetry()` source-precedence rules.

Both parsers operate on text and perform no filesystem writes.

## Integration contract

The caller remains responsible for aligning AirData and SRT samples to the same
video frame/time before calling `resolve_preferred_telemetry()`.

Recommended provenance fields to preserve with projected observations are:

- position source
- camera yaw source
- camera pitch source
- camera roll source
- height source
- project height offset

AirData camera yaw should report `airdata_gimbal_heading`. SRT fallback yaw
should report `srt_gb_yaw`.
