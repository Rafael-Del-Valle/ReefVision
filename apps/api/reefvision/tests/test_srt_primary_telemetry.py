from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.synchronization import (
    IndexedTelemetrySource,
    PreferredTelemetrySource,
)


def _source(sample: TelemetrySample) -> IndexedTelemetrySource:
    return IndexedTelemetrySource([sample])


def test_srt_fields_are_primary_when_both_sources_are_available():
    source = PreferredTelemetrySource(
        srt=_source(
            TelemetrySample(
                sample_index=1,
                time_s=1.0,
                latitude=25.0,
                longitude=-80.0,
                relative_altitude_m=20.0,
                gimbal_yaw_deg=10.0,
                gimbal_pitch_deg=-80.0,
                gimbal_roll_deg=1.0,
            )
        ),
        airdata=_source(
            TelemetrySample(
                sample_index=7,
                time_s=1.0,
                latitude=26.0,
                longitude=-81.0,
                relative_altitude_m=99.0,
                gimbal_yaw_deg=110.0,
                gimbal_pitch_deg=-10.0,
                gimbal_roll_deg=9.0,
            )
        ),
        airdata_time_offset_evidence="Matched flight/video slate.",
    )

    match = source.sample_for_time(1.0)
    assert match is not None
    sample = match.sample

    assert (sample.latitude, sample.longitude) == (25.0, -80.0)
    assert sample.relative_altitude_m == 20.0
    assert sample.gimbal_yaw_deg == 10.0
    assert sample.gimbal_pitch_deg == -80.0
    assert sample.gimbal_roll_deg == 1.0
    assert match.provenance is not None
    assert match.provenance.position_source == "dji_srt"
    assert match.provenance.gimbal_pitch_source == "dji_srt"


def test_aligned_airdata_fills_only_fields_missing_from_srt():
    source = PreferredTelemetrySource(
        srt=_source(
            TelemetrySample(
                sample_index=1,
                time_s=1.0,
                latitude=25.0,
                longitude=-80.0,
                relative_altitude_m=20.0,
                gimbal_yaw_deg=10.0,
                gimbal_pitch_deg=None,
            )
        ),
        airdata=_source(
            TelemetrySample(
                sample_index=7,
                time_s=1.0,
                latitude=26.0,
                longitude=-81.0,
                relative_altitude_m=99.0,
                gimbal_yaw_deg=110.0,
                gimbal_pitch_deg=-30.0,
            )
        ),
        airdata_time_offset_evidence="Matched flight/video slate.",
    )

    match = source.sample_for_time(1.0)
    assert match is not None

    assert match.sample.latitude == 25.0
    assert match.sample.relative_altitude_m == 20.0
    assert match.sample.gimbal_yaw_deg == 10.0
    assert match.sample.gimbal_pitch_deg == -30.0
    assert match.provenance is not None
    assert match.provenance.gimbal_pitch_source == "airdata"


def test_unaligned_airdata_never_changes_projection_fields():
    source = PreferredTelemetrySource(
        srt=_source(
            TelemetrySample(
                sample_index=1,
                time_s=1.0,
                latitude=25.0,
                longitude=-80.0,
                relative_altitude_m=20.0,
                gimbal_yaw_deg=10.0,
                gimbal_pitch_deg=None,
            )
        ),
        airdata=_source(
            TelemetrySample(
                sample_index=7,
                time_s=1.0,
                latitude=26.0,
                longitude=-81.0,
                relative_altitude_m=99.0,
                gimbal_yaw_deg=110.0,
                gimbal_pitch_deg=-30.0,
            )
        ),
    )

    match = source.sample_for_time(1.0)
    assert match is not None

    assert match.sample.latitude == 25.0
    assert match.sample.relative_altitude_m == 20.0
    assert match.sample.gimbal_yaw_deg == 10.0
    assert match.sample.gimbal_pitch_deg is None
    assert match.provenance is not None
    assert match.provenance.gimbal_pitch_source is None
    assert match.provenance.airdata_delta_s is None


def test_unaligned_airdata_only_source_is_not_usable_for_video_projection():
    source = PreferredTelemetrySource(
        srt=None,
        airdata=_source(
            TelemetrySample(
                sample_index=7,
                time_s=1.0,
                latitude=26.0,
                longitude=-81.0,
                relative_altitude_m=99.0,
                gimbal_pitch_deg=-30.0,
            )
        ),
    )

    assert source.sample_for_time(1.0) is None
