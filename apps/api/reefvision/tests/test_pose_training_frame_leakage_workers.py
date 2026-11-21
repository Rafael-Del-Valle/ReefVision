from __future__ import annotations

import hashlib
import io
import struct
import subprocess
import zipfile
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.models import ExperimentRecord, Job, ModelRegistration, TrainingRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.pose_training import process_pose_training_job
from reefvision.ml.reefpose.training import ReefPoseTrainer
from reefvision.services.workflow_pose_training import create_pose_workflow_training_result
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project

FRAME_COUNT = 8
WIDTH, HEIGHT = 96, 64


def _generated_mp4(tmp_path: Path) -> bytes:
    import imageio_ffmpeg

    video = tmp_path / "source.mp4"
    pixels = b"".join(
        bytes((32 + frame * 18, 80, 172 - frame * 12)) * (WIDTH * HEIGHT)
        for frame in range(FRAME_COUNT)
    )
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{WIDTH}x{HEIGHT}",
            "-framerate",
            "10",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "mpeg4",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        input=pixels,
        check=True,
        timeout=15,
    )
    return video.read_bytes()


def _checked(response: Any, status: int) -> Any:
    assert response.status_code == status, response.text
    return response.json()


def _frozen_recording(
    client: TestClient,
    *,
    project_id: str,
    label_id: str,
    schema: dict[str, Any],
    video_bytes: bytes,
    name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    original = _checked(
        client.post(
            f"/api/v1/projects/{project_id}/imports/videos",
            files={"file": (name + ".mp4", video_bytes, "video/mp4")},
        ),
        201,
    )
    assert original["frame_count"] == FRAME_COUNT
    assert original["sha256"] == hashlib.sha256(video_bytes).hexdigest()
    payload = {
        "label_class_id": label_id,
        "status": "verified",
        "keyframes": [
            {
                "frame": frame,
                "timestamp_seconds": frame / 10,
                "bbox": [20, 16, 32, 26],
                "pose_observations": [
                    {
                        "id": f"{landmark}-{frame}",
                        "landmark_id": landmark,
                        "semantic_label": label,
                        "occurrence_index": 0,
                        "x": x,
                        "y": 24,
                        "status": "visible",
                        "source": "manual",
                    }
                    for landmark, label, x in (("a", "A", 26), ("b", "B", 43))
                ],
            }
            for frame in range(FRAME_COUNT)
        ],
    }
    track = _checked(client.post(f"/api/v1/videos/{original['id']}/tracks", json=payload), 201)
    bound = _checked(
        client.put(
            f"/api/v1/video-tracks/{track['id']}",
            json={
                **payload,
                "base_revision": track["revision"],
                "pose_schema_binding": {
                    "schema_id": schema["id"],
                    "schema_revision": schema["revision"],
                    "content_hash": schema["content_hash"],
                },
            },
        ),
        200,
    )
    _checked(
        client.post(
            f"/api/v1/video-tracks/{bound['id']}/pose-temporal-associations",
            json={
                "max_gap_frames": 2,
                "max_normalized_displacement": 1.0,
                "confirm_after_observations": 2,
            },
        ),
        200,
    )
    round_ = _checked(
        client.post(
            f"/api/v1/projects/{project_id}/pose-active-learning-rounds",
            json={
                "name": name,
                "video_id": original["id"],
                "track_ids": [bound["id"]],
                "grouping": {"recording_id": name, "animal_id": f"animal-{name}"},
                "requested_size": FRAME_COUNT,
                "minimum_frame_spacing": 0,
            },
        ),
        201,
    )
    round_id = round_["id"]
    candidates = _checked(
        client.get(f"/api/v1/pose-active-learning-rounds/{round_id}/candidates"), 200
    )
    assert len(candidates) == FRAME_COUNT
    for candidate in candidates:
        _checked(
            client.put(
                f"/api/v1/pose-active-learning-candidates/{candidate['id']}/review",
                json={"action": "verify", "reviewed_by": "synthetic fixture reviewer"},
            ),
            200,
        )
    frozen = _checked(
        client.post(
            f"/api/v1/pose-active-learning-rounds/{round_id}/training-dataset",
            json={"name": name, "created_by": "synthetic fixture reviewer"},
        ),
        201,
    )
    assert frozen["status"] == "complete"
    return original, frozen


def _exported_frames(client: TestClient, dataset_id: str) -> set[str]:
    response = client.get(
        f"/api/v1/pose-training-datasets/{dataset_id}/export?format=ultralytics_pose"
    )
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as export:
        names = [
            name
            for name in export.namelist()
            if name.startswith("images/train/") and name.endswith(".png")
        ]
        assert len(names) == FRAME_COUNT
        return {hashlib.sha256(export.read(name)).hexdigest() for name in names}


@pytest.mark.parametrize("provider", ["ultralytics", "reefpose"])
def test_queued_pose_worker_refuses_frozen_frame_overlap_before_output(
    client: TestClient,
    test_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    from ultralytics import YOLO

    project = create_project(client, "Physically overlapping frozen pose frames")
    project_id = str(project["id"])
    label = project["label_classes"][0]["id"]
    schema = _checked(
        client.post(
            f"/api/v1/projects/{project_id}/pose-schemas",
            json={
                "name": "Two manual landmarks",
                "landmarks": [
                    {"id": "a", "name": "A"},
                    {"id": "b", "name": "B"},
                ],
            },
        ),
        201,
    )
    clip = _generated_mp4(tmp_path)
    # A legal ISO-BMFF free-space atom changes the original file's hash without
    # changing the pictures that decode into the frozen training examples.
    rec_a, rec_b = (
        _frozen_recording(
            client,
            project_id=project_id,
            label_id=label,
            schema=schema,
            video_bytes=clip + struct.pack(">I4s4s", 12, b"free", marker),
            name=name,
        )
        for name, marker in (("training-video", b"TRN1"), ("holdout-video", b"VAL2"))
    )
    train_video, training = rec_a
    holdout_video, holdout = rec_b
    assert train_video["id"] != holdout_video["id"]
    assert train_video["sha256"] != holdout_video["sha256"]
    assert training["id"] != holdout["id"]
    assert training["manifest_sha256"] != holdout["manifest_sha256"]
    duplicated = _exported_frames(client, training["id"])
    assert len(duplicated) == FRAME_COUNT
    assert duplicated == _exported_frames(client, holdout["id"])

    if provider == "ultralytics":
        architecture = "yolo11n-pose.yaml"
        config = {"epochs": 1, "batch": 1, "imgsz": 64, "workers": 0}
    else:
        architecture = "reefpose-s"
        config = {
            "epochs": 1,
            "batch": 1,
            "input_height": 64,
            "input_width": 64,
            "base_channels": 4,
            "fpn_channels": 8,
            "workers": 0,
        }

    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    with factory() as session:
        # Keep the already validated job queued, as it would have been before a restart.
        with pytest.raises(ValidationError, match="job=queued, run=queued"):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=project_id,
                dataset_payload={
                    "project_id": project_id,
                    "dataset_id": training["id"],
                    "manifest_sha256": training["manifest_sha256"],
                },
                validation_dataset_payload={
                    "project_id": project_id,
                    "dataset_id": holdout["id"],
                    "manifest_sha256": holdout["manifest_sha256"],
                },
                parameters={
                    "provider_id": provider,
                    "architecture": architecture,
                    "device": "cpu",
                    "initialization_mode": "random",
                    "training_config": config,
                },
                processor=lambda *_args: True,
            )
        run = session.scalar(select(TrainingRun).where(TrainingRun.project_id == project_id))
        assert run is not None and run.job_id is not None
        assert run.status == "queued"
        job = session.get(Job, run.job_id)
        assert job is not None and job.status == "queued"
        assert job.request_json["pose_training_dataset_id"] == training["id"]
        assert job.request_json["pose_validation_dataset_id"] == holdout["id"]
        run_id, job_id = run.id, job.id

    reached_fit = Mock(side_effect=AssertionError("Overlapping frames reached model fitting"))
    monkeypatch.setattr(YOLO, "train", reached_fit)
    monkeypatch.setattr(ReefPoseTrainer, "fit", reached_fit)

    assert not process_pose_training_job(test_settings, factory, job_id)

    with factory() as session:
        job = session.get(Job, job_id)
        run = session.get(TrainingRun, run_id)
        assert job is not None and run is not None
        assert job.status == run.status == "failed"
        assert "frozen frame" in (run.error_message or "").casefold()
        assert "frozen frame" in (job.error_message or "").casefold()
        assert run.result_checkpoint_path is None and run.registered_model_id is None
        assert (
            session.scalar(
                select(ExperimentRecord).where(ExperimentRecord.training_run_id == run_id)
            )
            is None
        )
        assert (
            session.scalar(
                select(ModelRegistration).where(ModelRegistration.project_id == project_id)
            )
            is None
        )
    reached_fit.assert_not_called()
    managed = resolve_managed_project_path(
        test_settings, f"{project['storage_root']}/training/{run_id}"
    )
    assert not managed.exists()
