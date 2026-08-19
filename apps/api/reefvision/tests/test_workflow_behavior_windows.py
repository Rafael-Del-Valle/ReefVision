from __future__ import annotations

import pytest

from reefvision.db.models import VideoAsset
from reefvision.jobs.workflow_behavior_window_runtime import (
    _analysis_window,
    _sample_in_window,
    _window_aware_behavior_request,
    _window_track,
)
from reefvision.services.workflow_full_platform_templates import (
    configurable_fish_behavior_template,
)


def _video() -> VideoAsset:
    return VideoAsset(
        id="video-1",
        project_id="project-1",
        original_filename="fish.mp4",
        managed_path="projects/project-1/videos/fish.mp4",
        sha256="a" * 64,
        media_type="video/mp4",
        width_px=100,
        height_px=100,
        frame_count=4,
        fps=1.0,
        duration_seconds=3.0,
        metadata_json={},
    )


def _track() -> dict[str, object]:
    return {
        "track_id": "track-1",
        "tracker_id": 1,
        "label_class_id": "fish",
        "trajectory": [
            {
                "observation_id": f"obs-{frame}",
                "frame_index": frame,
                "timestamp_seconds": float(frame),
                "center_x_pixels": float(frame * 10),
                "center_y_pixels": 50.0,
                "center_x_physical": None,
                "center_y_physical": None,
                "distance_from_previous_pixels": None,
                "distance_from_previous_physical": None,
                "speed_pixels_per_second": None,
                "speed_physical_per_second": None,
                "acceleration_pixels_per_second_squared": None,
                "turning_angle_degrees": None,
                "angular_velocity_degrees_per_second": None,
                "interpolated": False,
                "manual_edit": False,
            }
            for frame in range(4)
        ],
    }


def test_frame_window_recomputes_kinematics_activity_and_zone_dwell() -> None:
    window = _analysis_window({"start_frame": 1, "end_frame": 3})
    track, events = _window_track(
        _track(),
        video=_video(),
        window=window,
        distance_per_pixel=0.1,
        physical_unit="cm",
        activity_threshold=5.0,
        zones=[
            {
                "name": "center",
                "x_min": 15.0,
                "y_min": 0.0,
                "x_max": 35.0,
                "y_max": 100.0,
            }
        ],
    )

    assert track is not None
    assert track["first_frame"] == 1
    assert track["last_frame"] == 3
    assert track["observed_frame_count"] == 3
    assert track["persisted_observation_count"] == 3
    assert track["duration_seconds"] == pytest.approx(2.0)
    assert track["distance_pixels"] == pytest.approx(20.0)
    assert track["net_displacement_pixels"] == pytest.approx(20.0)
    assert track["mean_speed_pixels_per_second"] == pytest.approx(10.0)
    assert track["active_time_seconds"] == pytest.approx(2.0)
    assert track["inactive_time_seconds"] == pytest.approx(0.0)
    assert track["distance_physical"] == pytest.approx(2.0)
    assert track["zone_time_seconds"]["center"] == pytest.approx(1.0)
    assert events == [
        {
            "track_id": "track-1",
            "zone_name": "center",
            "event_type": "entry",
            "frame_index": 2,
            "timestamp_seconds": 2.0,
        }
    ]


def test_frame_and_time_windows_are_combined_as_an_intersection() -> None:
    window = _analysis_window(
        {
            "start_frame": 1,
            "end_frame": 3,
            "start_time_seconds": 2.0,
            "end_time_seconds": 3.0,
        }
    )
    samples = _track()["trajectory"]
    assert isinstance(samples, list)
    selected = [
        int(sample["frame_index"])
        for sample in samples
        if isinstance(sample, dict) and _sample_in_window(sample, window)
    ]
    assert selected == [2, 3]


def test_invalid_window_order_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="start_frame"):
        _analysis_window({"start_frame": 3, "end_frame": 1})
    with pytest.raises(RuntimeError, match="start_time_seconds"):
        _analysis_window({"start_time_seconds": 5.0, "end_time_seconds": 2.0})


def test_windowed_workflows_do_not_persist_broader_service_analysis() -> None:
    request = _window_aware_behavior_request(
        {"start_frame": 1, "end_frame": 2},
        persist_result=True,
    )
    assert request.persist_result is False

    unwindowed = _window_aware_behavior_request({}, persist_result=True)
    assert unwindowed.persist_result is True


def test_behavior_template_exposes_optional_frame_and_time_window_controls() -> None:
    template = configurable_fish_behavior_template()
    behavior = next(node for node in template.workflow.nodes if node.id == "behavior")
    assert behavior.configuration["start_frame"] is None
    assert behavior.configuration["end_frame"] is None
    assert behavior.configuration["start_time_seconds"] is None
    assert behavior.configuration["end_time_seconds"] is None
