from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import VideoAsset
from reefvision.main import create_app
from reefvision.storage.projects import resolve_managed_project_path
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
            5: float(int.from_bytes(b"mp4v", byteorder="little")),
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
        CAP_PROP_FOURCC=5,
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
    assert video["metadata_json"]["codec"]

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


def test_video_import_rejects_invalid_media_and_uses_safe_managed_paths(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    project = create_project(client, "Video import validation")
    missing = client.post(f"/api/v1/projects/{project['id']}/imports/videos")
    assert missing.status_code == 422, missing.text

    unsupported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("fish.txt", b"not-video", "text/plain")},
    )
    assert unsupported.status_code == 400, unsupported.text
    wrong_media_type = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("fish.mp4", b"not-video", "text/plain")},
    )
    assert wrong_media_type.status_code == 400, wrong_media_type.text

    class ClosedCapture(FakeCapture):
        def __init__(self, path: str) -> None:
            super().__init__(path)
            self.opened = False

    monkeypatch.setitem(
        sys.modules,
        "cv2",
        SimpleNamespace(
            **{
                **vars(fake_cv2_module()),
                "VideoCapture": ClosedCapture,
            }
        ),
    )
    unreadable = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("fish.mp4", b"not-a-decodable-video", "video/mp4")},
    )
    assert unreadable.status_code == 400, unreadable.text

    monkeypatch.setitem(sys.modules, "cv2", fake_cv2_module())
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("../../outside.mp4", b"safe-video", "video/mp4")},
    )
    assert imported.status_code == 201, imported.text
    app = client.app
    assert isinstance(app, FastAPI)
    with app.state.session_factory() as session:
        video = session.get(VideoAsset, imported.json()["video"]["id"])
        assert video is not None
        assert ".." not in Path(video.managed_path).parts
        resolved = resolve_managed_project_path(app.state.settings, video.managed_path)
        assert resolved.is_relative_to(app.state.settings.resolved_data_dir.resolve())
        assert resolved.read_bytes() == b"safe-video"
    assert not list(app.state.settings.resolved_data_dir.rglob("*.upload"))


def test_imported_video_remains_readable_after_application_restart(
    test_settings: Settings,
    monkeypatch: Any,
) -> None:
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2_module())
    first_app = create_app(test_settings)
    Base.metadata.create_all(first_app.state.engine)
    content = b"restart-safe-video"
    with TestClient(first_app) as first_client:
        project = create_project(first_client, "Restart-safe video")
        imported = first_client.post(
            f"/api/v1/projects/{project['id']}/imports/videos",
            files={"file": ("restart.mp4", content, "video/mp4")},
        )
        assert imported.status_code == 201, imported.text
        video_id = imported.json()["video"]["id"]

    second_app = create_app(test_settings)
    try:
        with TestClient(second_app) as second_client:
            reopened = second_client.get(f"/api/v1/videos/{video_id}")
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()["original_filename"] == "restart.mp4"
            playback = second_client.get(f"/api/v1/videos/{video_id}/content")
            assert playback.status_code == 200, playback.text
            assert playback.content == content
    finally:
        Base.metadata.drop_all(second_app.state.engine)
        second_app.state.engine.dispose()
