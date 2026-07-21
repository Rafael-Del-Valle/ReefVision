from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_video_tracking_phase6 import _seed_video


def _track_payload(
    video_id: str,
    label_class_id: str,
    track_number: int,
    centers: list[tuple[float, float]],
) -> dict[str, object]:
    return {
        "video_id": video_id,
        "label_class_id": label_class_id,
        "track_number": track_number,
        "interpolation": "linear",
        "status": "verified",
        "keyframes": [
            {
                "frame_index": frame_index,
                "x_min": center_x - 2,
                "y_min": center_y - 2,
                "x_max": center_x + 2,
                "y_max": center_y + 2,
            }
            for frame_index, (center_x, center_y) in enumerate(centers)
        ],
    }


def test_video_behavior_reports_tortuosity_turning_and_school_polarization(
    client: TestClient,
) -> None:
    _project, video_id, label_class_id = _seed_video(client)
    first = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json=_track_payload(
            video_id,
            label_class_id,
            1,
            [(5, 5), (15, 5), (15, 15)],
        ),
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json=_track_payload(
            video_id,
            label_class_id,
            2,
            [(5, 25), (15, 25), (15, 35)],
        ),
    )
    assert second.status_code == 201, second.text
    calibration = client.put(
        f"/api/v1/videos/{video_id}/calibration",
        json={
            "distance_per_pixel": 0.1,
            "unit": "cm",
            "source": "tank scale",
        },
    )
    assert calibration.status_code == 200, calibration.text

    response = client.post(
        f"/api/v1/videos/{video_id}/analytics",
        json={
            "activity_speed_threshold_pixels_per_second": 50,
            "heatmap_bins_x": 10,
            "heatmap_bins_y": 10,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    first_track = next(item for item in payload["tracks"] if item["tracker_id"] == 1)
    assert first_track["distance_pixels"] == pytest.approx(20)
    assert first_track["total_path_length_pixels"] == pytest.approx(20)
    assert first_track["net_displacement_pixels"] == pytest.approx(math.sqrt(200))
    assert first_track["path_tortuosity"] == pytest.approx(math.sqrt(2))
    assert first_track["mean_speed_pixels_per_second"] == pytest.approx(100)
    assert first_track["maximum_speed_pixels_per_second"] == pytest.approx(100)
    assert first_track["mean_acceleration_pixels_per_second_squared"] == pytest.approx(0)
    assert first_track["maximum_acceleration_pixels_per_second_squared"] == pytest.approx(0)
    assert first_track["mean_turning_angle_degrees"] == pytest.approx(90)
    assert first_track["cumulative_turning_angle_degrees"] == pytest.approx(90)
    assert first_track["mean_distance_to_wall_pixels"] == pytest.approx(25 / 3)
    assert first_track["active_time_seconds"] == pytest.approx(0.2)
    assert first_track["inactive_time_seconds"] == pytest.approx(0)
    assert first_track["distance_physical"] == pytest.approx(2)
    assert first_track["net_displacement_physical"] == pytest.approx(math.sqrt(2))
    assert first_track["mean_speed_physical_per_second"] == pytest.approx(10)
    assert first_track["mean_distance_to_wall_physical"] == pytest.approx(5 / 6)

    frames = {item["frame_index"]: item for item in payload["school_by_frame"]}
    assert frames[0]["mean_pairwise_distance_pixels"] == pytest.approx(20)
    assert frames[0]["mean_nearest_neighbor_pixels"] == pytest.approx(20)
    assert frames[0]["school_spread_pixels"] == pytest.approx(10)
    assert frames[0]["school_centroid_x_pixels"] == pytest.approx(5)
    assert frames[0]["school_centroid_y_pixels"] == pytest.approx(15)
    assert frames[0]["school_centroid_x_physical"] == pytest.approx(0.5)
    assert frames[0]["school_centroid_y_physical"] == pytest.approx(1.5)
    assert frames[0]["polarization"] is None
    assert frames[1]["polarization"] == pytest.approx(1)
    assert frames[2]["polarization"] == pytest.approx(1)
    assert frames[1]["mean_pairwise_distance_physical"] == pytest.approx(2)
