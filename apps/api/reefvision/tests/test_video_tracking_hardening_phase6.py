from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import Job, ModelRegistration, VideoTrack
from reefvision.jobs.video import process_video_extract_job
from reefvision.jobs.video_exports import process_video_render_export_job
from reefvision.jobs.video_tracking import process_video_tracking_job
from reefvision.main import create_app
from reefvision.ml.video_tracking import TrackedDetection, TrackedFrame
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.videos import write_video_data_export
from reefvision.tests.test_video_tracking_phase6 import _seed_video


def _manual_track(
    client: TestClient,
    video_id: str,
    label_class_id: str,
    track_number: int,
    frames: list[tuple[int, float, float]],
    *,
    ground_truth: bool = False,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "video_id": video_id,
            "operation_id": f"create-{video_id}-{track_number}",
            "label_class_id": label_class_id,
            "track_number": track_number,
            "name": f"Fish {track_number}",
            "keyframes": [
                {
                    "frame_index": frame,
                    "x_min": x,
                    "y_min": y,
                    "x_max": x + 10,
                    "y_max": y + 6,
                }
                for frame, x, y in frames
            ],
            "status": "verified",
            "is_ground_truth": ground_truth,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _register_detector(
    client: TestClient,
    project: dict[str, object],
    class_mapping: dict[str, str],
) -> tuple[str, Path]:
    app = cast(FastAPI, client.app)
    settings: Settings = app.state.settings
    with app.state.session_factory() as session:
        managed_path = f"projects/{project['id']}/models/fish.pt"
        model_path = resolve_managed_project_path(settings, managed_path)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_bytes(b"local-test-checkpoint")
        model = ModelRegistration(
            project_id=str(project["id"]),
            purpose="detector",
            display_name="Fish detector",
            source_filename="fish.pt",
            managed_path=managed_path,
            sha256="c" * 64,
            file_size_bytes=model_path.stat().st_size,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={"mapping": class_mapping},
            metadata_json={},
        )
        session.add(model)
        session.commit()
        return model.id, model_path


def _materialize_video(client: TestClient, video_id: str) -> Path:
    app = cast(FastAPI, client.app)
    settings: Settings = app.state.settings
    with app.state.session_factory() as session:
        from reefvision.db.models import VideoAsset

        video = session.get(VideoAsset, video_id)
        assert video is not None
        path = resolve_managed_project_path(settings, video.managed_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"managed-test-video")
        return path


def test_observation_edits_are_revision_safe_idempotent_and_preserve_automation(
    client: TestClient,
) -> None:
    _project, video_id, label_class_id = _seed_video(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        track = VideoTrack(
            video_id=video_id,
            label_class_id=label_class_id,
            track_number=1,
            keyframes_json=[
                {
                    "frame_index": 0,
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 15,
                    "y_max": 11,
                    "confidence": 0.8,
                    "source": "bytetrack",
                },
                {
                    "frame_index": 2,
                    "x_min": 7,
                    "y_min": 5,
                    "x_max": 17,
                    "y_max": 11,
                    "confidence": 0.9,
                    "source": "bytetrack",
                },
            ],
            interpolation="linear",
            status="generated",
            source_type="generated",
            metadata_json={"tracker": "bytetrack", "model_id": "model-1"},
            created_by="video_tracking_worker",
            updated_by="video_tracking_worker",
        )
        session.add(track)
        session.commit()
        track_id = track.id

    listed = client.get(f"/api/v1/videos/{video_id}/tracks")
    assert listed.status_code == 200, listed.text
    track = listed.json()[0]
    observation_id = track["keyframes"][0]["id"]
    assert observation_id
    assert track["revision"] == 1

    payload = {
        "operation_id": "move-generated-observation",
        "expected_revision": 1,
        "x_min": 6,
        "x_max": 16,
    }
    moved = client.patch(
        f"/api/v1/video-tracks/{track_id}/observations/{observation_id}",
        json=payload,
    )
    assert moved.status_code == 200, moved.text
    moved_track = moved.json()["tracks"][0]
    moved_observation = next(
        item for item in moved_track["keyframes"] if item["id"] == observation_id
    )
    assert moved_track["revision"] == 2
    assert moved_observation["manual_edit"] is True
    assert moved_observation["source"] == "human"
    assert moved_observation["automated_provenance"]["observation"]["x_min"] == 5
    assert moved_track["metadata_json"]["model_id"] == "model-1"

    replay = client.patch(
        f"/api/v1/video-tracks/{track_id}/observations/{observation_id}",
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["tracks"][0]["revision"] == 2

    stale = client.patch(
        f"/api/v1/video-tracks/{track_id}/observations/{observation_id}",
        json={**payload, "operation_id": "stale-write", "x_min": 7},
    )
    assert stale.status_code == 409, stale.text
    assert "current revision is 2" in stale.json()["detail"]

    deleted = client.post(
        f"/api/v1/video-tracks/{track_id}/observations/{observation_id}/delete",
        json={"operation_id": "delete-observation", "expected_revision": 2},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["tracks"][0]["revision"] == 3
    restored = client.post(
        f"/api/v1/video-tracks/{track_id}/observations/{observation_id}/restore",
        json={"operation_id": "restore-observation", "expected_revision": 3},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["tracks"][0]["revision"] == 4

    events = client.get(f"/api/v1/video-tracks/{track_id}/events")
    assert events.status_code == 200, events.text
    assert [item["event_type"] for item in events.json()] == [
        "observation_updated",
        "observation_deleted",
        "observation_restored",
    ]


def test_track_split_merge_identity_and_cross_video_guards(client: TestClient) -> None:
    _project, video_id, label_class_id = _seed_video(client)
    original = _manual_track(
        client,
        video_id,
        label_class_id,
        1,
        [(0, 0, 0), (1, 1, 0), (2, 2, 0), (3, 3, 0)],
    )
    split = client.post(
        f"/api/v1/video-tracks/{original['id']}/split",
        json={
            "split_frame": 2,
            "new_track_key": "Fish 1 continuation",
            "expected_revision": 1,
            "operation_id": "split-fish-1",
        },
    )
    assert split.status_code == 200, split.text
    split_tracks = split.json()["tracks"]
    assert (
        sum(
            len([item for item in track["keyframes"] if item["deleted_at"] is None])
            for track in split_tracks
        )
        == 4
    )
    assert {
        item["frame_index"]
        for track in split_tracks
        for item in track["keyframes"]
        if item["deleted_at"] is None
    } == {0, 1, 2, 3}
    split_history = client.get(f"/api/v1/video-tracks/{split_tracks[1]['id']}/events")
    assert split_history.status_code == 200, split_history.text
    assert split_history.json()[-1]["event_type"] == "track_split"

    merged = client.post(
        "/api/v1/video-tracks/merge",
        json={
            "primary_track_id": split_tracks[0]["id"],
            "secondary_track_id": split_tracks[1]["id"],
            "expected_primary_revision": split_tracks[0]["revision"],
            "expected_secondary_revision": split_tracks[1]["revision"],
            "operation_id": "merge-fish-1",
        },
    )
    assert merged.status_code == 200, merged.text
    assert len(merged.json()["deleted_track_ids"]) == 1
    active_primary = merged.json()["tracks"][0]
    assert len([item for item in active_primary["keyframes"] if item["deleted_at"] is None]) == 4
    merged_history = client.get(f"/api/v1/video-tracks/{split_tracks[1]['id']}/events")
    assert merged_history.status_code == 200, merged_history.text
    assert merged_history.json()[-1]["event_type"] == "tracks_merged"

    other = _manual_track(
        client,
        video_id,
        label_class_id,
        3,
        [(0, 20, 20), (1, 21, 20), (2, 22, 20), (3, 23, 20)],
    )
    identity = client.post(
        "/api/v1/video-tracks/identity-switch",
        json={
            "first_track_id": active_primary["id"],
            "second_track_id": other["id"],
            "after_frame": 1,
            "expected_first_revision": active_primary["revision"],
            "expected_second_revision": other["revision"],
            "operation_id": "correct-switch",
        },
    )
    assert identity.status_code == 200, identity.text
    assert all(
        len([item for item in track["keyframes"] if item["deleted_at"] is None]) == 4
        for track in identity.json()["tracks"]
    )
    identity_history = client.get(f"/api/v1/video-tracks/{other['id']}/events")
    assert identity_history.status_code == 200, identity_history.text
    assert identity_history.json()[-1]["event_type"] == "identity_switch_corrected"

    _other_project, other_video_id, _other_class = _seed_video(client)
    other_video_track = _manual_track(
        client,
        other_video_id,
        _other_class,
        1,
        [(0, 1, 1)],
    )
    cross_video = client.post(
        "/api/v1/video-tracks/merge",
        json={
            "primary_track_id": identity.json()["tracks"][0]["id"],
            "secondary_track_id": other_video_track["id"],
            "expected_primary_revision": identity.json()["tracks"][0]["revision"],
            "expected_secondary_revision": other_video_track["revision"],
            "operation_id": "invalid-cross-video",
        },
    )
    assert cross_video.status_code == 400, cross_video.text


def test_track_add_reassign_relabel_delete_and_geometry_guards(
    client: TestClient,
) -> None:
    project, video_id, first_class_id = _seed_video(client)
    label_classes = cast(list[dict[str, object]], project["label_classes"])
    second_class_id = str(label_classes[1]["id"])
    source = _manual_track(
        client,
        video_id,
        first_class_id,
        1,
        [(0, 1, 1), (1, 2, 1)],
    )
    target = _manual_track(
        client,
        video_id,
        first_class_id,
        2,
        [(5, 20, 20), (6, 21, 20)],
    )
    add_payload: dict[str, Any] = {
        "operation_id": "add-source-observation",
        "expected_revision": 1,
        "observation": {
            "frame_index": 2,
            "x_min": 3,
            "y_min": 1,
            "x_max": 13,
            "y_max": 7,
            "confidence": 0.75,
        },
    }
    added = client.post(
        f"/api/v1/video-tracks/{source['id']}/observations",
        json=add_payload,
    )
    assert added.status_code == 200, added.text
    added_track = added.json()["tracks"][0]
    added_observation = next(item for item in added_track["keyframes"] if item["frame_index"] == 2)
    assert added_observation["manual_edit"] is True
    assert added_observation["source"] == "human"
    replay = client.post(
        f"/api/v1/video-tracks/{source['id']}/observations",
        json=add_payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["tracks"][0]["revision"] == 2

    duplicate = client.post(
        f"/api/v1/video-tracks/{source['id']}/observations",
        json={
            **add_payload,
            "operation_id": "duplicate-frame",
            "expected_revision": 2,
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    invalid_frame = client.post(
        f"/api/v1/video-tracks/{source['id']}/observations",
        json={
            **add_payload,
            "operation_id": "invalid-frame",
            "expected_revision": 2,
            "observation": {**add_payload["observation"], "frame_index": 21},
        },
    )
    assert invalid_frame.status_code == 400, invalid_frame.text
    outside_bounds = client.post(
        f"/api/v1/video-tracks/{source['id']}/observations",
        json={
            **add_payload,
            "operation_id": "outside-bounds",
            "expected_revision": 2,
            "observation": {**add_payload["observation"], "frame_index": 3, "x_max": 101},
        },
    )
    assert outside_bounds.status_code == 400, outside_bounds.text
    zero_area = client.post(
        f"/api/v1/video-tracks/{source['id']}/observations",
        json={
            **add_payload,
            "operation_id": "zero-area",
            "expected_revision": 2,
            "observation": {
                **add_payload["observation"],
                "frame_index": 3,
                "x_max": 3,
            },
        },
    )
    assert zero_area.status_code == 422, zero_area.text

    relabeled = client.patch(
        f"/api/v1/video-tracks/{source['id']}",
        json={
            "operation_id": "relabel-source",
            "expected_revision": 2,
            "label_class_id": second_class_id,
            "name": "Relabeled fish",
        },
    )
    assert relabeled.status_code == 200, relabeled.text
    assert relabeled.json()["label_class_id"] == second_class_id
    assert relabeled.json()["name"] == "Relabeled fish"

    reassigned = client.post(
        "/api/v1/video-tracks/reassign-observations",
        json={
            "source_track_id": source["id"],
            "target_track_id": target["id"],
            "observation_ids": [added_observation["id"]],
            "expected_source_revision": 3,
            "expected_target_revision": 1,
            "operation_id": "reassign-added-observation",
        },
    )
    assert reassigned.status_code == 200, reassigned.text
    source_after, target_after = reassigned.json()["tracks"]
    assert not any(item["id"] == added_observation["id"] for item in source_after["keyframes"])
    assert any(item["id"] == added_observation["id"] for item in target_after["keyframes"])

    archived = client.post(
        f"/api/v1/video-tracks/{source['id']}/delete",
        json={
            "operation_id": "archive-source",
            "expected_revision": source_after["revision"],
        },
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["tracks"][0]["deleted_at"] is not None
    assert all(
        item["id"] != source["id"]
        for item in client.get(f"/api/v1/videos/{video_id}/tracks").json()
    )
    restored = client.post(
        f"/api/v1/video-tracks/{source['id']}/restore",
        json={
            "operation_id": "restore-source",
            "expected_revision": archived.json()["tracks"][0]["revision"],
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["tracks"][0]["deleted_at"] is None


class FakeTrackingAdapter:
    provider_name = "ultralytics"
    provider_version = "test"

    def __init__(self, frames: list[TrackedFrame]) -> None:
        self.frames = frames
        self.unloaded = False

    def track(self, **_kwargs: Any) -> tuple[Any, str]:
        return iter(self.frames), "cpu"

    def unload(self) -> None:
        self.unloaded = True


def _tracked_detection(
    tracker_id: int,
    label: str,
    class_index: int,
    x: float,
) -> TrackedDetection:
    return TrackedDetection(
        tracker_id=tracker_id,
        class_index=class_index,
        label=label,
        confidence=0.9,
        x_min=x,
        y_min=10,
        x_max=x + 10,
        y_max=16,
    )


def test_tracking_requests_reject_missing_and_incompatible_detectors(
    client: TestClient,
) -> None:
    project, video_id, label_class_id = _seed_video(client)
    missing = client.post(
        f"/api/v1/videos/{video_id}/tracking-jobs",
        json={"model_id": "missing-detector", "tracker": "bytetrack"},
    )
    assert missing.status_code == 400, missing.text

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        incompatible = ModelRegistration(
            project_id=str(project["id"]),
            purpose="classifier",
            display_name="Fish classifier",
            source_filename="classifier.pt",
            managed_path=f"projects/{project['id']}/models/classifier.pt",
            sha256="d" * 64,
            file_size_bytes=1,
            framework="ultralytics",
            task="classify",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={"mapping": {"fish": label_class_id}},
            metadata_json={},
        )
        session.add(incompatible)
        session.commit()
        incompatible_id = incompatible.id
    rejected = client.post(
        f"/api/v1/videos/{video_id}/tracking-jobs",
        json={"model_id": incompatible_id, "tracker": "botsort"},
    )
    assert rejected.status_code == 400, rejected.text
    assert "detector" in rejected.json()["detail"].lower()


def test_botsort_auto_device_and_empty_detections_complete_cleanly(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    project, video_id, label_class_id = _seed_video(client)
    _materialize_video(client, video_id)
    model_id, _model_path = _register_detector(client, project, {"fish": label_class_id})

    class InspectingAdapter(FakeTrackingAdapter):
        configuration = ""
        requested_device = ""

        def track(self, **kwargs: Any) -> tuple[Any, str]:
            self.configuration = Path(kwargs["tracker_config_path"]).read_text(encoding="utf-8")
            self.requested_device = str(kwargs["requested_device"])
            return iter(
                [
                    TrackedFrame(frame_index=0, detections=()),
                    TrackedFrame(frame_index=1, detections=()),
                ]
            ), "cpu"

    adapter = InspectingAdapter([])
    monkeypatch.setattr(
        "reefvision.jobs.video_tracking.build_video_tracking_adapter",
        lambda *_args: adapter,
    )
    request = {
        "model_id": model_id,
        "tracker": "botsort",
        "device": "auto",
        "confidence_threshold": 0.2,
        "iou_threshold": 0.4,
        "tracker_options": {"gmc_method": "orb", "track_buffer": 12},
    }
    queued = client.post(f"/api/v1/videos/{video_id}/tracking-jobs", json=request)
    assert queued.status_code == 201, queued.text
    app = cast(FastAPI, client.app)
    assert process_video_tracking_job(
        app.state.settings,
        app.state.session_factory,
        queued.json()["id"],
    )
    completed = client.get(f"/api/v1/jobs/{queued.json()['id']}").json()
    assert completed["status"] == "succeeded"
    assert completed["result_json"]["track_count"] == 0
    assert completed["result_json"]["resolved_device"] == "cpu"
    assert adapter.requested_device == "auto"
    assert "tracker_type: botsort" in adapter.configuration
    assert "gmc_method: orb" in adapter.configuration
    assert client.get(f"/api/v1/videos/{video_id}/tracks").json() == []
    retried = client.post(f"/api/v1/videos/{video_id}/tracking-jobs", json=request)
    assert retried.json()["id"] == queued.json()["id"]


def test_tracking_jobs_are_transactional_idempotent_and_preserve_provenance(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    project, video_id, first_class_id = _seed_video(client)
    label_classes = cast(list[dict[str, object]], project["label_classes"])
    second_class_id = str(label_classes[1]["id"])
    _materialize_video(client, video_id)
    model_id, _model_path = _register_detector(
        client,
        project,
        {"fish": first_class_id, "shark": second_class_id},
    )
    adapter = FakeTrackingAdapter(
        [
            TrackedFrame(
                frame_index=0,
                detections=(
                    _tracked_detection(1, "fish", 0, 1),
                    _tracked_detection(2, "shark", 1, 30),
                ),
            ),
            TrackedFrame(frame_index=1, detections=()),
            TrackedFrame(
                frame_index=2,
                detections=(
                    _tracked_detection(1, "fish", 0, 3),
                    _tracked_detection(2, "shark", 1, 32),
                ),
            ),
        ]
    )
    monkeypatch.setattr(
        "reefvision.jobs.video_tracking.build_video_tracking_adapter",
        lambda *_args: adapter,
    )
    request = {
        "request_id": "byte-run-1",
        "model_id": model_id,
        "tracker": "bytetrack",
        "device": "cpu",
        "confidence_threshold": 0.3,
        "iou_threshold": 0.5,
        "tracker_options": {"track_buffer": 15, "match_thresh": 0.7},
    }
    queued = client.post(f"/api/v1/videos/{video_id}/tracking-jobs", json=request)
    assert queued.status_code == 201, queued.text
    repeated_queue = client.post(f"/api/v1/videos/{video_id}/tracking-jobs", json=request)
    assert repeated_queue.status_code == 201, repeated_queue.text
    assert repeated_queue.json()["id"] == queued.json()["id"]

    app = cast(FastAPI, client.app)
    assert process_video_tracking_job(
        app.state.settings,
        app.state.session_factory,
        queued.json()["id"],
    )
    completed = client.get(f"/api/v1/jobs/{queued.json()['id']}")
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "succeeded"
    assert completed.json()["result_json"]["track_count"] == 2
    assert completed.json()["result_json"]["resolved_device"] == "cpu"
    tracks = client.get(f"/api/v1/videos/{video_id}/tracks").json()
    assert len(tracks) == 2
    assert {track["label_class_id"] for track in tracks} == {
        first_class_id,
        second_class_id,
    }
    assert all(track["origin_job_id"] == queued.json()["id"] for track in tracks)
    assert all(track["source_type"] == "generated" for track in tracks)
    assert all(track["metadata_json"]["model_sha256"] == "c" * 64 for track in tracks)
    assert all(track["metadata_json"]["tracker_options"]["track_buffer"] == 15 for track in tracks)
    assert adapter.unloaded is True

    repeated_completed = client.post(
        f"/api/v1/videos/{video_id}/tracking-jobs",
        json=request,
    )
    assert repeated_completed.json()["id"] == queued.json()["id"]
    assert len(client.get(f"/api/v1/videos/{video_id}/tracks").json()) == 2


def test_tracking_failure_and_cancellation_leave_no_partial_tracks_or_temp_files(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    project, video_id, label_class_id = _seed_video(client)
    _materialize_video(client, video_id)
    model_id, _model_path = _register_detector(client, project, {"fish": label_class_id})
    app = cast(FastAPI, client.app)

    class FailingAdapter(FakeTrackingAdapter):
        def track(self, **_kwargs: Any) -> tuple[Any, str]:
            def frames() -> Any:
                yield TrackedFrame(
                    frame_index=0,
                    detections=(_tracked_detection(1, "fish", 0, 1),),
                )
                raise RuntimeError("synthetic tracker failure")

            return frames(), "cpu"

    monkeypatch.setattr(
        "reefvision.jobs.video_tracking.build_video_tracking_adapter",
        lambda *_args: FailingAdapter([]),
    )
    failed_job = client.post(
        f"/api/v1/videos/{video_id}/tracking-jobs",
        json={"request_id": "failure-run", "model_id": model_id, "device": "cpu"},
    ).json()
    assert not process_video_tracking_job(
        app.state.settings,
        app.state.session_factory,
        failed_job["id"],
    )
    failed = client.get(f"/api/v1/jobs/{failed_job['id']}").json()
    assert failed["status"] == "failed"
    assert "synthetic tracker failure" in failed["error_message"]
    with app.state.session_factory() as session:
        assert not list(
            session.scalars(select(VideoTrack).where(VideoTrack.origin_job_id == failed_job["id"]))
        )
    temp_root = resolve_managed_project_path(
        app.state.settings,
        f"projects/{project['id']}/tmp/video-tracking/{failed_job['id']}",
    )
    assert not temp_root.exists()

    cancellation_job = client.post(
        f"/api/v1/videos/{video_id}/tracking-jobs",
        json={"request_id": "cancel-run", "model_id": model_id, "device": "cpu"},
    ).json()

    class CancellingAdapter(FakeTrackingAdapter):
        def track(self, **_kwargs: Any) -> tuple[Any, str]:
            def frames() -> Any:
                yield TrackedFrame(
                    frame_index=0,
                    detections=(_tracked_detection(1, "fish", 0, 1),),
                )
                with app.state.session_factory() as session:
                    job = session.get(Job, cancellation_job["id"])
                    assert job is not None
                    job.status = "cancel_requested"
                    session.commit()
                yield TrackedFrame(
                    frame_index=1,
                    detections=(_tracked_detection(1, "fish", 0, 2),),
                )

            return frames(), "cpu"

    monkeypatch.setattr(
        "reefvision.jobs.video_tracking.build_video_tracking_adapter",
        lambda *_args: CancellingAdapter([]),
    )
    assert process_video_tracking_job(
        app.state.settings,
        app.state.session_factory,
        cancellation_job["id"],
    )
    cancelled = client.get(f"/api/v1/jobs/{cancellation_job['id']}").json()
    assert cancelled["status"] == "cancelled"
    with app.state.session_factory() as session:
        assert not list(
            session.scalars(
                select(VideoTrack).where(VideoTrack.origin_job_id == cancellation_job["id"])
            )
        )


def test_saved_zones_irregular_timing_and_unit_safeguards(client: TestClient) -> None:
    _project, video_id, label_class_id = _seed_video(client)
    track = _manual_track(
        client,
        video_id,
        label_class_id,
        1,
        [(0, 0, 0), (2, 4, 0), (4, 8, 0)],
    )
    updated = client.patch(
        f"/api/v1/video-tracks/{track['id']}",
        json={
            "operation_id": "set-irregular-times",
            "expected_revision": track["revision"],
            "keyframes": [
                {**track["keyframes"][0], "timestamp_seconds": 0.0},
                {**track["keyframes"][1], "timestamp_seconds": 0.4},
                {**track["keyframes"][2], "timestamp_seconds": 0.8},
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    zone = client.post(
        f"/api/v1/videos/{video_id}/zones",
        json={"name": "start", "x_min": 0, "y_min": 0, "x_max": 10, "y_max": 20},
    )
    assert zone.status_code == 201, zone.text

    analysis = client.post(
        f"/api/v1/videos/{video_id}/analytics",
        json={"sampling": "observations", "activity_speed_threshold_pixels_per_second": 1},
    )
    assert analysis.status_code == 200, analysis.text
    payload = analysis.json()
    metric = payload["tracks"][0]
    assert metric["persisted_observation_count"] == 3
    assert metric["distance_pixels"] == pytest.approx(8)
    assert metric["mean_speed_pixels_per_second"] == pytest.approx(10)
    assert metric["inactive_time_seconds"] == pytest.approx(0)
    assert metric["distance_physical"] is None
    assert metric["physical_unit"] is None
    assert payload["coordinate_unit"] == "pixels"
    assert payload["timing_source"] == "observation_timestamps"
    school_by_frame = {item["frame_index"]: item for item in payload["school_by_frame"]}
    assert school_by_frame[2]["timestamp_seconds"] == pytest.approx(0.4)
    assert any("pixel-based" in warning for warning in payload["warnings"])
    assert any("missing frames" in warning for warning in payload["warnings"])
    assert metric["zone_time_seconds"]["start"] == pytest.approx(0.8)
    assert payload["zone_events"][0]["event_type"] == "entry"
    assert payload["analysis_id"]
    assert payload["source_track_revisions"][0]["revision"] == 2

    replay = client.post(
        f"/api/v1/videos/{video_id}/analytics",
        json={"sampling": "observations", "activity_speed_threshold_pixels_per_second": 1},
    )
    assert replay.json()["analysis_id"] == payload["analysis_id"]
    reopened = client.get(f"/api/v1/video-analyses/{payload['analysis_id']}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["analysis_sha256"] == payload["analysis_sha256"]


def test_persisted_tracking_evaluation_handles_identity_and_missing_ground_truth(
    client: TestClient,
) -> None:
    project, video_id, label_class_id = _seed_video(client)
    reference = _manual_track(
        client,
        video_id,
        label_class_id,
        1,
        [(0, 0, 10), (1, 1, 10), (2, 2, 10), (3, 3, 10)],
        ground_truth=True,
    )
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        job = Job(
            project_id=str(project["id"]),
            job_type="video_track",
            status="succeeded",
            request_json={
                "video_id": video_id,
                "tracker": "bytetrack",
                "confidence_threshold": 0.25,
                "iou_threshold": 0.5,
            },
        )
        session.add(job)
        session.commit()
        job_id = job.id
    first = _manual_track(
        client,
        video_id,
        label_class_id,
        2,
        [(0, 0, 10), (1, 1, 10)],
    )
    second = _manual_track(
        client,
        video_id,
        label_class_id,
        3,
        [(2, 2, 10), (3, 3, 10)],
    )
    with app.state.session_factory() as session:
        for track_id in (first["id"], second["id"]):
            track = session.get(VideoTrack, track_id)
            assert track is not None
            track.origin_job_id = job_id
            track.source_type = "generated"
            track.status = "generated"
            keyframes = [dict(item) for item in track.keyframes_json]
            for item in keyframes:
                item["confidence"] = 0.9
                item["source"] = "generated"
            track.keyframes_json = keyframes
            session.commit()

    evaluated = client.post(
        f"/api/v1/videos/{video_id}/tracking-evaluations",
        json={"candidate_job_ids": [job_id], "minimum_iou": 0.5},
    )
    assert evaluated.status_code == 201, evaluated.text
    payload = evaluated.json()
    assert payload["ground_truth_available"] is True
    assert payload["best_candidate_name"].startswith("bytetrack")
    summary = payload["ranked_by_hota"][0]
    assert summary["detection_precision"] == pytest.approx(1)
    assert summary["detection_recall"] == pytest.approx(1)
    assert summary["localization_iou"] == pytest.approx(1)
    assert summary["identity_switch_count"] == 1
    assert summary["fragmentation_count"] == 0
    assert summary["false_positive_track_count"] == 0
    assert summary["false_negative_track_count"] == 0
    assert len(summary["per_frame"]) == 4
    assert summary["per_track"][0]["reference_track_id"] == reference["id"]

    reopened = client.get(f"/api/v1/tracking-evaluations/{payload['evaluation_id']}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["evaluation_sha256"] == payload["evaluation_sha256"]

    botsort = _manual_track(
        client,
        video_id,
        label_class_id,
        4,
        [(0, 0, 10), (1, 1, 10), (2, 2, 10), (3, 3, 10)],
    )
    with app.state.session_factory() as session:
        botsort_job = Job(
            project_id=str(project["id"]),
            job_type="video_track",
            status="succeeded",
            request_json={
                "video_id": video_id,
                "tracker": "botsort",
                "confidence_threshold": 0.25,
                "iou_threshold": 0.5,
            },
        )
        session.add(botsort_job)
        session.flush()
        botsort_track = session.get(VideoTrack, botsort["id"])
        assert botsort_track is not None
        botsort_track.origin_job_id = botsort_job.id
        botsort_track.source_type = "generated"
        botsort_track.status = "generated"
        keyframes = [dict(item) for item in botsort_track.keyframes_json]
        for item in keyframes:
            item["confidence"] = 0.9
            item["source"] = "generated"
        botsort_track.keyframes_json = keyframes
        session.commit()
        botsort_job_id = botsort_job.id
    comparison = client.post(
        f"/api/v1/videos/{video_id}/tracking-evaluations",
        json={
            "candidate_job_ids": [job_id, botsort_job_id],
            "confidence_thresholds": [0.5, 0.95],
            "minimum_iou": 0.5,
        },
    )
    assert comparison.status_code == 201, comparison.text
    names = [item["candidate_name"] for item in comparison.json()["ranked_by_hota"]]
    assert len(names) == 4
    assert any(name.startswith("bytetrack") and "0.500" in name for name in names)
    assert any(name.startswith("botsort") and "0.950" in name for name in names)

    cleared = client.patch(
        f"/api/v1/video-tracks/{reference['id']}",
        json={
            "operation_id": "clear-ground-truth",
            "expected_revision": reference["revision"],
            "is_ground_truth": False,
        },
    )
    assert cleared.status_code == 200, cleared.text
    no_ground_truth = client.post(
        f"/api/v1/videos/{video_id}/tracking-evaluations",
        json={"candidate_job_ids": [job_id], "minimum_iou": 0.75},
    )
    assert no_ground_truth.status_code == 201, no_ground_truth.text
    assert no_ground_truth.json()["ground_truth_available"] is False
    assert no_ground_truth.json()["ranked_by_hota"] == []
    assert any("No explicitly verified" in item for item in no_ground_truth.json()["warnings"])


def test_data_export_bundle_is_checksummed_restart_safe_and_atomic(
    client: TestClient,
    test_settings: Settings,
) -> None:
    _project, video_id, label_class_id = _seed_video(client)
    _manual_track(client, video_id, label_class_id, 1, [(0, 1, 1), (2, 3, 1)])
    analysis = client.post(
        f"/api/v1/videos/{video_id}/analytics",
        json={"sampling": "observations"},
    )
    assert analysis.status_code == 200, analysis.text
    exported = client.post(
        f"/api/v1/videos/{video_id}/data-exports",
        json={"formats": ["csv", "json", "mot", "npz"]},
    )
    assert exported.status_code == 201, exported.text
    payload = exported.json()
    artifact = client.get(f"/api/v1/artifacts/{payload['artifact_id']}/content?download=true")
    assert artifact.status_code == 200, artifact.text
    assert artifact.content
    with zipfile.ZipFile(io.BytesIO(artifact.content)) as bundle:
        names = set(bundle.namelist())
        assert {
            "manifest.json",
            "tracks.csv",
            "tracks.json",
            "tracks-mot.txt",
            "tracks.npz",
        } <= names
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["video_id"] == video_id
        assert manifest["track_revisions"][0]["revision"] == 1
        assert manifest["analysis_runs"][0]["analysis_id"] == analysis.json()["analysis_id"]
        assert all(len(item["sha256"]) == 64 for item in manifest["files"])
        csv_content = bundle.read("tracks.csv").decode("utf-8")
        assert "manual_edit" in csv_content
        assert "detector_model_checksum" in csv_content
        structured = json.loads(bundle.read("tracks.json"))
        assert structured["format"] == "reefvision_video_tracks_v2"
        assert structured["analysis_runs"]

    reopened = client.get(f"/api/v1/artifacts/{payload['artifact_id']}/content")
    assert reopened.status_code == 200
    assert reopened.content == artifact.content

    relative_root = "projects/test/video-exports/atomic-conflict"
    first = write_video_data_export(
        test_settings,
        relative_root=relative_root,
        files={"tracks.csv": b"first"},
        manifest={"video_id": "video"},
    )
    archive_path = resolve_managed_project_path(test_settings, first.archive_path)
    original_bytes = archive_path.read_bytes()
    with pytest.raises(Exception, match="already exists"):
        write_video_data_export(
            test_settings,
            relative_root=relative_root,
            files={"tracks.csv": b"second"},
            manifest={"video_id": "video"},
        )
    assert archive_path.read_bytes() == original_bytes


def test_rendered_video_export_is_atomic_provenance_rich_and_failure_clean(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    project, video_id, label_class_id = _seed_video(client)
    _materialize_video(client, video_id)
    track = _manual_track(
        client,
        video_id,
        label_class_id,
        1,
        [(0, 1, 1), (2, 3, 1)],
    )
    app = cast(FastAPI, client.app)

    class RenderCapture:
        def __init__(self, _path: str) -> None:
            self.index = 0

        def isOpened(self) -> bool:
            return True

        def get(self, property_id: int) -> float:
            return {1: 10.0, 2: 100.0, 3: 100.0}[property_id]

        def read(self) -> tuple[bool, Any]:
            if self.index >= 3:
                return False, None
            self.index += 1
            return True, np.zeros((100, 100, 3), dtype=np.uint8)

        def release(self) -> None:
            return None

    class RenderWriter:
        def __init__(self, destination: str, *_args: Any) -> None:
            self.destination = Path(destination)
            self.frames = 0

        def isOpened(self) -> bool:
            return True

        def write(self, _frame: Any) -> None:
            self.frames += 1

        def release(self) -> None:
            self.destination.write_bytes(f"rendered-{self.frames}".encode())

    fake_cv2 = SimpleNamespace(
        VideoCapture=RenderCapture,
        VideoWriter=RenderWriter,
        VideoWriter_fourcc=lambda *_codec: 1,
        CAP_PROP_FPS=1,
        CAP_PROP_FRAME_WIDTH=2,
        CAP_PROP_FRAME_HEIGHT=3,
        FONT_HERSHEY_SIMPLEX=4,
        LINE_AA=5,
        rectangle=lambda frame, *_args: frame,
        putText=lambda frame, *_args: frame,
    )
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    queued = client.post(
        f"/api/v1/videos/{video_id}/render-exports",
        json={"export_kind": "annotated", "maximum_frames": 3},
    )
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["job"]["id"]
    assert process_video_render_export_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )
    completed = client.get(f"/api/v1/jobs/{job_id}").json()
    assert completed["status"] == "succeeded"
    assert completed["result_json"]["rendered_frames"] == 3
    manifest_path = resolve_managed_project_path(
        app.state.settings,
        completed["result_json"]["manifest_path"],
    )
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["video_id"] == video_id
    assert manifest["track_revisions"] == {track["id"]: track["revision"]}
    assert manifest["rendered_video_sha256"] == completed["result_json"]["video_sha256"]
    artifact = client.get(f"/api/v1/artifacts/{completed['result_json']['artifact_id']}/content")
    assert artifact.status_code == 200, artifact.text
    assert artifact.content == b"rendered-3"

    invalid_queue = client.post(
        f"/api/v1/videos/{video_id}/render-exports",
        json={"export_kind": "annotated", "maximum_frames": 3},
    )
    assert invalid_queue.status_code == 202, invalid_queue.text
    invalid_job_id = invalid_queue.json()["job"]["id"]
    with app.state.session_factory() as session:
        invalid_job = session.get(Job, invalid_job_id)
        assert invalid_job is not None
        invalid_request = dict(invalid_job.request_json)
        invalid_request["resolved_track_ids"] = ["00000000-0000-0000-0000-000000000000"]
        invalid_job.request_json = invalid_request
        session.commit()
    assert not process_video_render_export_job(
        app.state.settings,
        app.state.session_factory,
        invalid_job_id,
    )
    invalid_job = client.get(f"/api/v1/jobs/{invalid_job_id}").json()
    assert invalid_job["status"] == "failed"
    assert "changed" in invalid_job["error_message"]

    class ClosedWriter(RenderWriter):
        def isOpened(self) -> bool:
            return False

    fake_cv2.VideoWriter = ClosedWriter
    failed_queue = client.post(
        f"/api/v1/videos/{video_id}/render-exports",
        json={"export_kind": "annotated", "maximum_frames": 3},
    )
    assert failed_queue.status_code == 202, failed_queue.text
    failed_job_id = failed_queue.json()["job"]["id"]
    assert not process_video_render_export_job(
        app.state.settings,
        app.state.session_factory,
        failed_job_id,
    )
    failed = client.get(f"/api/v1/jobs/{failed_job_id}").json()
    assert failed["status"] == "failed"
    output_root = resolve_managed_project_path(
        app.state.settings,
        f"projects/{project['id']}/video-exports/{failed_job_id}",
    )
    assert not output_root.exists()
    assert not list(output_root.parent.glob(f".{failed_job_id}.*.tmp"))


def test_corrected_track_review_and_artifacts_survive_application_restart(
    test_settings: Settings,
) -> None:
    first_app = create_app(test_settings)
    Base.metadata.create_all(first_app.state.engine)
    with TestClient(first_app) as first_client:
        _project, video_id, label_class_id = _seed_video(first_client)
        track = _manual_track(
            first_client,
            video_id,
            label_class_id,
            1,
            [(0, 1, 1), (2, 3, 1)],
        )
        observation_id = track["keyframes"][0]["id"]
        corrected = first_client.patch(
            f"/api/v1/video-tracks/{track['id']}/observations/{observation_id}",
            json={
                "operation_id": "restart-safe-correction",
                "expected_revision": track["revision"],
                "x_min": 2,
                "x_max": 12,
            },
        )
        assert corrected.status_code == 200, corrected.text
        analysis = first_client.post(
            f"/api/v1/videos/{video_id}/analytics",
            json={"sampling": "observations"},
        )
        assert analysis.status_code == 200, analysis.text
        analysis_id = analysis.json()["analysis_id"]
        exported = first_client.post(
            f"/api/v1/videos/{video_id}/data-exports",
            json={"formats": ["json"]},
        )
        assert exported.status_code == 201, exported.text
        artifact_id = exported.json()["artifact_id"]

    second_app = create_app(test_settings)
    try:
        with TestClient(second_app) as second_client:
            tracks = second_client.get(f"/api/v1/videos/{video_id}/tracks")
            assert tracks.status_code == 200, tracks.text
            reopened = tracks.json()[0]
            assert reopened["revision"] == 2
            observation = next(
                item for item in reopened["keyframes"] if item["id"] == observation_id
            )
            assert observation["manual_edit"] is True
            assert observation["x_min"] == 2
            events = second_client.get(f"/api/v1/video-tracks/{track['id']}/events")
            assert [item["event_type"] for item in events.json()] == [
                "track_created",
                "observation_updated",
            ]
            reopened_analysis = second_client.get(f"/api/v1/video-analyses/{analysis_id}")
            assert reopened_analysis.status_code == 200, reopened_analysis.text
            artifact = second_client.get(f"/api/v1/artifacts/{artifact_id}/content")
            assert artifact.status_code == 200, artifact.text
            with zipfile.ZipFile(io.BytesIO(artifact.content)) as bundle:
                assert "tracks.json" in bundle.namelist()
    finally:
        Base.metadata.drop_all(second_app.state.engine)
        second_app.state.engine.dispose()


def test_frame_endpoint_returns_exact_index_and_rejects_invalid_frames(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    _project, video_id, _label_class_id = _seed_video(client)
    _materialize_video(client, video_id)

    class FrameCapture:
        frame_index = -1

        def __init__(self, _path: str) -> None:
            self.opened = True

        def isOpened(self) -> bool:
            return self.opened

        def set(self, _property_id: int, frame_index: int) -> bool:
            self.frame_index = frame_index
            return True

        def read(self) -> tuple[bool, bytes]:
            return True, f"frame-{self.frame_index}".encode()

        def release(self) -> None:
            self.opened = False

    fake_cv2 = SimpleNamespace(
        VideoCapture=FrameCapture,
        CAP_PROP_POS_FRAMES=1,
        IMWRITE_JPEG_QUALITY=2,
        imencode=lambda _suffix, frame, _options: (True, b"jpeg:" + frame),
    )
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    frame = client.get(f"/api/v1/videos/{video_id}/frames/7")
    assert frame.status_code == 200, frame.text
    assert frame.content == b"jpeg:frame-7"
    assert frame.headers["x-reefvision-frame-index"] == "7"
    invalid = client.get(f"/api/v1/videos/{video_id}/frames/21")
    assert invalid.status_code == 400, invalid.text


def test_frame_extraction_is_atomic_cancel_safe_and_restart_readable(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    project, video_id, _label_class_id = _seed_video(client)
    source = _materialize_video(client, video_id)
    app = cast(FastAPI, client.app)
    settings: Settings = app.state.settings
    source_relative = source.relative_to(settings.data_dir).as_posix()

    class ExtractCapture:
        def __init__(self, _path: str) -> None:
            self.index = 0

        def isOpened(self) -> bool:
            return True

        def get(self, _property_id: int) -> int:
            return 3

        def read(self) -> tuple[bool, bytes | None]:
            if self.index >= 3:
                return False, None
            frame = f"frame-{self.index}".encode()
            self.index += 1
            return True, frame

        def release(self) -> None:
            return None

    def write_frame(destination: str, frame: bytes) -> bool:
        Path(destination).write_bytes(frame)
        return True

    monkeypatch.setattr("reefvision.jobs.video.cv2.VideoCapture", ExtractCapture)
    monkeypatch.setattr("reefvision.jobs.video.cv2.imwrite", write_frame)

    def add_job(frames_path: str) -> str:
        with app.state.session_factory() as session:
            job = Job(
                project_id=str(project["id"]),
                job_type="video_extract",
                status="queued",
                request_json={
                    "video_path": source_relative,
                    "frames_path": frames_path,
                    "every_n_frames": 2,
                },
            )
            session.add(job)
            session.commit()
            return job.id

    success_path = f"projects/{project['id']}/frames/success"
    success_job_id = add_job(success_path)
    assert process_video_extract_job(settings, app.state.session_factory, success_job_id)
    success_root = resolve_managed_project_path(settings, success_path)
    assert [path.name for path in sorted(success_root.iterdir())] == [
        "frame_00000000.jpg",
        "frame_00000002.jpg",
    ]
    with app.state.session_factory() as session:
        completed = session.get(Job, success_job_id)
        assert completed is not None
        assert completed.status == "succeeded"
        assert completed.result_json == {
            "stage": "completed",
            "frames_path": success_path,
            "source_frame_count": 3,
            "written_frame_count": 2,
        }

    cancel_path = f"projects/{project['id']}/frames/cancelled"
    cancel_job_id = add_job(cancel_path)
    cancellation_checks = 0

    def cancel_after_first_frame(_factory: Any, _job_id: str) -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks > 1

    monkeypatch.setattr(
        "reefvision.jobs.video._cancellation_requested",
        cancel_after_first_frame,
    )
    assert process_video_extract_job(settings, app.state.session_factory, cancel_job_id)
    assert not resolve_managed_project_path(settings, cancel_path).exists()
    with app.state.session_factory() as session:
        cancelled = session.get(Job, cancel_job_id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"

    failed_path = f"projects/{project['id']}/frames/failed"
    failed_job_id = add_job(failed_path)
    monkeypatch.setattr(
        "reefvision.jobs.video._cancellation_requested",
        lambda _factory, _job_id: False,
    )
    monkeypatch.setattr("reefvision.jobs.video.cv2.imwrite", lambda _path, _frame: False)
    assert not process_video_extract_job(settings, app.state.session_factory, failed_job_id)
    assert not resolve_managed_project_path(settings, failed_path).exists()
    with app.state.session_factory() as session:
        failed = session.get(Job, failed_job_id)
        assert failed is not None
        assert failed.status == "failed"
        assert "Unable to write extracted frame" in str(failed.error_message)

    frames_parent = resolve_managed_project_path(
        settings,
        f"projects/{project['id']}/frames",
    )
    assert not list(frames_parent.glob(".*.tmp"))
