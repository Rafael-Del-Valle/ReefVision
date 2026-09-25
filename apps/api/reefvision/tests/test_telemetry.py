from pathlib import Path

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.dji_srt import parse_dji_srt
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.synchronization import IndexedTelemetrySource, PreferredTelemetrySource
from reefvision.storage.telemetry import find_paired_srt, load_dji_srt

FIXTURES = Path(__file__).parent / "fixtures" / "telemetry"


def test_modern_fields_and_missing_values():
    samples = load_dji_srt(FIXTURES / "modern.SRT").samples
    assert len(samples) == 3
    first = samples[0]
    assert first.sample_index == 1 and first.frame_number == 1 and first.time_s == 0
    assert (first.latitude, first.longitude) == (25.125, -80.25)
    assert (first.relative_altitude_m, first.absolute_altitude_m) == (12.5, 42.5)
    assert (first.gimbal_yaw_deg, first.gimbal_pitch_deg, first.gimbal_roll_deg) == (179, -90, 0.5)
    assert (first.aircraft_yaw_deg, first.aircraft_pitch_deg, first.aircraft_roll_deg) == (
        180,
        -2,
        1,
    )
    assert (first.horizontal_speed_mps, first.vertical_speed_mps) == (3.5, -0.5)
    assert first.iso == 100 and first.shutter_speed_s == 0.001
    assert first.focal_length_mm == 24 and first.digital_zoom_ratio == 1.5
    assert samples[1].latitude == 25.126 and samples[1].relative_altitude_m == 13
    assert samples[1].gimbal_pitch_deg is None and samples[1].frame_number is None
    assert samples[1].iso is None and samples[1].absolute_altitude_m is None


def test_legacy_variant_and_units():
    first, second = load_dji_srt(FIXTURES / "legacy.srt").samples
    assert (first.latitude, first.longitude, first.absolute_altitude_m) == (25.125, -80.25, 42.5)
    assert first.relative_altitude_m == 12.5
    assert first.horizontal_speed_mps == pytest.approx(3.5)
    assert first.vertical_speed_mps == -0.5
    assert first.gimbal_pitch_deg == -90 and first.aircraft_yaw_deg == 180
    assert first.iso == 200 and first.shutter_speed_s == 0.002
    assert second.gimbal_pitch_deg == -89
    assert second.focal_length_raw == "240" and second.focal_length_mm is None


@pytest.mark.parametrize("text", ["", "not an srt", "1\n00:00:00,000 --> 00:00:01,000\nHello"])
def test_empty_or_non_telemetry_is_useful_error(text):
    with pytest.raises(ValidationError, match="telemetry"):
        parse_dji_srt(text)


def test_malformed_blocks_and_values_do_not_poison_valid_samples():
    valid = (FIXTURES / "modern.SRT").read_text()
    text = "9\nbad timestamp\n[latitude: 20]\n\n" + valid
    text += (
        "\n\n4\n00:00:15,000 --> 00:00:16,000\n"
        "[latitude: 200] [longitude: nan] [iso: 100] [shutter: 1/0]"
    )
    samples = parse_dji_srt(text)
    assert len(samples) == 4
    assert samples[-1].latitude is None and samples[-1].longitude is None
    assert samples[-1].shutter_speed_s is None


@pytest.mark.parametrize("suffix", [".SRT", ".srt", ".SrT"])
def test_pairing_case_insensitive(tmp_path, suffix):
    video = tmp_path / "DJI_0001.MP4"
    video.touch()
    sidecar = tmp_path / ("dji_0001" + suffix)
    sidecar.touch()
    assert find_paired_srt(video) == sidecar


def test_pairing_absent_and_unrelated(tmp_path):
    video = tmp_path / "fish.mp4"
    (tmp_path / "other.srt").touch()
    assert find_paired_srt(video) is None


