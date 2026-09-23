from __future__ import annotations

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.airdata import parse_airdata_csv
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.synchronization import IndexedTelemetrySource, PreferredTelemetrySource


AIRDATA = """time(millisecond),latitude,longitude,height_above_takeoff(meters),gimbal_heading(degrees),gimbal_pitch(degrees),gimbal_roll(degrees),compass_heading(degrees)
10000,22.892814,-109.840571,83.4,265.1,-23.4,0,248.9
10100,22.892808,-109.840590,83.5,265.6,-23.4,0,249.3
"""


def test_airdata_parser_maps_gimbal_and_aircraft_heading_separately() -> None:
    samples = parse_airdata_csv(AIRDATA)
    assert len(samples) == 2
    assert samples[0].time_s == 10.0
    assert samples[0].gimbal_yaw_deg == 265.1
    assert samples[0].aircraft_yaw_deg == 248.9
    assert samples[0].relative_altitude_m == 83.4
    assert samples[0].latitude == 22.892814


def test_airdata_parser_skips_bad_rows_but_requires_valid_telemetry() -> None:
    text = """time(millisecond),gimbal_heading(degrees)
bad,200
100,not-a-number
200,250
"""
    samples = parse_airdata_csv(text)
    assert len(samples) == 1
    assert samples[0].time_s == 0.2
    assert samples[0].gimbal_yaw_deg == 250
    with pytest.raises(ValidationError):
        parse_airdata_csv("time(millisecond),unknown\n0,1\n")


def test_preferred_source_uses_airdata_pose_and_srt_fallback_fields() -> None:
    airdata = IndexedTelemetrySource(parse_airdata_csv(AIRDATA))
    srt = IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=1,
                time_s=0.0,
                frame_number=1,
                latitude=22.0,
                longitude=-109.0,
                relative_altitude_m=80,
                gimbal_yaw_deg=240,
                gimbal_pitch_deg=-20,
                gimbal_roll_deg=1,
                focal_length_mm=24,
            ),
            TelemetrySample(
                sample_index=2,
                time_s=0.1,
                frame_number=2,
                latitude=22.1,
                longitude=-109.1,
                relative_altitude_m=81,
                gimbal_yaw_deg=241,
                gimbal_pitch_deg=-21,
                gimbal_roll_deg=1,
                focal_length_mm=24,
            ),
        ]
    )
    source = PreferredTelemetrySource(
        airdata=airdata,
        srt=srt,
        airdata_time_offset_s=10.0,
        airdata_time_offset_evidence="Flight-log/video start alignment",
    )

    match = source.sample_for_frame(1, 10)
    assert match is not None
    assert match.sample.time_s == 0.1
    assert match.sample.gimbal_yaw_deg == 265.6
    assert match.sample.gimbal_pitch_deg == -23.4
    assert match.sample.latitude == 22.892808
    assert match.sample.relative_altitude_m == 83.5
    assert match.sample.focal_length_mm == 24
    assert match.provenance is not None
    assert match.provenance.gimbal_yaw_source == "airdata"
    assert match.provenance.position_source == "airdata"
    assert match.provenance.airdata_time_offset_s == 10.0


def test_preferred_source_falls_back_to_srt_only_for_missing_airdata_field() -> None:
    airdata = IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=0,
                time_s=10.0,
                latitude=22.0,
                longitude=-109.0,
                relative_altitude_m=83.4,
                gimbal_pitch_deg=-23.4,
                gimbal_roll_deg=0,
            )
        ]
    )
    srt = IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=1,
                time_s=0.0,
                latitude=21.0,
                longitude=-108.0,
                relative_altitude_m=80,
                gimbal_yaw_deg=249.3,
                gimbal_pitch_deg=-20,
                gimbal_roll_deg=1,
            )
        ]
    )
    source = PreferredTelemetrySource(
        airdata=airdata,
        srt=srt,
        airdata_time_offset_s=10.0,
        airdata_time_offset_evidence="Known clip start",
    )
    match = source.sample_for_time(0)
    assert match is not None
    assert match.sample.gimbal_yaw_deg == 249.3
    assert match.sample.gimbal_pitch_deg == -23.4
    assert match.sample.latitude == 22.0
    assert match.provenance is not None
    assert match.provenance.gimbal_yaw_source == "dji_srt"
    assert match.provenance.gimbal_pitch_source == "airdata"
    assert match.provenance.position_source == "airdata"


def test_preferred_source_uses_worst_contributing_sync_delta() -> None:
    airdata = IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=0,
                time_s=10.08,
                gimbal_yaw_deg=265,
            )
        ]
    )
    srt = IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=0,
                time_s=0.01,
                latitude=22,
                longitude=-109,
                gimbal_pitch_deg=-23,
                gimbal_roll_deg=0,
            )
        ]
    )
    source = PreferredTelemetrySource(
        airdata=airdata,
        srt=srt,
        airdata_time_offset_s=10.0,
        airdata_time_offset_evidence="Known clip start",
    )
    match = source.sample_for_time(0)
    assert match is not None
    assert match.delta_s == pytest.approx(0.08)
    assert source.sample_for_time(0, max_delta_s=0.05) is None


def test_nonzero_airdata_offset_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        PreferredTelemetrySource(
            airdata=IndexedTelemetrySource(parse_airdata_csv(AIRDATA)),
            srt=None,
            airdata_time_offset_s=10.0,
        )
