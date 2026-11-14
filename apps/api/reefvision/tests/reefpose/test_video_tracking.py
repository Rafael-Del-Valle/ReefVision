from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
import torch

from reefvision.ml.reefpose.checkpoints import save_checkpoint
from reefvision.ml.reefpose.model import ReefPoseConfig, ReefPoseS
from reefvision.ml.reefpose.schema import AnatomySchema, LandmarkDefinition
from reefvision.ml.video_tracking import (
    VideoTrackingProgress,
    video_tracking_provider_for_name,
)


def _checkpoint(path: Path) -> None:
    schema = AnatomySchema(
        schema_id="reefpose-video-schema",
        name="Synthetic animal",
        revision=1,
        landmarks=(
            LandmarkDefinition(landmark_id="center", name="center"),
            LandmarkDefinition(landmark_id="tail", name="tail"),
        ),
    )
    model = ReefPoseS(
        ReefPoseConfig(
            num_keypoints=2,
            input_height=64,
            input_width=64,
            base_channels=8,
        )
    )
    visibility_layer = model.visibility_head[-1]
    assert isinstance(visibility_layer, torch.nn.Linear)
    torch.nn.init.zeros_(visibility_layer.weight)
    torch.nn.init.constant_(visibility_layer.bias, 10.0)
    save_checkpoint(
        path,
        model=model,
        schema=schema,
        epoch=0,
        global_step=1,
        training_config={"class_label": "animal"},
    )


def _video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cast(Any, cv2).VideoWriter_fourcc(*"MJPG"),
        10.0,
        (80, 48),
    )
    assert writer.isOpened()
    for value in (20, 80, 140):
        writer.write(np.full((48, 80, 3), value, dtype=np.uint8))
    writer.release()


def test_registered_reefpose_checkpoint_runs_video_pose_inference(tmp_path: Path) -> None:
    checkpoint = tmp_path / "reefpose.pt"
    video = tmp_path / "animal.avi"
    _checkpoint(checkpoint)
    _video(video)
    progress: list[VideoTrackingProgress] = []

    provider = video_tracking_provider_for_name("reefpose")
    observations = provider.track(
        checkpoint,
        video,
        tracker=provider.resolve_tracker_name("bytetrack.yaml", link_detections=True),
        confidence=0.0,
        iou=0.5,
        device="cpu",
        link_detections=True,
        on_progress=progress.append,
    )

    assert provider.provider_id == "reefpose"
    assert len(observations) == 3
    assert {item.frame for item in observations} == {0, 1, 2}
    assert {item.provider_track_id for item in observations} == {1}
    assert {item.class_name for item in observations} == {"animal"}
    assert all(item.keypoints is not None and len(item.keypoints) == 2 for item in observations)
    assert all(item.bbox[2] > 0 and item.bbox[3] > 0 for item in observations)
    assert progress[-1].frames_processed == 3
    assert progress[-1].tracked_observations_seen == 3
    assert progress[-1].unique_tracks_seen == 1
