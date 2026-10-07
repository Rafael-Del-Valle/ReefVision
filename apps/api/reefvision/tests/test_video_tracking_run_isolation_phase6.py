from __future__ import annotations

import io
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, ModelRegistration
from reefvision.jobs import video_tracking as tracking_module
from reefvision.ml.video_tracking import (
    TrackObservation,
    VideoTrackingCancellationCheck,
    VideoTrackingProgress,
    VideoTrackingProgressCallback,
)
from reefvision.services import video_assets as video_assets_module
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


class MultiTrackerProvider:
    provider_id = "ultralytics"

    @property
    def provider_version(self) -> str:
        return "test-multi-tracker"

    def track(
        self,
        checkpoint_path: Path,
        video_path: Path,
        *,
        tracker: str,
        confidence: float,
        iou: float,
        device: str,
        link_detections: bool = True,
        on_progress: VideoTrackingProgressCallback | None = None,
        should_cancel: VideoTrackingCancellationCheck | None = None,
    ) -> list[TrackObservation]:
        assert checkpoint_path.read_bytes() == b"detector"
        assert video_path.read_bytes() == b"video"
        assert link_detections is True

        provider_track_id = 7 if tracker == "bytetrack.yaml" else 8
        x = 10 if tracker == "bytetrack.yaml" else 20

        observations = [
            TrackObservation(
                frame=0,
                provider_track_id=provider_track_id,
                class_name="fish",
                confidence=0.9,
                bbox=(x, 10, 20, 10),
            ),
            TrackObservation(
                frame=1,
                provider_track_id=provider_track_id,
                class_name="fish",
                confidence=0.8,
                bbox=(x + 2, 10, 20, 10),
            ),
        ]

        for index in range(2):
            assert should_cancel is None or not should_cancel()

            if on_progress is not None:
                on_progress(
                    VideoTrackingProgress(
                        frames_processed=index + 1,
                        detections_seen=index + 1,
                        tracked_observations_seen=index + 1,
                        unique_tracks_seen=1,
                    )
                )

        return observations


def _fake_metadata(_path: Path) -> dict[str, float | int]:
    return {
        "width_px": 100,
        "height_px": 60,
        "frame_count": 10,
        "fps": 10.0,
        "duration_seconds": 1.0,
    }


def test_separate_tracker_jobs_from_same_model_keep_both_track_sets(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Independent tracker runs")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("fish.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert imported.status_code == 201, imported.text
    video_id = str(imported.json()["id"])
    label_class_id = str(cast(list[dict[str, object]], project["label_classes"])[0]["id"])

    app = cast(FastAPI, client.app)
    model_id = "aa69a9ba-896b-4df7-a954-88ba75370878"
    managed_relative = f"{project['storage_root']}/models/{model_id}.pt"
    managed_path = resolve_managed_project_path(app.state.settings, managed_relative)
    managed_path.parent.mkdir(parents=True, exist_ok=True)
    managed_path.write_bytes(b"detector")
    with app.state.session_factory() as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=str(project["id"]),
                purpose="detector",
                display_name="Fish detector",
                source_filename="fish.pt",
                managed_path=managed_relative,
                sha256="b" * 64,
                file_size_bytes=len(b"detector"),
                framework="ultralytics",
                task="detect",
                provider_name="ultralytics",
                provider_version="test",
                class_map_json={"labels": ["fish"], "mapping": {"fish": label_class_id}},
                input_size_json={"width": 640, "height": 640},
                metadata_json={},
            )
        )
        session.commit()

    monkeypatch.setattr(
        tracking_module,
        "video_tracking_provider_for_name",
        lambda _name: MultiTrackerProvider(),
    )

    job_ids: list[str] = []
    for tracker in ("bytetrack.yaml", "botsort.yaml"):
        queued = client.post(
            f"/api/v1/videos/{video_id}/tracking-jobs",
            json={
                "model_id": model_id,
                "tracker": tracker,
                "confidence": 0.25,
                "iou": 0.5,
                "device": "cpu",
                "minimum_track_frames": 2,
            },
        )
        assert queued.status_code == 200, queued.text
        job_id = str(queued.json()["id"])
        assert tracking_module.process_video_tracking_job(
            app.state.settings,
            app.state.session_factory,
            job_id,
        )
        job_ids.append(job_id)

    tracks = client.get(f"/api/v1/videos/{video_id}/tracks")
    assert tracks.status_code == 200, tracks.text
    machine_tracks = [item for item in tracks.json() if item["source_job_id"] in job_ids]
    assert len(machine_tracks) == 2
    assert {item["source_job_id"] for item in machine_tracks} == set(job_ids)
    assert {item["metadata_json"]["tracker"] for item in machine_tracks} == {
        "bytetrack.yaml",
        "botsort.yaml",
    }

    with app.state.session_factory() as session:
        first_job = session.get(Job, job_ids[0])
        second_job = session.get(Job, job_ids[1])
        assert first_job is not None and first_job.result_json is not None
        assert second_job is not None and second_job.result_json is not None
        assert first_job.result_json["tracker"] == "bytetrack.yaml"
        assert second_job.result_json["tracker"] == "botsort.yaml"
        assert first_job.result_json["model_id"] == model_id
        assert second_job.result_json["model_id"] == model_id
