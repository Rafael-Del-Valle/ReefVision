from __future__ import annotations

import io
from typing import cast

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job
from reefvision.jobs import video_metric_depth as depth_job
from reefvision.ml.video_depth_anything import VideoMetricDepthInference
from reefvision.services import video_assets as video_assets_module
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 100,
        "height_px": 60,
        "frame_count": 3,
        "fps": 10.0,
        "duration_seconds": 0.3,
    }


def _video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": ("fish.mp4", io.BytesIO(b"fake-video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


class FakeMetricDepthProvider:
    provider_id = "video_depth_anything"
    provider_version = "test"

    def infer(self, *_args: object, **_kwargs: object) -> VideoMetricDepthInference:
        return VideoMetricDepthInference(
            depths=np.full((3, 60, 100), 2.0, dtype=np.float32),
            fps=10.0,
            input_size_used=392,
            device="cpu",
            model_repo="depth-anything/Metric-Video-Depth-Anything-Small",
            model_revision="test-revision",
            model_sha256="a" * 64,
            source_commit="test-source",
            decoded_frame_count=3,
            warnings=[],
        )


def test_metric_depth_3d_job_generates_track_depth_and_xyz(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Metric fish 3D")
    video = _video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    track = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": str(classes[0]["id"]),
            "keyframes": [
                {"frame": 0, "bbox": [10, 10, 20, 10]},
                {"frame": 2, "bbox": [30, 10, 20, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert track.status_code == 201, track.text
    track_payload = track.json()

    intrinsics = client.put(
        f"/api/v1/videos/{video['id']}/camera-intrinsics",
        json={
            "fx_px": 100,
            "fy_px": 100,
            "cx_px": 50,
            "cy_px": 30,
            "method": "test_camera_calibration",
        },
    )
    assert intrinsics.status_code == 200, intrinsics.text

    queued = client.post(
        f"/api/v1/videos/{video['id']}/metric-depth-3d-jobs",
        json={
            "track_ids": [track_payload["id"]],
            "device": "cpu",
            "input_size": 392,
            "max_res": 1280,
            "allow_model_download": False,
        },
    )
    assert queued.status_code == 200, queued.text
    assert queued.json()["job_type"] == "video_metric_depth_3d"

    monkeypatch.setattr(
        depth_job,
        "metric_video_depth_provider",
        lambda _settings: FakeMetricDepthProvider(),
    )
    app = cast(FastAPI, client.app)
    assert depth_job.process_video_metric_depth_job(
        app.state.settings,
        app.state.session_factory,
        queued.json()["id"],
    )

    with app.state.session_factory() as session:
        job = session.get(Job, queued.json()["id"])
        assert job is not None
        assert job.status == "succeeded"
        result = dict(job.result_json or {})
        assert result["depth_tier"] == "model_estimated_metric"
        assert result["physical_measurement_claim_allowed"] is False
        assert result["metric_depth_sample_count"] == 3
        assert result["analyzed_track_ids"] == [track_payload["id"]]
        assert result["depth_preview"]["display_min_m"] == pytest.approx(1.98)
        assert result["depth_preview"]["display_max_m"] == pytest.approx(2.02)
        assert result["depth_preview"]["colorization_only"] is True
        analytics = result["analytics"]
        assert analytics["tracks"][0]["observed_frame_count"] == 3
        assert analytics["tracks"][0]["mean_depth"] == pytest.approx(2.0)

        from reefvision.storage.projects import resolve_managed_project_path

        persisted = resolve_managed_project_path(
            app.state.settings,
            result["depth_stack_path"],
        )
        assert persisted.is_file()
        loaded = np.load(persisted, allow_pickle=False)["depths"]
        assert loaded.shape == (3, 60, 100)

    preview = client.get(
        f"/api/v1/videos/{video['id']}/metric-depth-3d-jobs/{queued.json()['id']}/depth-preview",
        params={"frame": 1},
    )
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert preview.headers["x-reefvision-depth-tier"] == ("model_estimated_metric")
    assert preview.headers["x-reefvision-depth-scaling"] == (
        "global_positive_depth_percentile_2_98"
    )
