from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project


class FakeCapture:
    def __init__(self, _path: str) -> None:
        self.opened = True

    def isOpened(self) -> bool:
        return self.opened

    def get(self, property_id: int) -> float:
        values = {
            1: 1920.0,
            2: 1080.0,
            3: 120.0,
            4: 30.0,
        }
        return values[property_id]

    def release(self) -> None:
        self.opened = False


def fake_cv2_module() -> Any:
    return SimpleNamespace(
        VideoCapture=FakeCapture,
        CAP_PROP_FRAME_WIDTH=1,
        CAP_PROP_FRAME_HEIGHT=2,
        CAP_PROP_FRAME_COUNT=3,
        CAP_PROP_FPS=4,
    )


def test_managed_video_import_deduplicates_and_serves_source_inline(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2_module())
    project = create_project(client, "Managed video import")
    content = b"fake-but-stable-video-bytes"

    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("fish.mp4", content, "video/mp4")},
    )
    assert imported.status_code == 201, imported.text
    payload = imported.json()
    assert payload["duplicate"] is False
    video = payload["video"]
    assert video["width_px"] == 1920
    assert video["height_px"] == 1080
    assert video["frame_count"] == 120
    assert video["fps"] == 30
    assert video["duration_seconds"] == 4
    assert video["metadata_json"]["source_modified"] is False

    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("renamed.mp4", content, "video/mp4")},
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["video"]["id"] == video["id"]

    listed = client.get(f"/api/v1/projects/{project['id']}/videos")
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [video["id"]]

    playback = client.get(f"/api/v1/videos/{video['id']}/content")
    assert playback.status_code == 200, playback.text
    assert playback.content == content
    assert playback.headers["content-disposition"].startswith("inline")

    deleted = client.delete(f"/api/v1/videos/{video['id']}")
    assert deleted.status_code == 204, deleted.text
    missing = client.get(f"/api/v1/videos/{video['id']}")
    assert missing.status_code == 404