@pytest.mark.parametrize(
    ("time_s", "matched", "delta"),
    [(0, 0, 0), (0.1, 0.1, 0), (0.08, 0.1, 0.02), (0.05, 0, -0.05), (4, 0.1, -3.9), (20, 10, -10)],
)
def test_nearest_time_endpoints_ties_and_gap(time_s, matched, delta):
    source = load_dji_srt(FIXTURES / "modern.SRT")
    match = source.sample_for_time(time_s)
    assert match.sample.time_s == matched
    assert match.delta_s == pytest.approx(delta)
    assert match.error_s == pytest.approx(abs(delta))


def test_srt_is_primary_and_airdata_requires_explicit_alignment_for_fallback():
    srt = IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=1,
                time_s=0,
                latitude=25.0,
                longitude=-80.0,
                gimbal_pitch_deg=-80.0,
            )
        ]
    )
    airdata = IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=2,
                time_s=0,
                latitude=30.0,
                longitude=-70.0,
                gimbal_pitch_deg=-20.0,
                gimbal_yaw_deg=123.0,
            )
        ]
    )

    unaligned = PreferredTelemetrySource(
        airdata=airdata,
        srt=srt,
        airdata_time_offset_s=0.0,
        airdata_time_offset_evidence=None,
    )
    unaligned_match = unaligned.sample_for_time(0)
    assert unaligned_match is not None
    assert (unaligned_match.sample.latitude, unaligned_match.sample.longitude) == (25.0, -80.0)
    assert unaligned_match.sample.gimbal_pitch_deg == -80.0
    assert unaligned_match.sample.gimbal_yaw_deg is None
    assert unaligned_match.provenance is not None
    assert unaligned_match.provenance.position_source == "dji_srt"
    assert unaligned_match.provenance.gimbal_pitch_source == "dji_srt"
    assert unaligned_match.provenance.gimbal_yaw_source is None

    aligned = PreferredTelemetrySource(
        airdata=airdata,
        srt=srt,
        airdata_time_offset_s=0.0,
        airdata_time_offset_evidence="Independent video/flight alignment",
    )
    aligned_match = aligned.sample_for_time(0)
    assert aligned_match is not None
    assert (aligned_match.sample.latitude, aligned_match.sample.longitude) == (25.0, -80.0)
    assert aligned_match.sample.gimbal_pitch_deg == -80.0
    assert aligned_match.sample.gimbal_yaw_deg == 123.0
    assert aligned_match.provenance is not None
    assert aligned_match.provenance.position_source == "dji_srt"
    assert aligned_match.provenance.gimbal_pitch_source == "dji_srt"
    assert aligned_match.provenance.gimbal_yaw_source == "airdata"


def test_non_integer_fps_and_first_sample_after_video_start():
    source = IndexedTelemetrySource([TelemetrySample(sample_index=1, time_s=1.001, latitude=25)])
    assert source.sample_for_frame(30, 30000 / 1001).error_s == pytest.approx(0)
    assert source.sample_for_frame(0, 29.97).delta_s == 1.001
    assert source.sample_for_time(30, max_delta_s=0.5) is None


@pytest.mark.parametrize(
    ("frame", "fps"), [(-1, 30), (1, 0), (1, -1), (1, float("nan")), (1, float("inf"))]
)
def test_invalid_frame_requests(frame, fps):
    source = load_dji_srt(FIXTURES / "modern.SRT")
    with pytest.raises(ValidationError):
        source.sample_for_frame(frame, fps)


def test_sorting_duplicates_and_empty_source():
    source = IndexedTelemetrySource(
        [
            TelemetrySample(sample_index=3, time_s=2),
            TelemetrySample(sample_index=1, time_s=1),
            TelemetrySample(sample_index=2, time_s=1),
        ]
    )
    assert source.sample_for_time(1).sample.sample_index == 1
    assert source.sample_for_time(3).sample.sample_index == 3
    assert IndexedTelemetrySource([]).sample_for_frame(0, 30) is None


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
def test_file_encoding_and_crlf(tmp_path, encoding):
    path = tmp_path / "telemetry.srt"
    text = (FIXTURES / "modern.SRT").read_text().replace("\n", "\r\n")
    path.write_bytes(text.encode(encoding))
    assert len(load_dji_srt(path).samples) == 3


