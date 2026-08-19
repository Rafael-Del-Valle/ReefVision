from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow_video_depth_3d_runtime import _workflow_video_depth_3d
from reefvision.services.workflow_definition_extensions import (
    install_workflow_definition_extensions,
)
from reefvision.services.workflow_full_platform_templates import (
    calibrated_3d_fish_trajectory_template,
)
from reefvision.services.workflows import NODE_DEFINITIONS
from reefvision.tests.test_video_tracking_phase6 import _seed_video


def _artifact(payload: dict[str, object]) -> Any:
    return SimpleNamespace(payload_json=payload)


def test_metric_rgbd_samples_back_project_to_calibrated_xyz_trajectory(
    client: TestClient,
) -> None:
    project, video_id, label_class_id = _seed_video(client)
    response = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "video_id": video_id,
            "label_class_id": label_class_id,
            "track_number": 1,
            "interpolation": "linear",
            "status": "verified",
            "keyframes": [
                {
                    "frame_index": 0,
                    "x_min": 48,
                    "y_min": 48,
                    "x_max": 52,
                    "y_max": 52,
                },
                {
                    "frame_index": 10,
                    "x_min": 58,
                    "y_min": 48,
                    "x_max": 62,
                    "y_max": 52,
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    track_id = response.json()["id"]

    app = cast(FastAPI, client.app)
    outputs = _workflow_video_depth_3d(
        app.state.session_factory,
        cast(Any, SimpleNamespace(project_id=str(project["id"]))),
        {
            "measurement_mode": "video_depth_3d",
            "depth_source_kind": "metric_rgbd",
            "unit": "m",
            "camera_intrinsics": {"fx": 100, "fy": 100, "cx": 50, "cy": 50},
            "depth_samples": [
                {"track_id": track_id, "frame_index": 0, "depth": 2.0},
                {"track_id": track_id, "frame_index": 10, "depth": 2.0},
            ],
        },
        [
            _artifact({"video_ids": [video_id]}),
            _artifact({"video_ids": [video_id], "track_ids": [track_id]}),
        ],
    )

    artifact_type, payload = outputs["measurements"]
    assert artifact_type == "measurements"
    assert payload["measurement_mode"] == "video_depth_3d"
    assert payload["coordinate_system"] == "pinhole_camera_xyz"
    assert payload["physical_unit"] == "m"
    assert payload["provenance"]["relative_monocular_depth_is_metric"] is False
    track = payload["tracks"][0]
    assert track["sample_count"] == 2
    assert track["path_length_3d"] == pytest.approx(0.2)
    assert track["displacement_3d"] == pytest.approx(0.2)
    assert track["mean_speed_3d_per_second"] == pytest.approx(0.2)
    assert track["maximum_speed_3d_per_second"] == pytest.approx(0.2)
    assert track["depth_range"] == pytest.approx(0.0)
    assert track["trajectory"][0]["x"] == pytest.approx(0.0)
    assert track["trajectory"][1]["x"] == pytest.approx(0.2)
    assert track["trajectory"][0]["z"] == pytest.approx(2.0)


def test_relative_monocular_depth_is_rejected_for_physical_3d() -> None:
    with pytest.raises(RuntimeError, match="relative monocular depth"):
        _workflow_video_depth_3d(
            cast(Any, None),
            cast(Any, SimpleNamespace(project_id="project-1")),
            {
                "measurement_mode": "video_depth_3d",
                "depth_source_kind": "relative_monocular",
                "unit": "m",
                "camera_intrinsics": {"fx": 100, "fy": 100, "cx": 50, "cy": 50},
                "depth_samples": [
                    {"track_number": 1, "frame_index": 0, "depth": 0.2},
                    {"track_number": 1, "frame_index": 1, "depth": 0.3},
                ],
            },
            [_artifact({"video_ids": ["video-1"], "track_ids": ["track-1"]})],
        )


def test_3d_template_uses_typed_video_and_track_measurement_ports() -> None:
    install_workflow_definition_extensions()
    measurement = NODE_DEFINITIONS["measurement"]
    assert measurement.display_name == "Scientific measurement"
    assert measurement.inputs["video"] == ("video", False)
    assert measurement.inputs["tracks"] == ("tracks", False)
    assert measurement.inputs["masks"] == ("masks", False)

    template = calibrated_3d_fish_trajectory_template()
    nodes = {node.id: node for node in template.workflow.nodes}
    assert nodes["measure3d"].configuration["measurement_mode"] == "video_depth_3d"
    assert nodes["measure3d"].configuration["depth_source_kind"] == "metric_rgbd"
    assert any(
        edge.source_node_id == "video"
        and edge.source_port == "video"
        and edge.target_node_id == "measure3d"
        and edge.target_port == "video"
        for edge in template.workflow.edges
    )
    assert any(
        edge.source_node_id == "track"
        and edge.source_port == "tracks"
        and edge.target_node_id == "measure3d"
        and edge.target_port == "tracks"
        for edge in template.workflow.edges
    )
