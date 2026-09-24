"""Task 18B: scientific and GIS contract tests for geographic exports."""

from __future__ import annotations

import csv
import io
import json
from uuid import UUID, uuid4

import pytest

from reefvision.schemas.georeferenced_observation import (
    GeographicLocation,
    GeoReferencedObservation,
)
from reefvision.services.geographic_gis_export import (
    GeographicExportEnrichment,
    GeographicGISExportError,
    build_geojson,
    csv_bytes,
    geojson_bytes,
)


def observation(
    frame: int,
    *,
    latitude: float = 32.75,
    longitude: float = -79.93,
    track_id: UUID | None = None,
    video_id: UUID | None = None,
    available: bool = False,
    radius: float | None = None,
) -> GeoReferencedObservation:
    return GeoReferencedObservation.model_validate(
        {
            "id": str(uuid4()),
            "project_id": str(PROJECT_ID),
            "video_asset_id": str(video_id or VIDEO_ID),
            "track_id": str(track_id) if track_id else None,
            "detection_id": str(uuid4()),
            "frame_index": frame,
            "frame_width_px": 100,
            "frame_height_px": 60,
            "bbox": {
                "x_min": 10,
                "y_min": 12,
                "x_max": 30,
                "y_max": 20,
            },
            "representative_pixel": {
                "x": 20,
                "y": 16,
                "method": "bbox_center",
            },
            "timestamp": {
                "frame_time_s": frame / 10,
                "utc": "2026-09-23T20:00:00Z",
                "source": "frame_index_fps",
                "fps": 10,
            },
            "pose": {
                "platform": {
                    "latitude_deg": 32.75,
                    "longitude_deg": -79.93,
                    "height_above_surface_m": 20,
                    "heading_reference": "true_north",
                },
                "camera": {
                    "yaw_deg": 0,
                    "pitch_deg": -90,
                    "roll_deg": 0,
                    "orientation_source": "gimbal_telemetry",
                },
            },
            "calibration": {
                "calibration_id": str(uuid4()),
                "calibration_version": "calibration-v1",
                "checksum_sha256": "a" * 64,
                "image_width_px": 100,
                "image_height_px": 60,
                "focal_length_x_px": 80,
                "focal_length_y_px": 80,
                "principal_point_x_px": 50,
                "principal_point_y_px": 30,
            },
            "telemetry": {
                "source_id": str(uuid4()),
                "source_type": "dji_srt",
                "synchronization_method": "exact",
                "within_sync_tolerance": True,
                "sync_tolerance_ms": 50,
                "absolute_time_error_ms": 4,
            },
            "location": {
                "latitude_deg": latitude,
                "longitude_deg": longitude,
                "crs": "EPSG:4326",
            },
            "uncertainty": {
                "available": available,
                "method": ("empirical_validation" if available else "not_estimated"),
                "horizontal_95_m": radius,
                "reason_unavailable": (None if available else "Not estimated."),
            },
            "method": {
                "version": "projection-v1",
                "surface_model": "local_horizontal_plane",
                "representative_pixel_policy_version": "pixel-v1",
                "synchronization_version": "sync-v1",
                "pose_convention_version": "pose-v1",
            },
            "created_at": "2026-09-23T20:00:00Z",
        }
    )


PROJECT_ID = uuid4()
VIDEO_ID = uuid4()
TRACK_ID = uuid4()


def test_points_and_track_line_preserve_coordinate_order_and_chronology() -> None:
    first = observation(10, track_id=TRACK_ID, longitude=-79.93)
    second = observation(20, track_id=TRACK_ID, longitude=-79.92)
    untracked = observation(15)

    result = build_geojson([second, untracked, first])
    features = result["features"]

    assert result["type"] == "FeatureCollection"
    assert len(features) == 4

    points = [feature for feature in features if feature["geometry"]["type"] == "Point"]
    lines = [feature for feature in features if feature["geometry"]["type"] == "LineString"]

    assert len(points) == 3
    assert len(lines) == 1
    assert points[0]["geometry"]["coordinates"] == [-79.93, 32.75]
    assert lines[0]["geometry"]["coordinates"] == [
        [-79.93, 32.75],
        [-79.92, 32.75],
    ]
    assert lines[0]["properties"]["frame_indices"] == [10, 20]
    assert lines[0]["properties"]["observation_ids"] == [
        str(first.id),
        str(second.id),
    ]


