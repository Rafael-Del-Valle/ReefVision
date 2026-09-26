"""Deterministic configuration identity for derived georeferencing results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite
from string import hexdigits

from reefvision.geospatial.georeferencing_policy import (
    MINIMUM_RAY_DEPRESSION_DEG,
)

GEOREFERENCING_CONFIGURATION_SCHEMA_VERSION = "georeferencing-configuration-0003"

GEOREFERENCING_ALGORITHM_NAME = "camera_ray_surface_intersection"
GEOREFERENCING_ALGORITHM_VERSION = "opencv-dji-enu-flat-wgs84-v3"
GEOREFERENCING_SURFACE_MODEL = "local_horizontal_plane"
GEOREFERENCING_REPRESENTATIVE_PIXEL_POLICY_VERSION = "1.0.0"
GEOREFERENCING_SYNCHRONIZATION_VERSION = "nearest-frame-time-v1"
GEOREFERENCING_POSE_CONVENTION_VERSION = "absolute-gimbal-ned-to-enu-v1"
GEOREFERENCING_TELEMETRY_SELECTION_VERSION = "srt-primary-explicit-airdata-fallback-v2"


class GeoreferencingConfigurationError(ValueError):
    """The current configuration cannot be fingerprinted safely."""


@dataclass(frozen=True, slots=True)
class GeoreferencingConfigurationSnapshot:
    """Coordinate-affecting and provenance-critical configuration."""

    video_id: str
    video_sha256: str
    video_fps: float

    srt_source_id: str | None
    srt_sample_count: int | None

    airdata_source_id: str | None
    airdata_sample_count: int | None
    airdata_time_offset_s: float
    airdata_alignment_evidence: str | None

    calibration_checksum_sha256: str
    calibration_revision: int

    mavic3t_dynamic_camera_version: str
    mavic3t_calibration_bundle_sha256: str

    project_height_offset_m: float
    project_height_evidence: str

    max_telemetry_delta_s: float

    minimum_ray_depression_deg: float = MINIMUM_RAY_DEPRESSION_DEG
    algorithm_name: str = GEOREFERENCING_ALGORITHM_NAME
    algorithm_version: str = GEOREFERENCING_ALGORITHM_VERSION
    surface_model: str = GEOREFERENCING_SURFACE_MODEL
    representative_pixel_policy_version: str = GEOREFERENCING_REPRESENTATIVE_PIXEL_POLICY_VERSION
    synchronization_version: str = GEOREFERENCING_SYNCHRONIZATION_VERSION
    pose_convention_version: str = GEOREFERENCING_POSE_CONVENTION_VERSION
    telemetry_selection_version: str = GEOREFERENCING_TELEMETRY_SELECTION_VERSION


def _required_text(value: str, *, field_name: str) -> str:
    rendered = str(value).strip()

    if not rendered:
        raise GeoreferencingConfigurationError(f"{field_name} cannot be blank")

    return rendered


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    rendered = str(value).strip()

    return rendered or None


def _finite_float(value: float, *, field_name: str) -> float:
    numeric = float(value)

    if not isfinite(numeric):
        raise GeoreferencingConfigurationError(f"{field_name} must be finite")

    # Avoid distinct hashes for semantically identical -0.0 and 0.0.
    return 0.0 if numeric == 0.0 else numeric


def _sha256_text(value: str, *, field_name: str) -> str:
    rendered = _required_text(
        value,
        field_name=field_name,
    ).lower()

    if len(rendered) != 64 or any(character not in hexdigits for character in rendered):
        raise GeoreferencingConfigurationError(f"{field_name} must be a 64-character SHA-256 value")

    return rendered


def _sample_count(
    value: int | None,
    *,
    field_name: str,
) -> int | None:
    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int):
        raise GeoreferencingConfigurationError(f"{field_name} must be an integer")

    if value < 0:
        raise GeoreferencingConfigurationError(f"{field_name} cannot be negative")

    return value


def canonical_configuration_payload(
    snapshot: GeoreferencingConfigurationSnapshot,
) -> dict[str, object]:
    """Return the stable scientific configuration represented by a hash."""
    if snapshot.calibration_revision < 1:
        raise GeoreferencingConfigurationError("calibration_revision must be at least 1")

    return {
        "schema_version": (GEOREFERENCING_CONFIGURATION_SCHEMA_VERSION),
        "video": {
            "id": _required_text(
                snapshot.video_id,
                field_name="video_id",
            ),
            "sha256": _sha256_text(
                snapshot.video_sha256,
                field_name="video_sha256",
            ),
            "fps": _finite_float(
                snapshot.video_fps,
                field_name="video_fps",
            ),
        },
        "telemetry": {
            "selection_version": _required_text(
                snapshot.telemetry_selection_version,
                field_name="telemetry_selection_version",
            ),
            "srt": {
                "source_id": _optional_text(snapshot.srt_source_id),
                "sample_count": _sample_count(
                    snapshot.srt_sample_count,
                    field_name="srt_sample_count",
                ),
            },
            "airdata": {
                "source_id": _optional_text(snapshot.airdata_source_id),
                "sample_count": _sample_count(
                    snapshot.airdata_sample_count,
                    field_name="airdata_sample_count",
                ),
                "time_offset_s": _finite_float(
                    snapshot.airdata_time_offset_s,
                    field_name="airdata_time_offset_s",
                ),
                "alignment_evidence": _optional_text(snapshot.airdata_alignment_evidence),
            },
            "max_delta_s": _finite_float(
                snapshot.max_telemetry_delta_s,
                field_name="max_telemetry_delta_s",
            ),
        },
        "calibration": {
            "checksum_sha256": _sha256_text(
                snapshot.calibration_checksum_sha256,
                field_name="calibration_checksum_sha256",
            ),
            "revision": snapshot.calibration_revision,
        },
        "dynamic_camera": {
            "mavic3t_version": _required_text(
                snapshot.mavic3t_dynamic_camera_version,
                field_name="mavic3t_dynamic_camera_version",
            ),
            "mavic3t_calibration_bundle_sha256": _sha256_text(
                snapshot.mavic3t_calibration_bundle_sha256,
                field_name="mavic3t_calibration_bundle_sha256",
            ),
        },
        "surface_reference": {
            "height_offset_m": _finite_float(
                snapshot.project_height_offset_m,
                field_name="project_height_offset_m",
            ),
            "evidence": _required_text(
                snapshot.project_height_evidence,
                field_name="project_height_evidence",
            ),
        },
        "algorithm": {
            "name": _required_text(
                snapshot.algorithm_name,
                field_name="algorithm_name",
            ),
            "version": _required_text(
                snapshot.algorithm_version,
                field_name="algorithm_version",
            ),
            "surface_model": _required_text(
                snapshot.surface_model,
                field_name="surface_model",
            ),
            "minimum_ray_depression_deg": _finite_float(
                snapshot.minimum_ray_depression_deg,
                field_name="minimum_ray_depression_deg",
            ),
            "representative_pixel_policy_version": (
                _required_text(
                    snapshot.representative_pixel_policy_version,
                    field_name=("representative_pixel_policy_version"),
                )
            ),
            "synchronization_version": _required_text(
                snapshot.synchronization_version,
                field_name="synchronization_version",
            ),
            "pose_convention_version": _required_text(
                snapshot.pose_convention_version,
                field_name="pose_convention_version",
            ),
        },
    }


def georeferencing_configuration_hash(
    snapshot: GeoreferencingConfigurationSnapshot,
) -> str:
    """Return a deterministic SHA-256 identity for current configuration."""
    payload = canonical_configuration_payload(snapshot)

    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
