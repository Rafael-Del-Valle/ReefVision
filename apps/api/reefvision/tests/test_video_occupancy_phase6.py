from __future__ import annotations

import io
from typing import cast

import pytest
from fastapi.testclient import TestClient

from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 100,
        "height_px": 100,
        "frame_count": 5,
        "fps": 10.0,
        "duration_seconds": 0.5,
    }


def _track(
    client: TestClient,
    video_id: str,
    label_class_id: str,
    x: float,
    y: float,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "label_class_id": label_class_id,
            "keyframes": [
                {"frame": 0, "bbox": [x, y, 10, 10]},
                {"frame": 2, "bbox": [x, y, 10, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_two_tracks_occupy_expected_grid_cells_and_fish_seconds(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Occupancy analytics")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("occupancy.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert imported.status_code == 201, imported.text
    video_id = str(imported.json()["id"])
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])
    first = _track(client, video_id, label_class_id, 0, 0)
    second = _track(client, video_id, label_class_id, 50, 50)

    response = client.post(
        f"/api/v1/videos/{video_id}/occupancy-analytics",
        json={
            "track_ids": [first["id"], second["id"]],
            "grid_rows": 2,
            "grid_columns": 2,
            "start_frame": 0,
            "end_frame": 2,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schema_version"] == "video-occupancy-0001"
    assert result["trajectory_policy"] == "configured_track_interpolation"
    assert result["frames_with_tracks"] == 3
    assert result["track_frame_observations"] == 6
    assert result["total_track_seconds"] == pytest.approx(0.6)
    assert len(result["cells"]) == 4

    cells = {(item["row"], item["column"]): item for item in result["cells"]}
    upper_left = cells[(0, 0)]
    lower_right = cells[(1, 1)]
    assert upper_left["observation_count"] == 3
    assert upper_left["observation_fraction"] == pytest.approx(0.5)
    assert upper_left["occupied_frame_count"] == 3
    assert upper_left["occupied_frame_fraction"] == pytest.approx(1.0)
    assert upper_left["unique_track_count"] == 1
    assert upper_left["dwell_seconds"] == pytest.approx(0.3)
    assert lower_right["observation_count"] == 3
    assert lower_right["observation_fraction"] == pytest.approx(0.5)
    assert lower_right["dwell_seconds"] == pytest.approx(0.3)
    assert cells[(0, 1)]["observation_count"] == 0
    assert cells[(1, 0)]["observation_count"] == 0
    assert sum(item["observation_fraction"] for item in result["cells"]) == pytest.approx(
        1.0
    )

    per_track = {item["track_id"]: item for item in result["per_track"]}
    assert per_track[first["id"]]["observation_count"] == 3
    assert per_track[first["id"]]["occupied_cell_count"] == 1
    assert per_track[first["id"]]["most_occupied_row"] == 0
    assert per_track[first["id"]]["most_occupied_column"] == 0
    assert per_track[first["id"]]["most_occupied_fraction"] == pytest.approx(1.0)
    assert per_track[second["id"]]["most_occupied_row"] == 1
    assert per_track[second["id"]]["most_occupied_column"] == 1


def test_occupancy_rejects_frame_range_without_selected_track_observations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Empty occupancy range")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("occupancy.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert imported.status_code == 201
    video_id = str(imported.json()["id"])
    classes = cast(list[dict[str, object]], project["label_classes"])
    track = _track(client, video_id, str(classes[0]["id"]), 0, 0)

    response = client.post(
        f"/api/v1/videos/{video_id}/occupancy-analytics",
        json={
            "track_ids": [track["id"]],
            "grid_rows": 3,
            "grid_columns": 3,
            "start_frame": 3,
            "end_frame": 4,
        },
    )
    assert response.status_code == 422
    assert "no observations" in response.text
