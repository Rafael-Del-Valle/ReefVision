from __future__ import annotations

import pytest

from reefvision.schemas.geographic_movement_analytics import (
    GeographicMovementObservation,
)
from reefvision.services.geographic_movement_analytics import (
    GeographicMovementInputError,
    UnsupportedGeographicCRSError,
    calculate_movement_segment,
    calculate_track_summary,
    geographic_distance_m,
)


def observation(
    observation_id: str,
    *,
    frame_index: int,
    frame_time_s: float,
    latitude_deg: float,
    longitude_deg: float,
    track_id: str | None = "track-1",
    video_asset_id: str = "video-1",
    crs: str = "EPSG:4326",
) -> GeographicMovementObservation:
    return GeographicMovementObservation(
        observation_id=observation_id,
        track_id=track_id,
        video_asset_id=video_asset_id,
        frame_index=frame_index,
        frame_time_s=frame_time_s,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        crs=crs,
    )


def test_wgs84_distance_is_zero_for_identical_coordinates() -> None:
    assert (
        geographic_distance_m(
            32.75,
            -79.93,
            32.75,
            -79.93,
        )
        == 0.0
    )


def test_wgs84_distance_matches_known_equatorial_latitude_and_longitude() -> None:
    north_one_degree = geographic_distance_m(
        0.0,
        0.0,
        1.0,
        0.0,
    )

    east_one_degree = geographic_distance_m(
        0.0,
        0.0,
        0.0,
        1.0,
    )

    assert north_one_degree == pytest.approx(
        110_574.388558,
        rel=1e-9,
    )

    assert east_one_degree == pytest.approx(
        111_319.490793,
        rel=1e-9,
    )


def test_wgs84_distance_matches_known_diagonal_pair() -> None:
    distance = geographic_distance_m(
        0.0,
        0.0,
        1.0,
        1.0,
    )

    assert distance == pytest.approx(
        156_899.568291,
        rel=1e-9,
    )


def test_segment_preserves_identity_and_calculates_speed() -> None:
    start = observation(
        "observation-1",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
    )

    end = observation(
        "observation-2",
        frame_index=20,
        frame_time_s=3.0,
        latitude_deg=32.7501,
        longitude_deg=-79.9299,
    )

    segment = calculate_movement_segment(
        start,
        end,
    )

    assert segment.track_id == "track-1"
    assert segment.video_asset_id == "video-1"
    assert segment.start_observation_id == "observation-1"
    assert segment.end_observation_id == "observation-2"
    assert segment.start_frame_index == 10
    assert segment.end_frame_index == 20
    assert segment.start_frame_time_s == 1.0
    assert segment.end_frame_time_s == 3.0

    assert segment.elapsed_time_s == 2.0

    assert segment.distance_m == pytest.approx(
        14.5194595,
        rel=1e-7,
    )

    assert segment.speed_m_s == pytest.approx(
        segment.distance_m / 2.0,
    )

    assert segment.speed_valid is True
    assert segment.invalid_reason is None


@pytest.mark.parametrize(
    ("start_lat", "start_lon", "end_lat", "end_lon", "expected_bearing"),
    [
        (0.0, 0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 1.0, 90.0),
        (0.0, 0.0, 0.0, -1.0, 270.0),
        (0.0, 179.9, 0.0, -179.9, 90.0),
        (0.0, -179.9, 0.0, 179.9, 270.0),
        (0.0, 0.0, 1.0, 1.0, 45.18804022935887),
    ],
    ids=["north", "east", "west", "dateline-east", "dateline-west", "wgs84-diagonal"],
)
def test_segment_initial_bearing_is_clockwise_from_true_north(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    expected_bearing: float,
) -> None:
    start = observation(
        "start",
        frame_index=0,
        frame_time_s=0.0,
        latitude_deg=start_lat,
        longitude_deg=start_lon,
    )
    end = observation(
        "end",
        frame_index=1,
        frame_time_s=1.0,
        latitude_deg=end_lat,
        longitude_deg=end_lon,
    )

    segment = calculate_movement_segment(start, end)

    assert segment.model_dump()["initial_bearing_deg"] == pytest.approx(
        expected_bearing,
        abs=1e-9,
    )


