from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from reefvision.services.geographic_movement_analytics import (
    UnsupportedGeographicCRSError,
)
from reefvision.services.geographic_movement_analytics_persistence import (
    PersistedObservationMappingError,
    calculate_persisted_track_summary,
    geographic_movement_observation_from_persisted,
)


def persisted(
    observation_id: str,
    *,
    frame_index: int,
    frame_time_s: float,
    latitude_deg: float,
    longitude_deg: float,
    track_id: str | None = "track-1",
    video_id: str = "video-1",
    crs: str = "EPSG:4326",
    is_stale: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=observation_id,
        track_id=track_id,
        video_id=video_id,
        frame_index=frame_index,
        frame_time_s=frame_time_s,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        crs=crs,
        is_stale=is_stale,
    )


def test_maps_persisted_record_without_recalculating_values() -> None:
    row = persisted(
        "observation-1",
        frame_index=42,
        frame_time_s=1.4,
        latitude_deg=32.750123,
        longitude_deg=-79.930456,
    )

    mapped = geographic_movement_observation_from_persisted(row)

    assert mapped.observation_id == "observation-1"
    assert mapped.track_id == "track-1"
    assert mapped.video_asset_id == "video-1"
    assert mapped.frame_index == 42
    assert mapped.frame_time_s == 1.4
    assert mapped.latitude_deg == 32.750123
    assert mapped.longitude_deg == -79.930456
    assert mapped.crs == "EPSG:4326"


def test_maps_database_uuid_identity_to_schema_string() -> None:
    observation_id = UUID("12345678-1234-5678-1234-567812345678")

    row = persisted(
        observation_id,
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
    )

    mapped = geographic_movement_observation_from_persisted(row)

    assert mapped.observation_id == str(observation_id)


def test_supports_canonical_persistence_aliases_and_nested_location() -> None:
    row = {
        "observation_id": "observation-1",
        "track_id": "track-1",
        "video_asset_id": "video-1",
        "frame_index": 10,
        "frame_time_seconds": 0.5,
        "is_stale": False,
        "geographic_location": {
            "latitude": 32.75,
            "longitude": -79.93,
            "crs": "EPSG:4326",
        },
    }

    mapped = geographic_movement_observation_from_persisted(row)

    assert mapped.observation_id == "observation-1"
    assert mapped.video_asset_id == "video-1"
    assert mapped.frame_time_s == 0.5
    assert mapped.latitude_deg == 32.75
    assert mapped.longitude_deg == -79.93
    assert mapped.crs == "EPSG:4326"


def test_persisted_track_summary_delegates_to_existing_pure_calculations() -> None:
    later = persisted(
        "observation-2",
        frame_index=20,
        frame_time_s=3.0,
        latitude_deg=32.7501,
        longitude_deg=-79.9299,
    )

    earlier = persisted(
        "observation-1",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
    )

    summary = calculate_persisted_track_summary(
        track_id="track-1",
        video_asset_id="video-1",
        persisted_observations=[
            later,
            earlier,
        ],
    )

    assert summary.observation_count == 2
    assert summary.segment_count == 1

    segment = summary.segments[0]

    assert segment.start_observation_id == "observation-1"
    assert segment.end_observation_id == "observation-2"

    assert segment.start_frame_index == 10
    assert segment.end_frame_index == 20
    assert segment.start_frame_time_s == 1.0
    assert segment.end_frame_time_s == 3.0

    assert segment.distance_m > 0.0
    assert segment.speed_m_s is not None
    assert segment.speed_m_s > 0.0

    assert summary.total_distance_m == pytest.approx(segment.distance_m)


def test_null_track_persisted_records_are_not_added_to_track_trajectory() -> None:
    tracked = persisted(
        "tracked",
        frame_index=20,
        frame_time_s=2.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
    )

    untracked = persisted(
        "untracked",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=40.0,
        longitude_deg=-70.0,
        track_id=None,
    )

    summary = calculate_persisted_track_summary(
        track_id="track-1",
        video_asset_id="video-1",
        persisted_observations=[
            untracked,
            tracked,
        ],
    )

    assert summary.observation_count == 1
    assert summary.segment_count == 0
    assert summary.first_frame_index == 20


def test_empty_persisted_collection_returns_empty_track_summary() -> None:
    summary = calculate_persisted_track_summary(
        track_id="track-1",
        video_asset_id="video-1",
        persisted_observations=[],
    )

    assert summary.track_id == "track-1"
    assert summary.video_asset_id == "video-1"
    assert summary.observation_count == 0
    assert summary.segment_count == 0
    assert summary.total_distance_m == 0.0
    assert summary.net_displacement_m == 0.0
    assert summary.segments == []


@pytest.mark.parametrize("freshness", [True, None, "false", 0, "missing"])
def test_summary_excludes_rows_without_explicit_freshness(freshness: object) -> None:
    fresh = persisted(
        "fresh",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=0.0,
        longitude_deg=0.0,
    )
    excluded = persisted(
        "excluded",
        frame_index=20,
        frame_time_s=2.0,
        latitude_deg=10.0,
        longitude_deg=10.0,
    )
    if freshness == "missing":
        del excluded.is_stale
    else:
        excluded.is_stale = freshness

    summary = calculate_persisted_track_summary(
        track_id="track-1",
        video_asset_id="video-1",
        persisted_observations=[fresh, vars(excluded)],
    )

    assert summary.observation_count == 1
    assert summary.segment_count == 0
    assert summary.total_distance_m == 0.0
    assert summary.mean_speed_m_s is None


def test_persisted_unsupported_crs_propagates_scientific_validation() -> None:
    first = persisted(
        "observation-1",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
        crs="EPSG:3857",
    )

    second = persisted(
        "observation-2",
        frame_index=20,
        frame_time_s=2.0,
        latitude_deg=32.7501,
        longitude_deg=-79.9299,
        crs="EPSG:3857",
    )

    with pytest.raises(
        UnsupportedGeographicCRSError,
        match="EPSG:4326",
    ):
        calculate_persisted_track_summary(
            track_id="track-1",
            video_asset_id="video-1",
            persisted_observations=[
                first,
                second,
            ],
        )


def test_missing_persistence_field_fails_explicitly() -> None:
    row = SimpleNamespace(
        id="observation-1",
        track_id="track-1",
        video_id="video-1",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.75,
        crs="EPSG:4326",
    )

    with pytest.raises(
        PersistedObservationMappingError,
        match="longitude",
    ):
        geographic_movement_observation_from_persisted(row)
