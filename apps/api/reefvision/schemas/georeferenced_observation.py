from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BoundingBoxPixels(BaseModel):
    """Original-frame bounding box used by a geo-referenced observation."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    coordinate_system: Literal["image_pixels_top_left"] = "image_pixels_top_left"


class RepresentativePixel(BaseModel):
    """Pixel projected from image space into geographic space."""

    x: float
    y: float

    method: Literal[
        "explicit",
        "bbox_center",
    ]

    coordinate_system: Literal["image_pixels_top_left"] = "image_pixels_top_left"


class ObservationTimestamp(BaseModel):
    """Video-relative and, when available, absolute observation time."""

    frame_time_s: float = Field(ge=0.0)

    utc: datetime | None = None

    source: Literal[
        "frame_index_fps",
        "video_pts",
        "telemetry",
    ]

    fps: float | None = Field(default=None, gt=0.0)


class PlatformPose(BaseModel):
    """Platform position and orientation used for projection."""

    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-180.0, le=180.0)

    altitude_m: float | None = None
    altitude_datum: str | None = None

    height_above_surface_m: float = Field(gt=0.0)

    yaw_deg: float | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None

    heading_reference: Literal[
        "true_north",
        "magnetic_north",
        "unknown",
    ] = "unknown"


class CameraPose(BaseModel):
    """Camera/gimbal orientation relative to the projection convention."""

    yaw_deg: float
    pitch_deg: float
    roll_deg: float

    orientation_source: Literal[
        "gimbal_telemetry",
        "platform_pose",
        "fixed_extrinsics",
        "derived",
    ]


class ObservationPose(BaseModel):
    platform: PlatformPose
    camera: CameraPose


class CalibrationReference(BaseModel):
    """Calibration snapshot/provenance used to create this observation."""

    calibration_id: UUID | str
    calibration_version: str

    checksum_sha256: str | None = None
    camera_model: str | None = None

    image_width_px: int = Field(gt=0)
    image_height_px: int = Field(gt=0)

    focal_length_x_px: float = Field(gt=0.0)
    focal_length_y_px: float = Field(gt=0.0)

    principal_point_x_px: float
    principal_point_y_px: float

    distortion_model: str | None = None
    zoom_state: float | None = None


class TelemetryReference(BaseModel):
    """Telemetry source and synchronization provenance."""

    source_id: UUID | str

    source_type: Literal[
        "dji_srt",
        "embedded_video",
        "csv",
        "manual",
        "other",
    ]

    sample_index: int | None = Field(default=None, ge=0)

    synchronization_method: Literal[
        "nearest",
        "interpolated",
        "exact",
    ]

    telemetry_time_s: float | None = Field(default=None, ge=0.0)
    telemetry_utc: datetime | None = None

    signed_time_delta_ms: float | None = None
    absolute_time_error_ms: float | None = Field(default=None, ge=0.0)

    within_sync_tolerance: bool
    sync_tolerance_ms: float = Field(ge=0.0)

    field_provenance: dict[str, str | float | None] | None = None


class GeographicLocation(BaseModel):
    """Canonical persisted geographic result."""

    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-180.0, le=180.0)

    crs: Literal["EPSG:4326"] = "EPSG:4326"

    ground_elevation_m: float | None = None


class GeoreferencingUncertainty(BaseModel):
    """Optional uncertainty information for the geographic estimate."""

    available: bool

    method: Literal[
        "not_estimated",
        "propagated_1sigma",
        "empirical_validation",
        "combined",
    ]

    horizontal_sigma_m: float | None = Field(default=None, ge=0.0)
    horizontal_95_m: float | None = Field(default=None, ge=0.0)

    major_axis_95_m: float | None = Field(default=None, ge=0.0)
    minor_axis_95_m: float | None = Field(default=None, ge=0.0)
    major_axis_bearing_deg: float | None = None

    telemetry_component_m: float | None = Field(default=None, ge=0.0)
    pose_component_m: float | None = Field(default=None, ge=0.0)
    height_component_m: float | None = Field(default=None, ge=0.0)
    calibration_component_m: float | None = Field(default=None, ge=0.0)

    reason_unavailable: str | None = None


class GeoreferencingMethod(BaseModel):
    """Versioned algorithm and convention provenance."""

    name: Literal["camera_ray_surface_intersection"] = "camera_ray_surface_intersection"

    version: str

    surface_model: Literal[
        "local_horizontal_plane",
        "elevation_model",
    ]

    representative_pixel_policy_version: str
    synchronization_version: str
    pose_convention_version: str

    implementation: Literal["reefvision"] = "reefvision"


class GeoReferencedObservation(BaseModel):
    """One detection/annotation projected into geographic coordinates."""

    schema_version: str = "1.0.0"

    id: UUID
    project_id: UUID
    video_asset_id: UUID

    detection_id: UUID | None = None
    track_id: UUID | None = None

    frame_index: int = Field(ge=0)
    frame_width_px: int = Field(gt=0)
    frame_height_px: int = Field(gt=0)

    bbox: BoundingBoxPixels
    representative_pixel: RepresentativePixel

    timestamp: ObservationTimestamp
    pose: ObservationPose

    calibration: CalibrationReference
    telemetry: TelemetryReference

    location: GeographicLocation
    uncertainty: GeoreferencingUncertainty

    method: GeoreferencingMethod

    created_at: datetime
