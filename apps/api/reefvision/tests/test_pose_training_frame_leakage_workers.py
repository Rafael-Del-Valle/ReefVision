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
from reefvision.db.models import (
    ExperimentRecord,
    Job,
    ModelRegistration,
    PoseTrainingDataset,
    TrainingRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs import reefpose_training
from reefvision.jobs.pose_training import process_pose_training_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.ml.reefpose.training import ReefPoseTrainer
from reefvision.services.pose_training_exports import (
    PoseTrainingExportArtifact,
    PoseTrainingExportFormat,
    PoseTrainingExportService,
)
from reefvision.services.workflow_execution import WorkflowExecutionService
from reefvision.services.workflow_pose_training import create_pose_workflow_training_result
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project

FRAME_COUNT = 8
WIDTH, HEIGHT = 96, 64


def _generated_mp4(tmp_path: Path, *, variant: int = 0) -> bytes:
    import imageio_ffmpeg

    video = tmp_path / f"source-{variant}.mp4"
    pixels = b"".join(
        bytes((32 + frame * 18, 80 + variant, 172 - frame * 12)) * (WIDTH * HEIGHT)
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


def _frozen_split(
    client: TestClient, tmp_path: Path, *, overlapping: bool
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    project = create_project(client, "Two independent recordings of frozen pose frames")
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
    training_clip = _generated_mp4(tmp_path)
    validation_clip = training_clip if overlapping else _generated_mp4(tmp_path, variant=50)
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
        for name, marker, clip in (
            ("training-video", b"TRN1", training_clip),
            ("holdout-video", b"VAL2", validation_clip),
        )
    )
    train_video, training = rec_a
    holdout_video, holdout = rec_b
    assert train_video["id"] != holdout_video["id"]
    assert train_video["sha256"] != holdout_video["sha256"]
    assert training["id"] != holdout["id"]
    assert training["manifest_sha256"] != holdout["manifest_sha256"]
    training_frames = _exported_frames(client, training["id"])
    holdout_frames = _exported_frames(client, holdout["id"])
    assert len(training_frames) == len(holdout_frames) == FRAME_COUNT
    if overlapping:
        assert training_frames == holdout_frames
    else:
        assert training_frames.isdisjoint(holdout_frames)
    return project, training, holdout


def _native_training_config() -> dict[str, int]:
    return {
        "epochs": 1,
        "batch": 1,
        "input_height": 64,
        "input_width": 64,
        "base_channels": 4,
        "fpn_channels": 8,
        "workers": 0,
    }


@pytest.mark.parametrize("provider", ["ultralytics", "reefpose"])
def test_queued_pose_worker_refuses_frozen_frame_overlap_before_output(
    client: TestClient,
    test_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    from ultralytics import YOLO

    project, training, holdout = _frozen_split(client, tmp_path, overlapping=True)
    project_id = str(project["id"])
    if provider == "ultralytics":
        architecture = "yolo11n-pose.yaml"
        config = {"epochs": 1, "batch": 1, "imgsz": 64, "workers": 0}
    else:
        architecture = "reefpose-s"
        config = _native_training_config()

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
    readiness = Mock(side_effect=AssertionError("Provider readiness ran before split validation"))
    monkeypatch.setattr("reefvision.jobs.pose_training.require_provider_ready", readiness)
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
    readiness.assert_not_called()
    managed = resolve_managed_project_path(
        test_settings, f"{project['storage_root']}/training/{run_id}"
    )
    assert not managed.exists()


def _native_frozen_split_graph(training: dict[str, Any], holdout: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_id": "recover-frozen-frame-study",
        "name": "Recovery of a completed native pose study",
        "nodes": [
            {
                "node_id": node_id,
                "node_type": "pose_training_dataset",
                "parameters": {
                    "dataset_id": dataset["id"],
                    "manifest_sha256": dataset["manifest_sha256"],
                },
            }
            for node_id, dataset in (("training", training), ("holdout", holdout))
        ]
        + [
            {
                "node_id": "train",
                "node_type": "pose_model_training",
                "parameters": {
                    "provider_id": "reefpose",
                    "architecture": "reefpose-s",
                    "device": "cpu",
                    "precision": "fp32",
                    "initialization_mode": "random",
                    "training_config": _native_training_config(),
                },
            }
        ],
        "edges": [
            {
                "edge_id": f"{node_id}-train",
                "source_node_id": node_id,
                "source_port_id": "dataset",
                "target_node_id": "train",
                "target_port_id": port_id,
            }
            for node_id, port_id in (("training", "dataset"), ("holdout", "validation_dataset"))
        ],
    }


@pytest.mark.parametrize("overlapping", [True, False], ids=["overlap", "disjoint"])
def test_saved_pose_retry_revalidates_frozen_frames_from_completed_child(
    client: TestClient,
    test_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overlapping: bool,
) -> None:
    project, training, holdout = _frozen_split(client, tmp_path, overlapping=overlapping)
    project_id = project["id"]
    graph = _native_frozen_split_graph(training, holdout)
    factory = cast(FastAPI, client.app).state.session_factory
    url = f"/api/v1/projects/{project_id}"
    saved = _checked(client.post(f"{url}/workflow-graphs", json={"graph": graph}), 201)
    queued = _checked(
        client.post(f"{url}/workflow-runs", json={"graph_record_id": saved["id"]}), 202
    )
    job_id = queued["job_id"]
    detail_url = f"/api/v1/workflow-runs/{queued['id']}"

    execute_node = WorkflowExecutionService.execute_node

    def interrupt_after_child(service: WorkflowExecutionService, **kwargs: Any) -> Any:
        outputs = execute_node(service, **kwargs)
        if kwargs["step"].node_type == "pose_model_training":
            raise OSError("Interrupted after the completed pose child")
        return outputs

    with monkeypatch.context() as historical:
        # Simulate the child predating the frame-content check. All actual fitting,
        # evaluation, checkpoint writing and experiment registration still run.
        historical.setattr(
            reefpose_training, "verify_pose_export_frame_separation", lambda *_: None, raising=False
        )
        historical.setattr(WorkflowExecutionService, "execute_node", interrupt_after_child)
        assert not process_workflow_run_job(test_settings, factory, job_id)

    before = _checked(client.get(detail_url), 200)
    assert before["run"]["status"] == "failed"
    assert "Interrupted after the completed pose child" in before["run"]["error_message"]
    assert {artifact["data_type"] for artifact in before["artifacts"]} == {"pose_training_dataset"}
    with factory() as session:
        child = session.scalars(
            select(TrainingRun).where(TrainingRun.project_id == project_id)
        ).one()
        assert child.status == "completed" and child.result_checkpoint_path
        assert child.job_id is not None
        child_id, child_job_id = child.id, child.job_id
        child_job = session.get(Job, child_job_id)
        assert child_job is not None and child_job.status == "succeeded"
        assert child_job.request_json["pose_training_dataset_id"] == training["id"]
        assert child_job.request_json["pose_validation_dataset_id"] == holdout["id"]
        experiment = session.scalars(
            select(ExperimentRecord).where(ExperimentRecord.training_run_id == child_id)
        ).one()
        experiment_id, experiment_metrics = experiment.id, experiment.summary_metrics_json
        checkpoint = resolve_managed_project_path(test_settings, child.result_checkpoint_path)
        original_checkpoint = checkpoint.read_bytes()
        sha256 = hashlib.sha256(original_checkpoint).hexdigest()
        child_manifest = child.artifact_manifest_json
        assert child_manifest["result_checkpoint_sha256"] == sha256
        assert child_manifest.get("frame_content_separation") is None
        frozen_manifests = dict(
            session.execute(
                select(PoseTrainingDataset.id, PoseTrainingDataset.manifest_json).where(
                    PoseTrainingDataset.project_id == project_id
                )
            ).all()
        )

    fitting_again = Mock(side_effect=AssertionError("Retry must reuse the completed pose child"))
    monkeypatch.setattr(ReefPoseTrainer, "fit", fitting_again)
    _checked(client.post(f"/api/v1/jobs/{job_id}/retry"), 200)
    processed = process_workflow_run_job(test_settings, factory, job_id)
    after = _checked(client.get(detail_url), 200)

    fitting_again.assert_not_called()
    assert after["run"]["job_id"] == job_id
    assert after["run"]["workflow_graph_record_id"] == saved["id"]
    assert after["run"]["graph_sha256"] == saved["graph_sha256"]
    assert checkpoint.read_bytes() == original_checkpoint
    with factory() as session:
        runs = session.scalars(
            select(TrainingRun).where(TrainingRun.project_id == project_id)
        ).all()
        assert [(run.id, run.job_id, run.status) for run in runs] == [
            (child_id, child_job_id, "completed")
        ]
        assert runs[0].artifact_manifest_json == child_manifest
        child_job = session.get(Job, child_job_id)
        assert child_job is not None and child_job.status == "succeeded"
        experiment = session.get(ExperimentRecord, experiment_id)
        assert experiment is not None and experiment.summary_metrics_json == experiment_metrics
        assert (
            session.scalar(
                select(ModelRegistration).where(ModelRegistration.project_id == project_id)
            )
            is None
        )
        for dataset_id, manifest in frozen_manifests.items():
            dataset = session.get(PoseTrainingDataset, dataset_id)
            assert dataset is not None and dataset.manifest_json == manifest

    results = [
        row["payload_json"] for row in after["artifacts"] if row["data_type"] == "training_result"
    ]
    registration = client.post(
        f"{url}/models/register-from-run", json={"training_run_id": child_id}
    )
    if overlapping:
        assert not processed and after["run"]["status"] == "failed", after["run"]
        assert "frozen frame" in after["run"]["error_message"].casefold()
        assert results == []
        assert registration.status_code == 400
        assert "frozen frame" in registration.json()["detail"].casefold()
        assert _checked(client.get(f"{url}/models"), 200) == []
    else:
        assert processed and after["run"]["status"] == "succeeded", after["run"]
        assert len(results) == 1
        assert results[0]["training_run_id"] == child_id
        assert results[0]["training_job_id"] == child_job_id
        assert results[0]["experiment_id"] == experiment_id
        assert results[0]["result_checkpoint_sha256"] == sha256
        assert _checked(registration, 200)["sha256"] == sha256


@pytest.mark.parametrize("checkpoint_io_error", [False, True])
def test_cancelling_a_workflow_during_frozen_pose_preparation_cancels_parent(
    client: TestClient,
    test_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint_io_error: bool,
) -> None:
    project, training, holdout = _frozen_split(client, tmp_path, overlapping=False)
    project_id = project["id"]
    graph = _native_frozen_split_graph(training, holdout)
    graph["nodes"].append({"node_id": "register", "node_type": "register_trained_model"})
    graph["edges"].append(
        {
            "edge_id": "train-register",
            "source_node_id": "train",
            "source_port_id": "training",
            "target_node_id": "register",
            "target_port_id": "training",
        }
    )
    factory = cast(FastAPI, client.app).state.session_factory
    url = f"/api/v1/projects/{project_id}"
    saved = _checked(client.post(f"{url}/workflow-graphs", json={"graph": graph}), 201)
    queued = _checked(
        client.post(f"{url}/workflow-runs", json={"graph_record_id": saved["id"]}), 202
    )
    parent_job_id = queued["job_id"]
    child_ids: list[str] = []
    export = PoseTrainingExportService.export

    def cancel_during_export(
        service: PoseTrainingExportService,
        dataset_id: str,
        export_format: PoseTrainingExportFormat,
    ) -> PoseTrainingExportArtifact:
        if dataset_id == training["id"] and not child_ids:
            [child] = _checked(client.get(f"{url}/training-runs"), 200)
            assert child["stage"] == "preparing_dataset"
            assert child["progress_epoch"] == 0
            child_ids.append(child["id"])
            cancelled = _checked(client.post(f"/api/v1/jobs/{parent_job_id}/cancel"), 200)
            assert cancelled["status"] == "cancel_requested"
        return export(service, dataset_id, export_format)

    with monkeypatch.context() as preparing:
        if checkpoint_io_error:
            preparing.setattr(
                "reefvision.jobs.reefpose_training.capture_checkpoints",
                Mock(side_effect=OSError("checkpoint volume unavailable")),
            )
        preparing.setattr(PoseTrainingExportService, "export", cancel_during_export)
        assert not process_workflow_run_job(test_settings, factory, parent_job_id)

    [child_id] = child_ids
    child = _checked(client.get(f"/api/v1/training-runs/{child_id}"), 200)
    assert child["status"] == "cancelled" and child["progress_epoch"] == 0
    assert child["metrics"] == {} and child["result_checkpoint_path"] is None
    assert child["registered_model_id"] is None
    child_job = _checked(client.get(f"/api/v1/jobs/{child['job_id']}"), 200)
    assert child_job["status"] == "cancelled"
    if checkpoint_io_error:
        assert "checkpoint volume unavailable" in child_job["error_message"]
        assert "resume_checkpoint_path" not in child["artifact_manifest"]
    assert _checked(client.get(f"{url}/models"), 200) == []
    assert _checked(client.get(f"{url}/experiments"), 200) == []
    parent = _checked(client.get(f"/api/v1/workflow-runs/{queued['id']}"), 200)
    assert {artifact["data_type"] for artifact in parent["artifacts"]} == {"pose_training_dataset"}
    for dataset in (training, holdout):
        frozen = _checked(client.get(f"/api/v1/pose-training-datasets/{dataset['id']}"), 200)
        assert frozen["manifest_sha256"] == dataset["manifest_sha256"]
        assert frozen["item_count"] == FRAME_COUNT
    assert parent["run"]["status"] == "cancelled", parent["run"]
    assert _checked(client.get(f"/api/v1/jobs/{parent_job_id}"), 200)["status"] == "cancelled"
    train = next(node for node in parent["nodes"] if node["node_id"] == "train")
    assert train["status"] == "cancelled"