def test_provenance_is_preserved_and_missing_class_is_explicit() -> None:
    item = observation(10, available=False, radius=10)
    point = build_geojson([item])["features"][0]
    properties = point["properties"]

    assert properties["class_name"] is None
    assert properties["confidence"] is None
    assert properties["classification_status"] == ("not_in_geographic_observation")
    assert properties["uncertainty_available"] is False
    assert properties["horizontal_95_m"] is None

    original = properties["source_observation"]

    assert original["uncertainty"]["horizontal_95_m"] == 10
    assert original["calibration"]["calibration_version"] == "calibration-v1"
    assert original["telemetry"]["source_type"] == "dji_srt"
    assert original["method"]["version"] == "projection-v1"
    assert original["pose"]["camera"]["orientation_source"] == ("gimbal_telemetry")


def test_singleton_and_untracked_observations_do_not_create_lines() -> None:
    items = [observation(10, track_id=TRACK_ID), observation(11)]

    features = build_geojson(items)["features"]

    assert len(features) == 2
    assert all(feature["geometry"]["type"] == "Point" for feature in features)


def test_csv_preserves_flat_fields_and_original_scientific_payload() -> None:
    item = observation(10)
    content = csv_bytes([item]).decode("utf-8")

    rows = list(csv.DictReader(io.StringIO(content)))
    assert len(rows) == 1

    row = rows[0]

    assert row["observation_id"] == str(item.id)
    assert row["longitude_deg"] == "-79.93"
    assert row["latitude_deg"] == "32.75"
    assert row["class_name"] == ""
    assert row["confidence"] == ""
    assert row["method_version"] == "projection-v1"

    original = json.loads(row["source_observation_json"])

    assert original["id"] == str(item.id)
    assert original["telemetry"]["source_type"] == "dji_srt"


def test_invalid_geographic_values_and_duplicate_ids_are_rejected() -> None:
    first = observation(10)

    invalid = first.model_copy(
        update={
            "location": GeographicLocation.model_construct(
                latitude_deg=32.75,
                longitude_deg=float("nan"),
                crs="EPSG:4326",
            )
        }
    )

    with pytest.raises(GeographicGISExportError):
        build_geojson([invalid])

    with pytest.raises(GeographicGISExportError):
        build_geojson([first, first])


def test_mixed_video_track_is_rejected() -> None:
    first = observation(10, track_id=TRACK_ID)
    second = observation(
        20,
        track_id=TRACK_ID,
        video_id=uuid4(),
    )

    with pytest.raises(GeographicGISExportError):
        build_geojson([first, second])


def test_empty_exports_are_valid_and_json_has_no_nonfinite_tokens() -> None:
    result = json.loads(geojson_bytes([]))

    assert result == {"type": "FeatureCollection", "features": []}

    rows = list(csv.DictReader(io.StringIO(csv_bytes([]).decode("utf-8"))))
    assert rows == []


def test_authoritative_enrichment_reaches_geojson_and_csv() -> None:
    item = observation(10)

    enrichments = {
        str(item.id): GeographicExportEnrichment(
            label_class_id="class-1",
            class_name="Fish",
            confidence=0.91,
            confidence_status="exact_keyframe",
        )
    }

    point = build_geojson(
        [item],
        enrichments,
    )["features"][0]

    properties = point["properties"]

    assert properties["label_class_id"] == "class-1"
    assert properties["class_name"] == "Fish"
    assert properties["confidence"] == 0.91
    assert properties["confidence_status"] == "exact_keyframe"
    assert properties["classification_status"] == "linked_track_class"

    rows = list(
        csv.DictReader(
            io.StringIO(
                csv_bytes(
                    [item],
                    enrichments,
                ).decode("utf-8")
            )
        )
    )

    assert rows[0]["label_class_id"] == "class-1"
    assert rows[0]["class_name"] == "Fish"
    assert rows[0]["confidence"] == "0.91"
    assert rows[0]["confidence_status"] == "exact_keyframe"


def test_track_lines_keep_confidence_per_observation() -> None:
    first = observation(
        10,
        track_id=TRACK_ID,
        longitude=-79.93,
    )
    second = observation(
        20,
        track_id=TRACK_ID,
        longitude=-79.92,
    )

    enrichments = {
        str(first.id): GeographicExportEnrichment(
            label_class_id="class-1",
            class_name="Fish",
            confidence=0.9,
            confidence_status="exact_keyframe",
        ),
        str(second.id): GeographicExportEnrichment(
            label_class_id="class-1",
            class_name="Fish",
            confidence=None,
            confidence_status="not_persisted_for_frame",
        ),
    }

    features = build_geojson(
        [first, second],
        enrichments,
    )["features"]

    line = next(feature for feature in features if feature["geometry"]["type"] == "LineString")

    properties = line["properties"]

    assert properties["label_class_id"] == "class-1"
    assert properties["class_name"] == "Fish"
    assert properties["confidence"] is None
    assert properties["confidence_status"] == ("per_observation_values")
    assert properties["observation_confidences"] == [
        0.9,
        None,
    ]