def test_stationary_segment_has_no_initial_bearing() -> None:
    start = observation(
        "start",
        frame_index=0,
        frame_time_s=0.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
    )
    end = start.model_copy(update={"observation_id": "end", "frame_index": 1, "frame_time_s": 1.0})

    segment = calculate_movement_segment(start, end)

    assert segment.distance_m == 0.0
    assert segment.speed_m_s == 0.0
    assert segment.model_dump()["initial_bearing_deg"] is None


@pytest.mark.parametrize(
    ("end_time_s", "expected_elapsed_s"),
    [
        (1.0, 0.0),
        (0.5, -0.5),
    ],
)
def test_segment_does_not_fabricate_speed_for_non_positive_time(
    end_time_s: float,
    expected_elapsed_s: float,
) -> None:
    start = observation(
        "observation-1",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
    )

    end = observation(
        "observation-2",
        frame_index=20,
        frame_time_s=end_time_s,
        latitude_deg=32.7501,
        longitude_deg=-79.9299,
    )

    segment = calculate_movement_segment(
        start,
        end,
    )

    assert segment.elapsed_time_s == expected_elapsed_s
    assert segment.distance_m > 0.0
    assert segment.speed_m_s is None
    assert segment.speed_valid is False
    assert segment.invalid_reason == "non_positive_elapsed_time"


def test_track_summary_orders_by_frame_and_calculates_cumulative_metrics() -> None:
    first = observation(
        "observation-1",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.7500,
        longitude_deg=-79.9300,
    )

    second = observation(
        "observation-2",
        frame_index=20,
        frame_time_s=2.0,
        latitude_deg=32.7501,
        longitude_deg=-79.9299,
    )

    third = observation(
        "observation-3",
        frame_index=30,
        frame_time_s=4.0,
        latitude_deg=32.7502,
        longitude_deg=-79.9298,
    )

    summary = calculate_track_summary(
        track_id="track-1",
        video_asset_id="video-1",
        observations=[
            third,
            first,
            second,
        ],
    )

    assert summary.observation_count == 3
    assert summary.segment_count == 2

    assert summary.first_frame_index == 10
    assert summary.last_frame_index == 30
    assert summary.first_frame_time_s == 1.0
    assert summary.last_frame_time_s == 4.0
    assert summary.elapsed_time_s == 3.0

    assert [segment.start_observation_id for segment in summary.segments] == [
        "observation-1",
        "observation-2",
    ]

    assert [segment.end_observation_id for segment in summary.segments] == [
        "observation-2",
        "observation-3",
    ]

    expected_total = sum(segment.distance_m for segment in summary.segments)

    assert summary.total_distance_m == pytest.approx(expected_total)

    assert summary.segments[-1].cumulative_distance_m == pytest.approx(expected_total)

    assert summary.net_displacement_m == pytest.approx(
        geographic_distance_m(
            first.latitude_deg,
            first.longitude_deg,
            third.latitude_deg,
            third.longitude_deg,
        )
    )

    assert summary.mean_speed_m_s == pytest.approx(expected_total / 3.0)

    valid_speeds = [
        segment.speed_m_s for segment in summary.segments if segment.speed_m_s is not None
    ]

    assert summary.max_segment_speed_m_s == pytest.approx(max(valid_speeds))


def test_one_observation_track_has_zero_distance_and_no_speed() -> None:
    only = observation(
        "observation-1",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
    )

    summary = calculate_track_summary(
        track_id="track-1",
        video_asset_id="video-1",
        observations=[only],
    )

    assert summary.observation_count == 1
    assert summary.segment_count == 0
    assert summary.total_distance_m == 0.0
    assert summary.net_displacement_m == 0.0
    assert summary.elapsed_time_s == 0.0
    assert summary.mean_speed_m_s is None
    assert summary.max_segment_speed_m_s is None
    assert summary.segments == []


