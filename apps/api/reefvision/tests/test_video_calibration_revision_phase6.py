from __future__ import annotations

import io
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 200,
        "height_px": 100,
        "frame_count": 10,
        "fps": 10.0,
        "duration_seconds": 1.0,
    }


def test_calibration_revision_and_timestamp_are_monotonic_and_reopenable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Revisioned calibration")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("calibration.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert imported.status_code == 201, imported.text
    video_id = str(imported.json()["id"])
    initial_video_revision = int(imported.json()["revision"])

    first = client.put(
        f"/api/v1/videos/{video_id}/calibration",
        json={
            "unit": "cm",
            "reference_distance": 10,
            "reference_pixels": 100,
            "method": "tank ruler",
            "reference_label": "10 cm ruler",
        },
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["calibration_revision"] == 1
    assert first_payload["video_revision"] == initial_video_revision + 1
    first_updated = datetime.fromisoformat(first_payload["calibration_updated_at"])

    reopened = client.get(f"/api/v1/videos/{video_id}/calibration")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["calibration_revision"] == 1
    assert reopened.json()["calibration_updated_at"] == first_payload["calibration_updated_at"]

    second = client.put(
        f"/api/v1/videos/{video_id}/calibration",
        json={
            "unit": "cm",
            "reference_distance": 5,
            "reference_pixels": 60,
            "method": "tank ruler",
            "reference_label": "5 cm ruler",
            "notes": "Updated scale after camera repositioning",
        },
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["calibration_revision"] == 2
    assert second_payload["video_revision"] == initial_video_revision + 2
    assert second_payload["pixels_per_unit"] == pytest.approx(12.0)
    second_updated = datetime.fromisoformat(second_payload["calibration_updated_at"])
    assert second_updated >= first_updated

    reopened_again = client.get(f"/api/v1/videos/{video_id}/calibration")
    assert reopened_again.status_code == 200
    assert reopened_again.json() == second_payload
