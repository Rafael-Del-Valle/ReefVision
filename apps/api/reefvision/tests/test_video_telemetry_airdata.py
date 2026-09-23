from datetime import UTC, datetime

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.video_telemetry import (
    parse_airdata_csv,
    parse_dji_srt,
    resolve_preferred_telemetry,
)


AIRDATA = """time(millisecond),datetime(utc),latitude,longitude,height_above_takeoff(meters),gimbal_heading(degrees),gimbal_pitch(degrees),gimbal_roll(degrees),compass_heading(degrees),isVideo
0,2026-01-16 14:49:50,22.892814,-109.840571,83.4,265.1,-23.4,0,248.9,1
600,2026-01-16 14:49:51,22.892808,-109.840590,83.5,265.6,-23.4,0,249.3,1
"""

SRT = """1
00:00:17,649 --> 00:00:17,682
<font size="28">FrameCnt: 530, DiffTime: 33ms
2026-01-16 15:50:12.968
[latitude: 22.892808] [longitude: -109.840590] [rel_alt: 83.534 abs_alt: 53.867] [gb_yaw: -110.7 gb_pitch: -23.4 gb_roll: 0.0] </font>
"""


def test_airdata_parser_uses_gimbal_heading_as_camera_yaw() -> None:
    samples = parse_airdata_csv(AIRDATA)

    assert len(samples) == 2
    assert samples[0].camera_yaw_deg == 265.1
    assert samples[0].aircraft_heading_deg == 248.9
    assert samples[0].relative_height_m == 83.4
    assert samples[0].absolute_time_utc == datetime(
        2026, 1, 16, 14, 49, 50, tzinfo=UTC
    )
    assert samples[1].absolute_time_utc == datetime(
        2026, 1, 16, 14, 49, 50, 600000, tzinfo=UTC
    )


def test_dji_srt_parser_normalizes_signed_gb_yaw_for_fallback() -> None:
    samples = parse_dji_srt(SRT)

    assert len(samples) == 1
    assert samples[0].frame_counter == 530
    assert samples[0].camera_yaw_deg == pytest.approx(249.3)
    assert samples[0].camera_pitch_deg == -23.4
    assert samples[0].relative_height_m == 83.534


def test_airdata_pose_wins_over_srt_and_height_offset_is_explicit() -> None:
    airdata = parse_airdata_csv(AIRDATA)[0]
    srt = parse_dji_srt(SRT)[0]

    resolved = resolve_preferred_telemetry(
        airdata=airdata,
        srt=srt,
        project_height_offset_m=5.0,
    )

    assert resolved.camera_yaw_deg == 265.1
    assert resolved.camera_yaw_source == "airdata_gimbal_heading"
    assert resolved.camera_pitch_source == "airdata"
    assert resolved.camera_roll_source == "airdata"
    assert resolved.position_source == "airdata"
    assert resolved.height_source == "airdata_height_above_takeoff"
    assert resolved.camera_height_m == 88.4
    assert resolved.project_height_offset_m == 5.0
    assert resolved.elapsed_seconds == 17.649
    assert resolved.absolute_time_utc == datetime(
        2026, 1, 16, 14, 49, 50, tzinfo=UTC
    )


def test_srt_is_used_when_airdata_is_unavailable() -> None:
    srt = parse_dji_srt(SRT)[0]

    resolved = resolve_preferred_telemetry(
        airdata=None,
        srt=srt,
        project_height_offset_m=0.0,
    )

    assert resolved.camera_yaw_deg == pytest.approx(249.3)
    assert resolved.camera_yaw_source == "srt_gb_yaw"
    assert resolved.position_source == "dji_srt"
    assert resolved.height_source == "srt_rel_alt"
    assert resolved.camera_height_m == 83.534


def test_non_finite_project_height_offset_is_rejected() -> None:
    with pytest.raises(ValidationError):
        resolve_preferred_telemetry(
            airdata=None,
            srt=parse_dji_srt(SRT)[0],
            project_height_offset_m=float("nan"),
        )



def test_srt_yaw_fills_only_missing_airdata_yaw() -> None:
    airdata_without_yaw = parse_airdata_csv(
        """time(millisecond),datetime(utc),latitude,longitude,height_above_takeoff(meters),gimbal_heading(degrees),gimbal_pitch(degrees),gimbal_roll(degrees)
0,2026-01-16 14:49:50,22.892814,-109.840571,83.4,,-23.4,0
"""
    )[0]
    srt = parse_dji_srt(SRT)[0]

    resolved = resolve_preferred_telemetry(
        airdata=airdata_without_yaw,
        srt=srt,
        project_height_offset_m=5.0,
    )

    assert resolved.camera_yaw_deg == pytest.approx(249.3)
    assert resolved.camera_yaw_source == "srt_gb_yaw"
    assert resolved.camera_pitch_source == "airdata"
    assert resolved.position_source == "airdata"
    assert resolved.height_source == "airdata_height_above_takeoff"
    assert resolved.camera_height_m == 88.4
