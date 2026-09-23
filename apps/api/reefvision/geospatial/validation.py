"""Diagnostic geolocation agreement reports; no dataset or persistence coupling."""

from collections.abc import Sequence
from math import cos, hypot, isfinite, radians, sin, sqrt
from statistics import mean, median, pstdev
from typing import Self

from geographiclib.geodesic import Geodesic
from pydantic import BaseModel, Field, FiniteFloat, model_validator

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.calibration import CameraCalibration
from reefvision.geospatial.geodesy import geodesic_distance_m
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.projection import (
    GeoreferenceResult,
    SurfaceReference,
    georeference_pixel,
)
from reefvision.geospatial.synchronization import TelemetrySource


class GeoreferenceValidationPoint(BaseModel):
    point_id: str
    source_video: str = ""
    frame_index: int | None = Field(default=None, ge=0)
    video_time_s: FiniteFloat | None = Field(default=None, ge=0)
    object_id: str | None = None
    class_name: str | None = None
    source_frame_number: str | None = None
    source_time_value: str | None = None
    pixel_x: FiniteFloat
    pixel_y: FiniteFloat
    latitude: FiniteFloat = Field(ge=-90, le=90)
    longitude: FiniteFloat = Field(ge=-180, le=180)
    reference_height_m: FiniteFloat | None = None
    reference_pitch_deg: FiniteFloat | None = None

    @model_validator(mode="after")
    def has_sync_identifier(self) -> Self:
        if self.frame_index is None and self.video_time_s is None:
            raise ValueError("Annotation requires frame index or relative video time")
        return self


class GeolocationErrorStatistics(BaseModel):
    sample_count: int
    mean_m: float
    median_m: float
    rmse_m: float
    min_m: float
    max_m: float
    p95_m: float
    std_m: float


class GeoreferenceValidationObservation(BaseModel):
    point: GeoreferenceValidationPoint
    result: GeoreferenceResult | None = None
    error_m: float | None = None
    error: str | None = None
    sync_delta_s: float | None = None
    sync_error_s: float | None = None
    video_time_s: float | None = None
    telemetry: TelemetrySample | None = None
    east_error_m: float | None = None
    north_error_m: float | None = None
    distance_from_principal_point_px: float
    distance_from_image_center_px: float
    gimbal_pitch_deg: float | None = None
    digital_zoom_ratio: float | None = None
    height_minus_reference_m: float | None = None


class GeoreferenceValidationReport(BaseModel):
    attempted_count: int
    failed_count: int
    statistics: GeolocationErrorStatistics | None
    observations: list[GeoreferenceValidationObservation]


def summarize_errors(errors_m: Sequence[float]) -> GeolocationErrorStatistics | None:
    if not errors_m:
        return None
    if any(not isfinite(value) or value < 0 for value in errors_m):
        raise ValidationError("Geolocation errors must be finite nonnegative meters")
    ordered = sorted(errors_m)
    p95_index = (len(ordered) - 1) * 0.95
    lower = int(p95_index)
    upper = min(lower + 1, len(ordered) - 1)
    p95 = ordered[lower] + (ordered[upper] - ordered[lower]) * (p95_index - lower)
    return GeolocationErrorStatistics(
        sample_count=len(ordered),
        mean_m=mean(ordered),
        median_m=median(ordered),
        rmse_m=hypot(*ordered) / sqrt(len(ordered)),
        min_m=ordered[0],
        max_m=ordered[-1],
        p95_m=p95,
        std_m=pstdev(ordered),
    )


def evaluate_georeferencing(
    *,
    points: Sequence[GeoreferenceValidationPoint],
    telemetry_source: TelemetrySource,
    calibration: CameraCalibration,
    fps: float,
    surface: SurfaceReference,
    max_delta_s: float,
    max_distance_m: float = 10000,
    video_time_offset_s: float = 0,
    time_offset_evidence: str | None = None,
) -> GeoreferenceValidationReport:
    """Evaluate all selected points, preserving failures and signed synchronization delta.

    Frame indices must already be zero-based source indices. A documented clip
    offset may be supplied; never estimate it by optimizing geographic residuals.
    No real-data accuracy threshold is asserted here.
    """
    if not isfinite(fps) or fps <= 0 or not isfinite(video_time_offset_s):
        raise ValidationError("Validation FPS/offset must be finite and FPS positive")
    if not isfinite(max_delta_s) or max_delta_s < 0:
        raise ValidationError("Validation synchronization limit must be finite and nonnegative")
    if video_time_offset_s and not (time_offset_evidence or "").strip():
        raise ValidationError("A nonzero timing offset requires independent documented evidence")
    rows = []
    errors = []
    for point in points:
        row = GeoreferenceValidationObservation(
            point=point,
            distance_from_principal_point_px=hypot(
                point.pixel_x - calibration.cx_px,
                point.pixel_y - calibration.cy_px,
            ),
            distance_from_image_center_px=hypot(
                point.pixel_x - calibration.width_px / 2,
                point.pixel_y - calibration.height_px / 2,
            ),
        )
        try:
            relative_time = (
                point.frame_index / fps if point.frame_index is not None else point.video_time_s
            )
            assert relative_time is not None
            row.video_time_s = relative_time
            match = telemetry_source.sample_for_time(relative_time + video_time_offset_s)
            if match is None:
                raise ValidationError("No telemetry available for synchronization")
            row.sync_delta_s = match.delta_s
            row.sync_error_s = match.error_s
            row.telemetry = match.sample
            row.gimbal_pitch_deg = match.sample.gimbal_pitch_deg
            row.digital_zoom_ratio = match.sample.digital_zoom_ratio
            if match.error_s > max_delta_s + 1e-12:
                raise ValidationError("Telemetry synchronization error above threshold")
            row.result = georeference_pixel(
                pixel_x=point.pixel_x,
                pixel_y=point.pixel_y,
                telemetry=match.sample,
                calibration=calibration,
                surface=surface,
                max_distance_m=max_distance_m,
            )
            row.error_m = geodesic_distance_m(
                row.result.latitude,
                row.result.longitude,
                point.latitude,
                point.longitude,
            )
            # Signed local residual at the reference point, from GT toward prediction.
            # This is true-East/North, not UTM grid East/North; no zone ambiguity.
            residual = Geodesic.WGS84.Inverse(
                point.latitude, point.longitude, row.result.latitude, row.result.longitude
            )
            azimuth = radians(float(residual["azi1"]))
            row.east_error_m = row.error_m * sin(azimuth)
            row.north_error_m = row.error_m * cos(azimuth)
            if point.reference_height_m is not None:
                row.height_minus_reference_m = row.result.camera_height_m - point.reference_height_m
            errors.append(row.error_m)
        except ValidationError as exc:
            row.error = str(exc)
        rows.append(row)
    return GeoreferenceValidationReport(
        attempted_count=len(rows),
        failed_count=sum(row.error is not None for row in rows),
        statistics=summarize_errors(errors),
        observations=rows,
    )
