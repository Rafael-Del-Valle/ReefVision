from datetime import UTC, datetime
from uuid import uuid4

from reefvision.schemas.georeferenced_observation import (
    BoundingBoxPixels,
    CalibrationReference,
    CameraPose,
    GeographicLocation,
    GeoReferencedObservation,
    GeoreferencingMethod,
    GeoreferencingUncertainty,
    ObservationPose,
    ObservationTimestamp,
    PlatformPose,
    RepresentativePixel,
    TelemetryReference,
)


def test_geo_referenced_observation_schema() -> None:
    observation = GeoReferencedObservation(
        id=uuid4(),
        project_id=uuid4(),
        video_asset_id=uuid4(),
        detection_id=uuid4(),
        track_id=uuid4(),
        frame_index=14862,
        frame_width_px=3840,
        frame_height_px=2160,
        bbox=BoundingBoxPixels(
            x_min=1260.4,
            y_min=843.2,
            x_max=1542.8,
            y_max=1094.6,
        ),
        representative_pixel=RepresentativePixel(
            x=1401.6,
            y=968.9,
            method="bbox_center",
        ),
        timestamp=ObservationTimestamp(
            frame_time_s=495.4,
            utc=datetime(2026, 1, 16, 15, 58, 37, 400000, tzinfo=UTC),
            source="frame_index_fps",
            fps=30.0,
        ),
        pose=ObservationPose(
            platform=PlatformPose(
                latitude_deg=32.0,
                longitude_deg=-79.0,
                altitude_m=42.6,
                altitude_datum="telemetry_reported",
                height_above_surface_m=37.655,
                yaw_deg=127.4,
                pitch_deg=0.0,
                roll_deg=0.0,
                heading_reference="true_north",
            ),
            camera=CameraPose(
                yaw_deg=0.0,
                pitch_deg=-90.0,
                roll_deg=0.0,
                orientation_source="gimbal_telemetry",
            ),
        ),
        calibration=CalibrationReference(
            calibration_id=uuid4(),
            calibration_version="1",
            camera_model="DJI M3T RGB wide",
            image_width_px=3840,
            image_height_px=2160,
            focal_length_x_px=3000.0,
            focal_length_y_px=3000.0,
            principal_point_x_px=1920.0,
            principal_point_y_px=1080.0,
            distortion_model="calibrated",
        ),
        telemetry=TelemetryReference(
            source_id=uuid4(),
            source_type="dji_srt",
            sample_index=487,
            synchronization_method="nearest",
            telemetry_time_s=495.377,
            signed_time_delta_ms=-23.0,
            absolute_time_error_ms=23.0,
            within_sync_tolerance=True,
            sync_tolerance_ms=100.0,
        ),
        location=GeographicLocation(
            latitude_deg=32.0,
            longitude_deg=-79.0,
        ),
        uncertainty=GeoreferencingUncertainty(
            available=False,
            method="not_estimated",
            reason_unavailable=("Formal uncertainty propagation not yet implemented."),
        ),
        method=GeoreferencingMethod(
            version="1.0.0",
            surface_model="local_horizontal_plane",
            representative_pixel_policy_version="1.0.0",
            synchronization_version="1.0.0",
            pose_convention_version="1.0.0",
        ),
        created_at=datetime.now(UTC),
    )

    assert observation.schema_version == "1.0.0"
    assert observation.representative_pixel.method == "bbox_center"
    assert observation.location.crs == "EPSG:4326"
    assert observation.method.version == "1.0.0"
    assert observation.telemetry.source_type == "dji_srt"
    assert observation.uncertainty.available is False


def test_explicit_representative_pixel_is_supported() -> None:
    point = RepresentativePixel(
        x=100.0,
        y=200.0,
        method="explicit",
    )

    assert point.method == "explicit"


def test_bbox_center_policy_value_is_supported() -> None:
    bbox = BoundingBoxPixels(
        x_min=100.0,
        y_min=200.0,
        x_max=300.0,
        y_max=400.0,
    )

    x = (bbox.x_min + bbox.x_max) / 2.0
    y = (bbox.y_min + bbox.y_max) / 2.0

    point = RepresentativePixel(
        x=x,
        y=y,
        method="bbox_center",
    )

    assert point.x == 200.0
    assert point.y == 300.0
