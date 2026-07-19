from __future__ import annotations

import numpy as np
import pytest

from reefvision.ml.rgbd import (
    depth_aware_association_cost,
    normalize_depth,
    stack_rgbd,
)
from reefvision.schemas.depth import DepthTrackAnalyticsRequest
from reefvision.services.depth_tracking import analyze_depth_tracks


def test_rgbd_stack_preserves_rgb_and_normalizes_depth() -> None:
    rgb = np.zeros((3, 4, 3), dtype=np.uint8)
    rgb[..., 0] = 255
    depth = np.arange(12, dtype=np.float32).reshape(3, 4) + 1

    rgbd = stack_rgbd(rgb, depth, depth_normalization="per_image")

    assert rgbd.shape == (3, 4, 4)
    assert np.allclose(rgbd[..., 0], 1.0)
    assert np.allclose(rgbd[..., 1:3], 0.0)
    assert np.isfinite(rgbd[..., 3]).all()
    assert not np.allclose(rgbd[..., 3], depth)


def test_dataset_depth_normalization_requires_valid_statistics() -> None:
    with pytest.raises(ValueError, match="positive standard deviation"):
        normalize_depth(
            np.ones((2, 2), dtype=np.float32),
            mode="dataset",
            dataset_mean=1.0,
            dataset_std=0.0,
        )


def test_depth_aware_association_can_reject_an_implausible_depth_jump() -> None:
    cost, gated, details = depth_aware_association_cost(
        appearance_cost=0.1,
        motion_cost=0.2,
        detection_depth=5.0,
        track_depth_history=[1.0, 1.1, 0.9],
        maximum_normalized_depth_gap=0.5,
    )

    assert cost > 0.1
    assert gated is True
    assert details["track_depth"] == pytest.approx(1.0)
    assert details["normalized_depth_gap"] == pytest.approx(0.8)


def test_metric_depth_samples_create_true_3d_track_distance() -> None:
    request = DepthTrackAnalyticsRequest.model_validate(
        {
            "fps": 10,
            "unit": "m",
            "camera_intrinsics": {
                "fx_px": 100,
                "fy_px": 100,
                "cx_px": 50,
                "cy_px": 50,
            },
            "samples": [
                {
                    "track_id": "fish-1",
                    "frame_index": 0,
                    "center_x_px": 50,
                    "center_y_px": 50,
                    "depth": 1,
                },
                {
                    "track_id": "fish-1",
                    "frame_index": 10,
                    "center_x_px": 60,
                    "center_y_px": 50,
                    "depth": 2,
                },
            ],
        }
    )

    response = analyze_depth_tracks(request)

    track = response.tracks[0]
    assert track.duration_seconds == pytest.approx(1.0)
    assert track.points[0].x == pytest.approx(0.0)
    assert track.points[1].x == pytest.approx(0.2)
    assert track.distance_3d == pytest.approx((0.2**2 + 1.0**2) ** 0.5)
    assert track.mean_speed_3d_per_second == pytest.approx(track.distance_3d)
