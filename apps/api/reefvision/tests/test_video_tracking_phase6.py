from __future__ import annotations

import io
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration
from reefvision.jobs import video_tracking as tracking_module
from reefvision.ml.video_tracking import (
    TrackObservation,
    VideoTrackingCancellationCheck,
    VideoTrackingProgress,
    VideoTrackingProgressCallback,
)
from reefvision.schemas.georeferenced_observation import BoundingBoxPixels
from reefvision.services import video_assets as video_assets_module
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


class FakeVideoTrackingProvider:
    provider_id = "ultralytics"

    @property
    def provider_version(self) -> str:
        return "test-tracker"

    def track(
        self,
        checkpoint_path: Path,
        video_path: Path,
        *,
        tracker: str,
        mode: str,
        confidence: float,
        iou: float,
        device: str,
        on_progress: VideoTrackingProgressCallback | None = None,
        should_cancel: VideoTrackingCancellationCheck | None = None,
    ) -> list[TrackObservation]:
        assert checkpoint_path.read_bytes() == b"fake-detector"
        assert video_path.read_bytes() == b"fake-video"
        assert tracker == "bytetrack.yaml"
        assert mode == "track"
        assert confidence == pytest.approx(0.2)
        assert iou == pytest.approx(0.4)
        assert device == "cpu"

        observations = [
            TrackObservation(
                frame=0,
                provider_track_id=7,
                class_name="fish",
                confidence=0.9,
                bbox=(10, 10, 20, 10),
            ),
            TrackObservation(
                frame=1,
                provider_track_id=7,
                class_name="fish",
                confidence=0.8,
                bbox=(20, 10, 20, 10),
            ),
            TrackObservation(
                frame=2,
                provider_track_id=7,
                class_name="fish",
                confidence=0.85,
                bbox=(30, 10, 20, 10),
            ),
        ]

        for index in range(3):
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
        "frame_count": 30,
        "fps": 10.0,
        "duration_seconds": 3.0,
    }