def test_bad_cue_after_good_cue_does_not_overwrite_coordinates():
    text = (
        "1\n00:00:00,000 --> 00:00:00,100\n[latitude: 25]\n\n"
        "2\n00:99:00,000 --> 00:99:01,000\n[latitude: 55]\n\n"
        "3\n00:00:02,000 --> 00:00:01,000\n[latitude: 65]\n\n"
    )
    samples = parse_dji_srt(text)
    assert len(samples) == 1
    assert samples[0].latitude == 25


def test_explicit_legacy_gps_order_and_uninterpreted_fields():
    samples = parse_dji_srt(
        "1\n00:00:00,000 --> 00:00:00,100\n"
        "GPS(25,-80,42) BAROMETER(15) [yaw: 45] [focal_len: 24mm]",
        gps_order="lat_lon",
    )
    assert samples[0].latitude == 25 and samples[0].longitude == -80
    assert samples[0].focal_length_mm == 24
    assert samples[0].relative_altitude_m is None
    assert samples[0].aircraft_yaw_deg is None and samples[0].gimbal_yaw_deg is None


@pytest.mark.parametrize("time_s", [-1, float("nan"), float("inf")])
def test_invalid_relative_time(time_s):
    with pytest.raises(ValidationError):
        IndexedTelemetrySource([]).sample_for_time(time_s)


@pytest.mark.parametrize("delta", [-1, float("nan"), float("inf")])
def test_invalid_gap_limit(delta):
    with pytest.raises(ValidationError):
        IndexedTelemetrySource([]).sample_for_time(0, max_delta_s=delta)


def test_missing_unreadable_or_oversized_source(tmp_path, monkeypatch):
    from reefvision.storage import telemetry

    path = tmp_path / "absent.srt"
    with pytest.raises(ValidationError, match="missing or unreadable"):
        load_dji_srt(path)
    path.write_bytes(b"\x80\x81")
    with pytest.raises(ValidationError, match="UTF"):
        load_dji_srt(path)
    monkeypatch.setattr(telemetry, "MAX_SRT_BYTES", 10)
    path.write_bytes(b"a" * 11)
    with pytest.raises(ValidationError, match="limit"):
        load_dji_srt(path)


def test_legacy_units_are_not_silently_truncated():
    sample = parse_dji_srt(
        "1\n00:00:00,000 --> 00:00:01,000\nGPS(-80,25,40) H 100ft H.S 20mph V.S 5ft/s"
    )[0]
    assert sample.relative_altitude_m == 30.48
    assert sample.horizontal_speed_mps == pytest.approx(8.9408)
    assert sample.vertical_speed_mps is None


def test_malformed_adjacent_cue_without_blank_separator_is_isolated():
    samples = parse_dji_srt(
        "1\n00:00:00,000 --> 00:00:01,000\n[latitude: 25] [longitude: -80]\n"
        "2\nbad timestamp\n[latitude: 50] [longitude: -10]"
    )
    assert len(samples) == 1
    assert samples[0].latitude == 25 and samples[0].longitude == -80


@pytest.mark.parametrize("part", ["hours", "index"])
def test_extreme_numeric_cues_are_domain_errors(part):
    index = "9" * 4301 if part == "index" else "1"
    hours = "9" * 310 if part == "hours" else "00"
    with pytest.raises(ValidationError, match="telemetry"):
        parse_dji_srt(f"{index}\n{hours}:00:00,000 --> {hours}:00:01,000\n[latitude: 25]")


def test_reordered_legacy_scalars_before_tuples():
    sample = parse_dji_srt(
        "1\n00:00:00,000 --> 00:00:01,000\n"
        "ISO 200 SS 500 G.PRY(-90,0,179) "
        "H 12.5m H.S 12.6km/h V.S -0.5m/s GPS(-80,25,40)"
    )[0]
    assert sample.shutter_speed_s == 0.002 and sample.iso == 200
    assert sample.relative_altitude_m == 12.5
    assert sample.horizontal_speed_mps == pytest.approx(3.5)
    assert sample.vertical_speed_mps == -0.5
    assert sample.gimbal_pitch_deg == -90 and sample.longitude == -80