def test_empty_track_returns_explicit_empty_summary() -> None:
    summary = calculate_track_summary(
        track_id="track-1",
        video_asset_id="video-1",
        observations=[],
    )

    assert summary.observation_count == 0
    assert summary.segment_count == 0

    assert summary.first_frame_index is None
    assert summary.last_frame_index is None
    assert summary.first_frame_time_s is None
    assert summary.last_frame_time_s is None
    assert summary.elapsed_time_s is None

    assert summary.total_distance_m == 0.0
    assert summary.net_displacement_m == 0.0
    assert summary.mean_speed_m_s is None
    assert summary.max_segment_speed_m_s is None

    assert summary.start_location is None
    assert summary.end_location is None
    assert summary.segments == []


def test_null_track_observations_do_not_form_requested_track_trajectory() -> None:
    tracked = observation(
        "tracked",
        frame_index=20,
        frame_time_s=2.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
    )

    untracked = observation(
        "untracked",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=40.0,
        longitude_deg=-70.0,
        track_id=None,
    )

    summary = calculate_track_summary(
        track_id="track-1",
        video_asset_id="video-1",
        observations=[
            untracked,
            tracked,
        ],
    )

    assert summary.observation_count == 1
    assert summary.segment_count == 0
    assert summary.start_location is not None
    assert summary.start_location.latitude_deg == 32.75


def test_segment_rejects_null_or_mismatched_track_identity() -> None:
    tracked = observation(
        "tracked",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
    )

    untracked = observation(
        "untracked",
        frame_index=20,
        frame_time_s=2.0,
        latitude_deg=32.7501,
        longitude_deg=-79.9299,
        track_id=None,
    )

    other_track = observation(
        "other-track",
        frame_index=20,
        frame_time_s=2.0,
        latitude_deg=32.7501,
        longitude_deg=-79.9299,
        track_id="track-2",
    )

    with pytest.raises(
        GeographicMovementInputError,
        match="non-null track IDs",
    ):
        calculate_movement_segment(
            tracked,
            untracked,
        )

    with pytest.raises(
        GeographicMovementInputError,
        match="same track",
    ):
        calculate_movement_segment(
            tracked,
            other_track,
        )


def test_track_summary_rejects_wrong_video_for_matching_track() -> None:
    wrong_video = observation(
        "observation-1",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
        video_asset_id="video-2",
    )

    with pytest.raises(
        GeographicMovementInputError,
        match="requested video",
    ):
        calculate_track_summary(
            track_id="track-1",
            video_asset_id="video-1",
            observations=[wrong_video],
        )


def test_unsupported_crs_is_explicit() -> None:
    start = observation(
        "observation-1",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.75,
        longitude_deg=-79.93,
    )

    end = observation(
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
        calculate_movement_segment(
            start,
            end,
        )


def test_duplicate_frame_order_is_deterministic_without_interpolation() -> None:
    later_id = observation(
        "b",
        frame_index=10,
        frame_time_s=2.0,
        latitude_deg=32.7501,
        longitude_deg=-79.9299,
    )

    earlier_time = observation(
        "a",
        frame_index=10,
        frame_time_s=1.0,
        latitude_deg=32.7500,
        longitude_deg=-79.9300,
    )

    summary = calculate_track_summary(
        track_id="track-1",
        video_asset_id="video-1",
        observations=[
            later_id,
            earlier_time,
        ],
    )

    assert summary.segment_count == 1

    segment = summary.segments[0]

    assert segment.start_observation_id == "a"
    assert segment.end_observation_id == "b"

    assert segment.start_frame_index == 10
    assert segment.end_frame_index == 10

    assert segment.start_frame_time_s == 1.0
    assert segment.end_frame_time_s == 2.0
