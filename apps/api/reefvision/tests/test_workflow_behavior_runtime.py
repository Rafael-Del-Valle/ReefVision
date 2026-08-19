from __future__ import annotations

import pytest

from reefvision.jobs.workflow_behavior_runtime import (
    _behavior_request,
    _filtered_aggregates,
    _selected_track_ids,
)


def _trajectory(track_id: str, y: float) -> dict[str, object]:
    return {
        "track_id": track_id,
        "trajectory": [
            {
                "frame_index": 0,
                "timestamp_seconds": 0.0,
                "center_x_pixels": 10.0,
                "center_y_pixels": y,
            },
            {
                "frame_index": 1,
                "timestamp_seconds": 0.1,
                "center_x_pixels": 20.0,
                "center_y_pixels": y,
            },
        ],
    }


def test_behavior_request_exposes_scientific_controls() -> None:
    request = _behavior_request(
        {
            "zones": [
                {
                    "name": "nursery",
                    "x_min": 0,
                    "y_min": 0,
                    "x_max": 50,
                    "y_max": 50,
                }
            ],
            "include_saved_zones": False,
            "heatmap_bins_x": 12,
            "heatmap_bins_y": 8,
            "activity_speed_threshold_pixels_per_second": 4.5,
            "sampling": "observations",
        },
        persist_result=False,
    )

    assert request.include_saved_zones is False
    assert request.heatmap_bins_x == 12
    assert request.heatmap_bins_y == 8
    assert request.activity_speed_threshold_pixels_per_second == pytest.approx(4.5)
    assert request.sampling == "observations"
    assert request.zones[0].name == "nursery"
    assert request.persist_result is False


def test_behavior_track_scope_defaults_to_connected_tracks() -> None:
    selected, declared = _selected_track_ids(
        [{"video_ids": ["video-1"], "track_ids": ["track-1", "track-2"]}],
        {},
    )

    assert declared is True
    assert selected == {"track-1", "track-2"}


def test_behavior_configured_tracks_must_be_connected() -> None:
    with pytest.raises(RuntimeError, match="subset"):
        _selected_track_ids(
            [{"track_ids": ["track-1"]}],
            {"track_ids": ["track-2"]},
        )


def test_behavior_subset_recomputes_school_and_heatmap_statistics() -> None:
    request = _behavior_request(
        {
            "heatmap_bins_x": 10,
            "heatmap_bins_y": 10,
        },
        persist_result=False,
    )
    analysis = {
        "fps": 10.0,
        "distance_per_pixel": 0.1,
        "tracks": [_trajectory("track-1", 10.0), _trajectory("track-2", 30.0)],
        "school_by_frame": [{"active_track_count": 2}],
        "heatmap": [{"observation_count": 4}],
        "zone_events": [
            {"track_id": "track-1", "event_type": "entry"},
            {"track_id": "track-2", "event_type": "entry"},
        ],
        "source_track_revisions": [
            {"track_id": "track-1", "revision": 1},
            {"track_id": "track-2", "revision": 1},
        ],
        "_source_dimensions": {"width_px": 100, "height_px": 100},
    }

    filtered = _filtered_aggregates(analysis, {"track-1"}, request)

    assert [track["track_id"] for track in filtered["tracks"]] == ["track-1"]
    assert all(frame["active_track_count"] == 1 for frame in filtered["school_by_frame"])
    assert all(frame["mean_pairwise_distance_pixels"] is None for frame in filtered["school_by_frame"])
    assert sum(cell["observation_count"] for cell in filtered["heatmap"]) == 2
    assert filtered["heatmap"][1]["occupancy_seconds"] == pytest.approx(0.1)
    assert [event["track_id"] for event in filtered["zone_events"]] == ["track-1"]
    assert [item["track_id"] for item in filtered["source_track_revisions"]] == ["track-1"]