def _import_video(
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


def test_managed_video_import_extraction_and_track_analytics(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Phase 6 managed video")
    video = _import_video(client, str(project["id"]), monkeypatch)
    assert video["frame_count"] == 30
    assert video["fps"] == pytest.approx(10.0)
    assert video["status"] == "imported"

    extraction = client.post(
        f"/api/v1/videos/{video['id']}/extract",
        json={"every_n_frames": 5},
    )
    assert extraction.status_code == 200, extraction.text
    queued = client.get(f"/api/v1/videos/{video['id']}")
    assert queued.status_code == 200, queued.text
    assert queued.json()["status"] == "extracting"
    assert queued.json()["extraction_job_id"] == extraction.json()["id"]

    classes = cast(list[dict[str, object]], project["label_classes"])
    track = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": str(classes[0]["id"]),
            "keyframes": [
                {"frame": 0, "bbox": [10, 10, 20, 10]},
                {"frame": 10, "bbox": [30, 10, 20, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert track.status_code == 201, track.text
    track_payload = track.json()
    assert track_payload["revision"] == 1

    interpolation = client.get(f"/api/v1/video-tracks/{track_payload['id']}/interpolation")
    assert interpolation.status_code == 200, interpolation.text
    frames = interpolation.json()["frames"]
    assert len(frames) == 11
    assert frames[5]["bbox"] == pytest.approx([20, 10, 20, 10])
    assert frames[5]["source"] == "interpolated"

    analytics = client.get(f"/api/v1/video-tracks/{track_payload['id']}/analytics")
    assert analytics.status_code == 200, analytics.text
    summary = analytics.json()
    assert summary["duration_seconds"] == pytest.approx(1.0)
    assert summary["path_length_pixels"] == pytest.approx(20.0)
    assert summary["mean_speed_pixels_per_second"] == pytest.approx(20.0)
    assert sum(summary["occupancy_grid"].values()) == 11

    stale = client.put(
        f"/api/v1/video-tracks/{track_payload['id']}",
        json={
            "base_revision": 0,
            "label_class_id": str(classes[0]["id"]),
            "keyframes": [{"frame": 0, "bbox": [10, 10, 20, 10]}],
            "interpolation": "hold",
            "status": "verified",
        },
    )
    assert stale.status_code == 422


def test_fake_detector_tracker_creates_editable_machine_track(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Phase 6 tracker")
    video = _import_video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])
    app = cast(FastAPI, client.app)
    model_id = "b4c0e265-28f4-43c8-bda8-1d73d48ff34b"
    managed_relative = f"{project['storage_root']}/models/{model_id}.pt"
    managed_path = resolve_managed_project_path(app.state.settings, managed_relative)
    managed_path.parent.mkdir(parents=True, exist_ok=True)
    managed_path.write_bytes(b"fake-detector")
    with app.state.session_factory() as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=str(project["id"]),
                purpose="detector",
                display_name="Fish detector",
                source_filename="fish.pt",
                managed_path=managed_relative,
                sha256="a" * 64,
                file_size_bytes=len(b"fake-detector"),
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
        lambda _name: FakeVideoTrackingProvider(),
    )
    queued = client.post(
        f"/api/v1/videos/{video['id']}/tracking-jobs",
        json={
            "model_id": model_id,
            "mode": "track",
            "tracker": "bytetrack.yaml",
            "confidence": 0.2,
            "iou": 0.4,
            "device": "cpu",
            "minimum_track_frames": 2,
        },
    )
    assert queued.status_code == 200, queued.text
    assert tracking_module.process_video_tracking_job(
        app.state.settings,
        app.state.session_factory,
        queued.json()["id"],
    )
    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks")
    assert tracks.status_code == 200, tracks.text
    job_id = queued.json()["id"]

    runs = client.get(f"/api/v1/videos/{video['id']}/tracking-runs")
    assert runs.status_code == 200, runs.text
    run = next(item for item in runs.json() if item["job_id"] == job_id)

    assert run["progress_current"] == 30
    assert run["progress_total"] == 30
    assert run["stage"] == "completed"
    assert run["live_detection_count"] == 3
    assert run["live_observation_count"] == 3
    assert run["live_tracks_seen"] == 1
    assert run["heartbeat_at"] is not None
    assert run["stale"] is False

    machine_tracks = [item for item in tracks.json() if item["source_job_id"] == job_id]
    assert len(machine_tracks) == 1
    machine = machine_tracks[0]
    assert machine["source_model_id"] == model_id
    assert machine["status"] == "machine_generated"
    assert len(machine["keyframes_json"]) == 3
    assert machine["metadata_json"]["provider_track_id"] == 7

    updated = client.put(
        f"/api/v1/video-tracks/{machine['id']}",
        json={
            "base_revision": machine["revision"],
            "label_class_id": label_class_id,
            "keyframes": machine["keyframes_json"],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == machine["revision"] + 1
    assert updated.json()["status"] == "verified"


class FakeGeoPersistence:
    def __init__(self) -> None:
        self.observations: list[object] = []

    def persist(
        self,
        observation: object,
        *,
        configuration_hash: str | None = None,
    ) -> None:
        self.observations.append(observation)
        return observation


def test_task11_yolo_bbox_is_fed_to_georeferencing() -> None:
    observation = TrackObservation(
        frame=12,
        provider_track_id=7,
        class_name="fish",
        confidence=0.91,
        bbox=(10.0, 12.0, 20.0, 8.0),
    )

    bbox = tracking_module._bounding_box_pixels(observation)

    assert bbox.x_min == pytest.approx(10.0)
    assert bbox.y_min == pytest.approx(12.0)
    assert bbox.x_max == pytest.approx(30.0)
    assert bbox.y_max == pytest.approx(20.0)

    class FakeGeoreferencingService:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def configuration_hash(
            self,
            _video_id: str,
            *,
            max_delta_s: float = 0.1,
        ) -> str:
            assert max_delta_s == 0.1
            return "d" * 64

        def georeference_detection(
            self,
            video_id: str,
            **kwargs: object,
        ) -> object:
            self.calls.append(
                {
                    "video_id": video_id,
                    **kwargs,
                }
            )
            return object()

    service = FakeGeoreferencingService()
    persistence = FakeGeoPersistence()

    successful, failed = tracking_module._georeference_track_observations(
        service,  # type: ignore[arg-type]
        persistence,  # type: ignore[arg-type]
        video_id="video-id",
        track_id="track-id",
        observations=[observation],
    )

    assert successful == 1
    assert failed == 0
    assert len(service.calls) == 1
    assert len(persistence.observations) == 1

    call = service.calls[0]

    assert call["video_id"] == "video-id"
    assert call["frame_index"] == 12
    assert call["track_id"] == "track-id"

    projected_bbox = call["bbox"]

    assert isinstance(projected_bbox, BoundingBoxPixels)
    assert projected_bbox.x_min == pytest.approx(10.0)
    assert projected_bbox.y_min == pytest.approx(12.0)
    assert projected_bbox.x_max == pytest.approx(30.0)
    assert projected_bbox.y_max == pytest.approx(20.0)

    # Task 11 intentionally supplies no explicit representative pixel.
    # Task 9 therefore selects the bbox center:
    # x = (10 + 30) / 2 = 20
    # y = (12 + 20) / 2 = 16
    assert "representative_pixel" not in call


def test_task11_invalid_yolo_bbox_is_counted_as_failure() -> None:
    observation = TrackObservation(
        frame=12,
        provider_track_id=7,
        class_name="fish",
        confidence=0.91,
        bbox=(10.0, 12.0, -20.0, 8.0),
    )

    class FakeGeoreferencingService:
        def configuration_hash(
            self,
            _video_id: str,
            *,
            max_delta_s: float = 0.1,
        ) -> str:
            assert max_delta_s == 0.1
            return "d" * 64

        def georeference_detection(
            self,
            video_id: str,
            **kwargs: object,
        ) -> object:
            raise AssertionError("Invalid YOLO geometry should fail before projection")

    persistence = FakeGeoPersistence()

    successful, failed = tracking_module._georeference_track_observations(
        FakeGeoreferencingService(),  # type: ignore[arg-type]
        persistence,  # type: ignore[arg-type]
        video_id="video-id",
        track_id="track-id",
        observations=[observation],
    )

    assert successful == 0
    assert failed == 1
    assert persistence.observations == []


def test_task12b_tracking_job_persists_geographic_observations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from uuid import uuid4

    from reefvision.schemas.georeferenced_observation import (
        GeoReferencedObservation,
    )
    from reefvision.services.georeferenced_observations import (
        GeoReferencedObservationService,
    )

    class ReadyService:
        def __init__(self, session, settings) -> None:
            self.session = session
            self.settings = settings

        def evaluate(self, video_id: str) -> object:
            return SimpleNamespace(
                ready=True,
                issues=[],
            )

    class FakeGeoService:
        def __init__(self, session, settings) -> None:
            self.session = session
            self.settings = settings

        def configuration_hash(
            self,
            _video_id: str,
            *,
            max_delta_s: float = 0.1,
        ) -> str:
            assert max_delta_s == 0.1
            return "d" * 64

        def georeference_detection(
            self,
            video_id: str,
            *,
            frame_index: int,
            bbox: BoundingBoxPixels,
            track_id: str,
            **_kwargs: object,
        ) -> GeoReferencedObservation:
            video_record = self.session.get(
                tracking_module.VideoAsset,
                video_id,
            )

            assert video_record is not None

            center_x = (bbox.x_min + bbox.x_max) / 2.0
            center_y = (bbox.y_min + bbox.y_max) / 2.0

            return GeoReferencedObservation.model_validate(
                {
                    "id": uuid4(),
                    "project_id": video_record.project_id,
                    "video_asset_id": video_record.id,
                    "detection_id": None,
                    "track_id": track_id,
                    "frame_index": frame_index,
                    "frame_width_px": video_record.width_px,
                    "frame_height_px": video_record.height_px,
                    "bbox": bbox.model_dump(),
                    "representative_pixel": {
                        "x": center_x,
                        "y": center_y,
                        "method": "bbox_center",
                    },
                    "timestamp": {
                        "frame_time_s": (frame_index / video_record.fps),
                        "utc": None,
                        "source": "frame_index_fps",
                        "fps": video_record.fps,
                    },
                    "pose": {
                        "platform": {
                            "latitude_deg": 32.75,
                            "longitude_deg": -79.93,
                            "altitude_m": 100.0,
                            "altitude_datum": ("relative_takeoff"),
                            "height_above_surface_m": 105.0,
                            "yaw_deg": None,
                            "pitch_deg": None,
                            "roll_deg": None,
                            "heading_reference": "unknown",
                        },
                        "camera": {
                            "yaw_deg": 0.0,
                            "pitch_deg": -90.0,
                            "roll_deg": 0.0,
                            "orientation_source": ("gimbal_telemetry"),
                        },
                    },
                    "calibration": {
                        "calibration_id": ("sha256:" + ("b" * 64)),
                        "calibration_version": "1",
                        "checksum_sha256": "b" * 64,
                        "camera_model": "test-camera",
                        "image_width_px": (video_record.width_px),
                        "image_height_px": (video_record.height_px),
                        "focal_length_x_px": 50.0,
                        "focal_length_y_px": 50.0,
                        "principal_point_x_px": (video_record.width_px / 2.0),
                        "principal_point_y_px": (video_record.height_px / 2.0),
                        "distortion_model": "none",
                        "zoom_state": 1.0,
                    },
                    "telemetry": {
                        "source_id": "test.srt",
                        "source_type": "dji_srt",
                        "sample_index": frame_index,
                        "synchronization_method": "nearest",
                        "telemetry_time_s": (frame_index / video_record.fps),
                        "telemetry_utc": None,
                        "signed_time_delta_ms": 0.0,
                        "absolute_time_error_ms": 0.0,
                        "within_sync_tolerance": True,
                        "sync_tolerance_ms": 100.0,
                        "field_provenance": {
                            "position_source": "dji_srt",
                        },
                    },
                    "location": {
                        "latitude_deg": (32.75 + frame_index * 0.000001),
                        "longitude_deg": (-79.93 + frame_index * 0.000001),
                    },
                    "uncertainty": {
                        "available": False,
                        "method": "not_estimated",
                        "reason_unavailable": ("Integration test."),
                    },
                    "method": {
                        "version": ("opencv-dji-enu-flat-wgs84-v1"),
                        "surface_model": ("local_horizontal_plane"),
                        "representative_pixel_policy_version": ("1.0.0"),
                        "synchronization_version": ("nearest-frame-time-v1"),
                        "pose_convention_version": ("absolute-gimbal-ned-to-enu-v1"),
                    },
                    "created_at": datetime.now(UTC),
                }
            )

    project = create_project(
        client,
        "Task 12B tracking persistence",
    )

    video = _import_video(
        client,
        str(project["id"]),
        monkeypatch,
    )

    classes = cast(
        list[dict[str, object]],
        project["label_classes"],
    )

    label_class_id = str(classes[0]["id"])

    app = cast(FastAPI, client.app)

    model_id = "4bc1b230-d27c-4d89-a59a-60d7c32c39d6"

    managed_relative = f"{project['storage_root']}/models/{model_id}.pt"

    managed_path = resolve_managed_project_path(
        app.state.settings,
        managed_relative,
    )

    managed_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    managed_path.write_bytes(b"fake-detector")

    with app.state.session_factory() as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=str(project["id"]),
                purpose="detector",
                display_name="Task 12B detector",
                source_filename="task12b.pt",
                managed_path=managed_relative,
                sha256="c" * 64,
                file_size_bytes=len(b"fake-detector"),
                framework="ultralytics",
                task="detect",
                provider_name="ultralytics",
                provider_version="test",
                class_map_json={
                    "labels": ["fish"],
                    "mapping": {
                        "fish": label_class_id,
                    },
                },
                input_size_json={
                    "width": 640,
                    "height": 640,
                },
                metadata_json={},
            )
        )
        session.commit()

    monkeypatch.setattr(
        tracking_module,
        "video_tracking_provider_for_name",
        lambda _name: FakeVideoTrackingProvider(),
    )

    monkeypatch.setattr(
        tracking_module,
        "VideoGeoreferencingReadinessService",
        ReadyService,
    )

    monkeypatch.setattr(
        tracking_module,
        "VideoGeoreferencingService",
        FakeGeoService,
    )

    queued = client.post(
        f"/api/v1/videos/{video['id']}/tracking-jobs",
        json={
            "model_id": model_id,
            "mode": "track",
            "tracker": "bytetrack.yaml",
            "confidence": 0.2,
            "iou": 0.4,
            "device": "cpu",
            "minimum_track_frames": 2,
        },
    )

    assert queued.status_code == 200, queued.text

    job_id = queued.json()["id"]

    assert tracking_module.process_video_tracking_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    tracks_response = client.get(f"/api/v1/videos/{video['id']}/tracks")

    assert tracks_response.status_code == 200

    machine_tracks = [item for item in tracks_response.json() if item["source_job_id"] == job_id]

    assert len(machine_tracks) == 1

    track_id = machine_tracks[0]["id"]

    with app.state.session_factory() as session:
        persistence = GeoReferencedObservationService(session)

        by_video = persistence.list_for_video(str(video["id"]))

        by_track = persistence.list_for_track(track_id)

        assert len(by_video) == 3
        assert len(by_track) == 3

        assert [item.frame_index for item in by_track] == [0, 1, 2]

        assert all(item.track_id == track_id for item in by_track)

        assert all(item.representative_pixel_method == "bbox_center" for item in by_track)

        assert all(item.configuration_hash == "d" * 64 for item in by_track)

        assert all(item.is_stale is False for item in by_track)

        assert all(item.stale_reason is None for item in by_track)

        assert (
            len(
                persistence.list_for_frame(
                    str(video["id"]),
                    1,
                )
            )
            == 1
        )

        job = session.get(
            tracking_module.Job,
            job_id,
        )

        assert job is not None

        result = dict(job.result_json or {})

        assert result["georeferencing_ready"] is True

        assert result["georeferencing_attempted_count"] == 3

        assert result["georeferenced_observation_count"] == 3

        assert result["georeferencing_failure_count"] == 0


def test_task20c_tracking_without_georeferencing_readiness_creates_no_coordinates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Phase 6 tracker")
    video = _import_video(client, str(project["id"]), monkeypatch)
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])
    app = cast(FastAPI, client.app)
    model_id = "b4c0e265-28f4-43c8-bda8-1d73d48ff34b"
    managed_relative = f"{project['storage_root']}/models/{model_id}.pt"
    managed_path = resolve_managed_project_path(app.state.settings, managed_relative)
    managed_path.parent.mkdir(parents=True, exist_ok=True)
    managed_path.write_bytes(b"fake-detector")
    with app.state.session_factory() as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=str(project["id"]),
                purpose="detector",
                display_name="Fish detector",
                source_filename="fish.pt",
                managed_path=managed_relative,
                sha256="a" * 64,
                file_size_bytes=len(b"fake-detector"),
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
        lambda _name: FakeVideoTrackingProvider(),
    )
    queued = client.post(
        f"/api/v1/videos/{video['id']}/tracking-jobs",
        json={
            "model_id": model_id,
            "mode": "track",
            "tracker": "bytetrack.yaml",
            "confidence": 0.2,
            "iou": 0.4,
            "device": "cpu",
            "minimum_track_frames": 2,
        },
    )
    assert queued.status_code == 200, queued.text
    assert tracking_module.process_video_tracking_job(
        app.state.settings,
        app.state.session_factory,
        queued.json()["id"],
    )
    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks")
    assert tracks.status_code == 200, tracks.text
    job_id = queued.json()["id"]

    runs = client.get(f"/api/v1/videos/{video['id']}/tracking-runs")
    assert runs.status_code == 200, runs.text
    run = next(item for item in runs.json() if item["job_id"] == job_id)

    assert run["progress_current"] == 30
    assert run["progress_total"] == 30
    assert run["stage"] == "completed"
    assert run["live_detection_count"] == 3
    assert run["live_observation_count"] == 3
    assert run["live_tracks_seen"] == 1
    assert run["heartbeat_at"] is not None
    assert run["stale"] is False

    machine_tracks = [item for item in tracks.json() if item["source_job_id"] == job_id]
    assert len(machine_tracks) == 1
    machine = machine_tracks[0]
    assert machine["source_model_id"] == model_id
    assert machine["status"] == "machine_generated"
    assert len(machine["keyframes_json"]) == 3
    assert machine["metadata_json"]["provider_track_id"] == 7

    updated = client.put(
        f"/api/v1/video-tracks/{machine['id']}",
        json={
            "base_revision": machine["revision"],
            "label_class_id": label_class_id,
            "keyframes": machine["keyframes_json"],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == machine["revision"] + 1
    assert updated.json()["status"] == "verified"

    # Task 20C production-path acceptance:
    # this ordinary tracking job has no complete geographic
    # readiness setup. Tracking itself must still succeed,
    # while no geographic observations are fabricated.

    from reefvision.services.georeferenced_observations import (
        GeoReferencedObservationService,
    )

    app = client.app

    assert isinstance(app, FastAPI)

    with app.state.session_factory() as session:
        persistence = GeoReferencedObservationService(session)

        geographic = persistence.list_for_video(str(video["id"]))

        assert geographic == []

        job = session.get(
            tracking_module.Job,
            job_id,
        )

        assert job is not None

        result = dict(job.result_json or {})

        assert result["georeferencing_ready"] is False

        assert result["georeferencing_attempted_count"] == 0

        assert result["georeferenced_observation_count"] == 0

        assert result["georeferencing_failure_count"] == 0

        issue_codes = result["georeferencing_issue_codes"]

        assert isinstance(
            issue_codes,
            list,
        )

        assert issue_codes
