"""Task 19B deterministic georeferencing configuration hashing."""

from __future__ import annotations

from dataclasses import replace

import pytest

from reefvision.services.georeferencing_configuration import (
    GeoreferencingConfigurationError,
    GeoreferencingConfigurationSnapshot,
    canonical_configuration_payload,
    georeferencing_configuration_hash,
)


def snapshot() -> GeoreferencingConfigurationSnapshot:
    return GeoreferencingConfigurationSnapshot(
        video_id="video-1",
        video_sha256="a" * 64,
        video_fps=29.97,
        srt_source_id="managed/video-1.srt",
        srt_sample_count=1000,
        airdata_source_id="managed/video-1.airdata.csv",
        airdata_sample_count=1000,
        airdata_time_offset_s=1.25,
        airdata_alignment_evidence="Independent source alignment",
        calibration_checksum_sha256="b" * 64,
        calibration_revision=3,
        project_height_offset_m=5.0,
        project_height_evidence="Surveyed takeoff height",
        max_telemetry_delta_s=0.1,
    )


def test_hash_is_deterministic() -> None:
    first = georeferencing_configuration_hash(snapshot())
    second = georeferencing_configuration_hash(snapshot())

    assert first == second
    assert len(first) == 64


@pytest.mark.parametrize(
    ("field_name", "new_value"),
    [
        ("calibration_checksum_sha256", "c" * 64),
        ("calibration_revision", 4),
        ("project_height_offset_m", 6.0),
        (
            "project_height_evidence",
            "Revised surveyed datum",
        ),
        ("airdata_time_offset_s", 1.5),
        (
            "airdata_alignment_evidence",
            "Revised independent alignment",
        ),
        (
            "algorithm_version",
            "opencv-dji-enu-flat-wgs84-v2",
        ),
        (
            "synchronization_version",
            "nearest-frame-time-v2",
        ),
        (
            "pose_convention_version",
            "absolute-gimbal-ned-to-enu-v2",
        ),
        ("max_telemetry_delta_s", 0.2),
        ("srt_source_id", "managed/replacement.srt"),
        (
            "airdata_source_id",
            "managed/replacement.airdata.csv",
        ),
        ("video_fps", 30.0),
    ],
)
def test_coordinate_or_provenance_changes_change_hash(
    field_name: str,
    new_value: object,
) -> None:
    current = snapshot()

    changed = replace(
        current,
        **{field_name: new_value},
    )

    assert georeferencing_configuration_hash(current) != georeferencing_configuration_hash(changed)


def test_whitespace_is_normalized_for_evidence() -> None:
    current = snapshot()

    changed = replace(
        current,
        project_height_evidence=("  Surveyed takeoff height  "),
        airdata_alignment_evidence=("  Independent source alignment "),
    )

    assert georeferencing_configuration_hash(current) == georeferencing_configuration_hash(changed)


def test_negative_zero_is_canonicalized() -> None:
    current = replace(
        snapshot(),
        airdata_time_offset_s=0.0,
        project_height_offset_m=0.0,
    )

    changed = replace(
        current,
        airdata_time_offset_s=-0.0,
        project_height_offset_m=-0.0,
    )

    assert georeferencing_configuration_hash(current) == georeferencing_configuration_hash(changed)


def test_nonfinite_values_are_rejected() -> None:
    changed = replace(
        snapshot(),
        airdata_time_offset_s=float("nan"),
    )

    with pytest.raises(
        GeoreferencingConfigurationError,
        match="airdata_time_offset_s must be finite",
    ):
        georeferencing_configuration_hash(changed)


def test_invalid_calibration_revision_is_rejected() -> None:
    changed = replace(
        snapshot(),
        calibration_revision=0,
    )

    with pytest.raises(
        GeoreferencingConfigurationError,
        match="calibration_revision",
    ):
        georeferencing_configuration_hash(changed)


def test_payload_exposes_versioned_algorithm_contract() -> None:
    payload = canonical_configuration_payload(snapshot())

    algorithm = payload["algorithm"]

    assert isinstance(algorithm, dict)
    assert algorithm["version"] == ("opencv-dji-enu-flat-wgs84-v1")
    assert algorithm["surface_model"] == ("local_horizontal_plane")
    assert algorithm["synchronization_version"] == ("nearest-frame-time-v1")
