from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
import torch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ExperimentRecord,
    Job,
    ModelRegistration,
    PoseModelSchemaBinding,
    PoseTrainingDataset,
    Project,
    TrainingRun,
    VideoAsset,
    WorkflowArtifact,
    WorkflowRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.pose_training import (
    _claim_pose_training_output,
    _safe_extract_zip,
    materialize_pose_training_exports,
    process_pose_training_job,
)
from reefvision.jobs.reefpose_training import _dataset_for_run
from reefvision.jobs.training import (
    _complete_training_run,
)
from reefvision.jobs.worker import process_next_thumbnail_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.ml.providers import DetectionSettings
from reefvision.ml.reefpose.checkpoints import save_checkpoint
from reefvision.ml.reefpose.errors import ReefPoseCancelledError
from reefvision.ml.reefpose.provider import ReefPoseRegistrationProvider
from reefvision.ml.reefpose.training import ReefPoseTrainer
from reefvision.schemas.models import RegisterModelFromRunRequest
from reefvision.services.jobs import JobService
from reefvision.services.pose_training_exports import (
    EXPORT_MANIFEST_FILENAME,
    PoseTrainingExportService,
)
from reefvision.services.semantic_models import SemanticModelService
from reefvision.services.workflow_execution import WorkflowExecutionService
from reefvision.services.workflow_pose_training import (
    create_pose_workflow_training_result,
)
from reefvision.services.workflow_runtime_adapters import (
    RUNTIME_ADAPTER_NODE_TYPES,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import (
    resolve_managed_project_path,
)
from reefvision.tests.test_pose_training_datasets_phase9 import (
    _verified_round,
)


def _frozen_dataset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    dict[str, object],
    dict[str, object],
]:
    (
        project,
        _video,
        _track,
        round_payload,
    ) = _verified_round(
        client,
        monkeypatch,
    )

    response = client.post(
        (f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset"),
        json={
            "name": "Phase 10B pose training",
            "created_by": "scientist",
        },
    )

    assert response.status_code == 201, response.text

    return (
        project,
        response.json(),
    )


def _seed_model(
    app: FastAPI,
    project: dict[str, object],
    dataset: dict[str, object],
) -> str:
    model_id = "11111111-2222-4333-8444-555555555555"

    checkpoint_bytes = b"phase10-pose-seed"

    managed_path = f"{project['storage_root']}/models/{model_id}.pt"

    checkpoint = resolve_managed_project_path(
        app.state.settings,
        managed_path,
    )

    checkpoint.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    checkpoint.write_bytes(checkpoint_bytes)

    sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()

    first_class = cast(
        dict[str, object],
        cast(
            list[object],
            project["label_classes"],
        )[0],
    )

    with app.state.session_factory() as session:
        frozen = session.get(
            PoseTrainingDataset,
            str(dataset["id"]),
        )

        assert frozen is not None

        model = ModelRegistration(
            id=model_id,
            project_id=str(project["id"]),
            purpose="detector",
            display_name=("Phase 10B seed pose"),
            source_filename=("yolo11n-pose.pt"),
            managed_path=managed_path,
            sha256=sha256,
            file_size_bytes=len(checkpoint_bytes),
            framework="ultralytics",
            task="pose",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={
                "labels": [str(first_class["name"])],
                "mapping": {str(first_class["name"]): str(first_class["id"])},
            },
            input_size_json={
                "width": 640,
                "height": 640,
            },
            metadata_json={
                "pose_keypoint_shape": [
                    2,
                    3,
                ],
                "source_architecture": ("yolo11n-pose.pt"),
            },
        )

        session.add(model)

        session.flush()

        session.add(
            PoseModelSchemaBinding(
                model_id=model.id,
                schema_id=(frozen.pose_schema_id),
                schema_revision=(frozen.pose_schema_revision),
            )
        )

        session.commit()

    return model_id


def _fake_pose_processor(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(
            Job,
            job_id,
        )

        assert job is not None

        run = session.get(
            TrainingRun,
            str(job.request_json["training_run_id"]),
        )

        assert run is not None

        project = session.get(
            Project,
            run.project_id,
        )

        assert project is not None

        checkpoint_relative = f"{project.storage_root}/training/{run.id}/runs/pose/weights/best.pt"

        checkpoint = resolve_managed_project_path(
            settings,
            checkpoint_relative,
        )

        checkpoint.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        checkpoint.write_bytes(b"phase10-pose-trained-checkpoint")

        run.result_checkpoint_path = checkpoint_relative

        run.metrics_json = {
            "metrics/mAP50-95(P)": 0.42,
        }

        run.metrics_history_json = {
            "epoch": [1],
            "metrics/mAP50-95(P)": [0.42],
        }

        run.artifact_manifest_json = {
            **dict(run.artifact_manifest_json or {}),
            "best_checkpoint_path": (checkpoint_relative),
            "native_results_rows": [
                {
                    "epoch": 1,
                    "metrics/mAP50-95(P)": (0.42),
                }
            ],
            "artifacts": [
                {
                    "name": "best.pt",
                    "category": "checkpoint",
                    "relative_path": (checkpoint_relative),
                }
            ],
        }

        run.progress_epoch = 1
        run.progress_total_epochs = 1

        _complete_training_run(
            session,
            run,
            job,
        )

        session.commit()

    return True


def _pose_export_zip(
    marker: bytes,
    *,
    classes: tuple[tuple[str, str], ...] = (("stable-fixture-animal", "animal"),),
    labels: str = "0 0.5 0.5 0.5 0.5 0.5 0.5 2\n",
) -> bytes:
    stream = io.BytesIO()

    with zipfile.ZipFile(
        stream,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "images/train/frame_00000001.png",
            marker,
        )
        archive.writestr(
            "labels/train/frame_00000001.txt",
            labels,
        )
        archive.writestr(
            "data.yaml",
            (
                "path: .\n"
                "train: images/train\n"
                "val: images/train\n"
                "kpt_shape: [1, 3]\n"
                "names:\n"
                + "".join(
                    f"  {index}: {json.dumps(name)}\n" for index, (_, name) in enumerate(classes)
                )
            ),
        )
        archive.writestr(
            EXPORT_MANIFEST_FILENAME,
            json.dumps(
                {
                    "classes": [
                        {"class_index": index, "label_class_id": ident, "display_name": name}
                        for index, (ident, name) in enumerate(classes)
                    ],
                }
            ),
        )

    return stream.getvalue()


def _synthetic_exact_frames(
    *,
    source: Path,
    video: VideoAsset,
    frame_indices: list[int],
    export_format: str,
) -> tuple[dict[str, bytes], list[dict[str, object]]]:
    del source
    width = int(video.width_px)
    height = int(video.height_px)
    files: dict[str, bytes] = {}
    records: list[dict[str, object]] = []
    for frame_index in sorted(set(frame_indices)):
        stream = io.BytesIO()
        Image.new("RGB", (width, height), color=(48, 96, 144)).save(stream, format="PNG")
        content = stream.getvalue()
        relative = PoseTrainingExportService._frame_path(export_format, frame_index)  # type: ignore[arg-type]
        files[relative] = content
        records.append(
            {
                "source_frame_index": frame_index,
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "width_px": width,
                "height_px": height,
                "encoding": "png-lossless",
            }
        )
    return files, records


def _queue_native_reefpose_run(
    app: FastAPI,
    settings: Settings,
    *,
    project: dict[str, object],
    dataset: dict[str, object],
    epochs: int = 1,
) -> tuple[str, str]:
    with app.state.session_factory() as session:
        with pytest.raises(Exception, match="job=queued, run=queued"):
            create_pose_workflow_training_result(
                session,
                settings,
                project_id=str(project["id"]),
                dataset_payload={
                    "project_id": project["id"],
                    "dataset_id": dataset["id"],
                    "manifest_sha256": dataset["manifest_sha256"],
                },
                parameters={
                    "provider_id": "reefpose",
                    "architecture": "reefpose-s",
                    "device": "cpu",
                    "precision": "fp32",
                    "random_seed": 61,
                    "training_config": {
                        "epochs": epochs,
                        "batch": 1,
                        "input_height": 64,
                        "input_width": 64,
                        "base_channels": 4,
                        "fpn_channels": 8,
                        "workers": 0,
                    },
                },
                processor=lambda _settings, _factory, _job_id: True,
            )
        run = session.scalar(
            select(TrainingRun)
            .where(TrainingRun.provider_id == "reefpose")
            .order_by(TrainingRun.created_at.desc())
        )
        assert run is not None and run.job_id is not None
        return run.id, run.job_id


def test_pose_materialization_never_silently_reuses_training_for_validation(
    tmp_path: Path,
) -> None:
    training = _pose_export_zip(b"train")

    validation = _pose_export_zip(b"validation")

    destination = tmp_path / "pose-dataset"

    independent = materialize_pose_training_exports(
        training_content=training,
        validation_content=validation,
        destination=destination,
    )

    assert independent["validation_mode"] == "separate_frozen_pose_dataset"

    yaml_text = (destination / "data.yaml").read_text(encoding="utf-8")

    # Ultralytics must resolve relative split names from the managed YAML's directory.
    assert not any(line.startswith("path:") for line in yaml_text.splitlines())
    assert "train: images/train" in yaml_text
    assert "val: images/val" in yaml_text

    assert (destination / "images" / "train" / "frame_00000001.png").read_bytes() == b"train"

    assert (destination / "images" / "val" / "frame_00000001.png").read_bytes() == b"validation"

    no_validation_root = tmp_path / "pose-no-validation"

    exploratory = materialize_pose_training_exports(
        training_content=training,
        validation_content=None,
        destination=no_validation_root,
    )

    assert exploratory["validation_mode"] == "none"

    assert exploratory["validation_image_count"] == 0


def test_pose_holdout_rejects_a_repeated_frame_at_a_different_index(tmp_path: Path) -> None:
    training = _pose_export_zip(b"reviewed training frame")
    disjoint = _pose_export_zip(b"independent validation frame")
    overlapping = io.BytesIO(disjoint)
    with zipfile.ZipFile(overlapping, "a") as archive:
        archive.writestr("images/train/frame_00000042.png", b"reviewed training frame")
        archive.writestr("labels/train/frame_00000042.txt", "0 0.5 0.5 0.5 0.5 0.5 0.5 2\n")

    output = tmp_path / "pose-dataset"
    with pytest.raises(ValidationError, match="frozen frame"):
        materialize_pose_training_exports(
            training_content=training, validation_content=overlapping.getvalue(), destination=output
        )
    assert list(tmp_path.iterdir()) == []

    recovered = materialize_pose_training_exports(
        training_content=training, validation_content=disjoint, destination=output
    )
    assert recovered["training_image_count"] == recovered["validation_image_count"] == 1
    assert recovered["frame_content_separation"] == {
        "method": "exact-lossless-png-sha256-v1",
        "training_export_sha256": hashlib.sha256(training).hexdigest(),
        "validation_export_sha256": hashlib.sha256(disjoint).hexdigest(),
    }


def test_pose_holdout_uses_training_ordinal_for_the_same_stable_class(tmp_path: Path) -> None:
    training = _pose_export_zip(
        b"train", classes=(("assigned", "animal"), ("unassigned", "neutral"))
    )
    original_labels = "0 0.5 0.5 0.5 0.5 0.27 0.36 1\n\n"
    validation = _pose_export_zip(
        b"validation", classes=(("unassigned", "renamed neutral"),), labels=original_labels
    )
    output = tmp_path / "pose-dataset"
    materialized = materialize_pose_training_exports(
        training_content=training, validation_content=validation, destination=output
    )
    assert (output / "labels/val/frame_00000001.txt").read_text() == "1" + original_labels[1:]
    assert (output / "labels/train/frame_00000001.txt").read_text().startswith("0 ")
    assert materialized["validation_class_projection"] == [
        {"label_class_id": "unassigned", "validation_class_index": 0, "training_class_index": 1}
    ]
    with zipfile.ZipFile(io.BytesIO(validation)) as archive:
        assert archive.read("labels/train/frame_00000001.txt").decode() == original_labels


def test_pose_holdout_refuses_a_different_class_even_with_the_same_name(tmp_path: Path) -> None:
    output = tmp_path / "pose-dataset"
    previous = tmp_path / "previous-checkpoint.pt"
    previous.write_bytes(b"existing generated scientific result")
    with pytest.raises(ValidationError, match="Validation classes were not present in training"):
        materialize_pose_training_exports(
            training_content=_pose_export_zip(b"train", classes=(("stable-a", "shared name"),)),
            validation_content=_pose_export_zip(
                b"validation", classes=(("stable-b", "shared name"),)
            ),
            destination=output,
        )
    assert not output.exists()
    assert not (tmp_path / ".pose-dataset-validation").exists()
    assert previous.read_bytes() == b"existing generated scientific result"


def test_pose_materialization_preserves_validation_stage_raced_after_precheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "pose-dataset"
    staging = tmp_path / ".pose-dataset-validation"
    other_review = staging / "prior-science.txt"

    def competing_claim(content: bytes, target: Path) -> None:
        if target == staging:
            staging.mkdir()
            other_review.write_bytes(b"other-reviewed-run")
        _safe_extract_zip(content, target)

    monkeypatch.setattr("reefvision.jobs.pose_training._safe_extract_zip", competing_claim)
    try:
        with pytest.raises(ValidationError, match="refusing to overwrite prior scientific data"):
            materialize_pose_training_exports(
                training_content=_pose_export_zip(b"reviewed-training"),
                validation_content=_pose_export_zip(b"new-holdout"),
                destination=destination,
            )
    finally:
        assert other_review.is_file(), "The losing worker removed the competing validation stage"
        assert other_review.read_bytes() == b"other-reviewed-run"

    assert not (staging / "data.yaml").exists()
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed-training"


@pytest.mark.parametrize("existing", ["pose-dataset", ".pose-dataset-validation"])
def test_pose_materialization_refuses_unowned_stage_without_writes(
    tmp_path: Path, existing: str
) -> None:
    destination = tmp_path / "pose-dataset"
    retained = tmp_path / existing
    retained.mkdir()
    original = retained / "prior-science.txt"
    original.write_bytes(b"previous-results")

    try:
        with pytest.raises(ValidationError, match="refusing to overwrite prior scientific data"):
            materialize_pose_training_exports(
                training_content=_pose_export_zip(b"reviewed-training"),
                validation_content=_pose_export_zip(b"reviewed-validation"),
                destination=destination,
            )
    finally:
        assert original.is_file(), "An existing stage was removed"
        assert original.read_bytes() == b"previous-results"
    assert not (destination / "data.yaml").exists()


def test_pose_materialization_cleans_own_partial_extraction_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "pose-dataset"
    training_content = _pose_export_zip(b"reviewed-training")
    validation_content = _pose_export_zip(b"reviewed-validation")

    with monkeypatch.context() as faults:

        def interrupted_copy(*_args: object, **_kwargs: object) -> None:
            raise OSError("fixture drive interrupted after destination was claimed")

        faults.setattr("reefvision.jobs.pose_training.shutil.copyfileobj", interrupted_copy)
        with pytest.raises(OSError, match="fixture drive interrupted"):
            materialize_pose_training_exports(
                training_content=training_content,
                validation_content=validation_content,
                destination=destination,
            )
    assert not destination.exists()

    retried = materialize_pose_training_exports(
        training_content=training_content,
        validation_content=validation_content,
        destination=destination,
    )
    assert retried["training_image_count"] == retried["validation_image_count"] == 1
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed-training"
    assert (destination / "images/val/frame_00000001.png").read_bytes() == b"reviewed-validation"


@pytest.mark.parametrize("relative", ["ultralytics", "runs/pose"])
def test_pose_output_claim_preserves_interrupted_run(tmp_path: Path, relative: str) -> None:
    previous = tmp_path / "interrupted-run" / relative
    previous.mkdir(parents=True)
    marker = previous / "existing-result.txt"
    marker.write_bytes(b"prior scientific artifact")

    with pytest.raises(ValidationError, match="refusing to overwrite prior artifacts"):
        _claim_pose_training_output(previous)
    assert marker.read_bytes() == b"prior scientific artifact"

    new_output = tmp_path / "new-run" / relative
    _claim_pose_training_output(new_output)
    assert list(new_output.iterdir()) == []
    with pytest.raises(ValidationError, match="refusing to overwrite prior artifacts"):
        _claim_pose_training_output(new_output)


def test_pose_training_workflow_node_is_registered_and_executable(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/workflow-graphs/node-registry")

    assert response.status_code == 200, response.text

    registry = {item["node_type"]: item for item in response.json()}

    node = registry["pose_model_training"]

    assert node["executable"] is True

    assert {item["port_id"] for item in node["input_ports"]} == {
        "dataset",
        "validation_dataset",
        "initial_model",
    }

    assert node["output_ports"][0]["accepted_types"] == ["training_result"]

    assert "pose_model_training" in RUNTIME_ADAPTER_NODE_TYPES


def test_pose_workflow_training_creates_normal_training_result_without_gpu(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, dataset = _frozen_dataset(
        client,
        monkeypatch,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    model_id = _seed_model(
        app,
        project,
        dataset,
    )

    with app.state.session_factory() as session:
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": (project["id"]),
                "dataset_id": (dataset["id"]),
                "manifest_sha256": (dataset["manifest_sha256"]),
            },
            initial_model_payload={
                "model_id": model_id,
            },
            parameters={
                "run_name": ("phase10-pose-retrain"),
                "device": "cpu",
                "precision": "fp32",
                "random_seed": 31,
                "training_config": {
                    "epochs": 1,
                },
            },
            workflow_run_id=("phase10-workflow"),
            workflow_node_run_id=("phase10-pose-training-node"),
            processor=(_fake_pose_processor),
        )

    assert result["task"] == "pose"
    assert result["provider_id"] == "ultralytics"

    assert result["pose_training_dataset_id"] == dataset["id"]

    assert result["validation_mode"] == "none"

    assert result["dataset_version_id"] is None

    assert len(result["dataset_manifest_sha256"]) == 64

    assert len(result["split_manifest_sha256"]) == 64

    assert len(result["result_checkpoint_sha256"]) == 64

    assert result["metrics"]["metrics/mAP50-95(P)"] == 0.42

    assert any(
        "no separate frozen validation dataset" in warning.casefold()
        for warning in result["warnings"]
    )


def test_pose_training_can_require_separate_validation_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, dataset = _frozen_dataset(
        client,
        monkeypatch,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    model_id = _seed_model(
        app,
        project,
        dataset,
    )

    with (
        app.state.session_factory() as session,
        pytest.raises(
            Exception,
            match=("requires a separate frozen validation dataset"),
        ),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": (project["id"]),
                "dataset_id": (dataset["id"]),
                "manifest_sha256": (dataset["manifest_sha256"]),
            },
            initial_model_payload={
                "model_id": model_id,
            },
            parameters={
                "require_validation_dataset": (True),
                "training_config": {
                    "epochs": 1,
                },
            },
            processor=(_fake_pose_processor),
        )


def test_pose_training_workflow_exposes_provider_without_changing_legacy_default(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/workflow-graphs/node-registry")

    assert response.status_code == 200, response.text
    node = next(item for item in response.json() if item["node_type"] == "pose_model_training")

    assert node["optional_parameters"]["provider_id"] == "ultralytics"
    assert node["optional_parameters"]["architecture"] == "yolo11n-pose.yaml"
    assert "ReefPose-S" in node["description"]


def test_reefpose_workflow_training_supports_random_initialization(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": project["id"],
                "dataset_id": dataset["id"],
                "manifest_sha256": dataset["manifest_sha256"],
            },
            parameters={
                "provider_id": "reefpose",
                "architecture": "reefpose-s",
                "device": "cpu",
                "precision": "fp32",
                "random_seed": 47,
                "training_config": {"epochs": 1, "batch": 2, "input_height": 64},
            },
            workflow_run_id="phase2a-workflow",
            workflow_node_run_id="phase2a-training-node",
            processor=_fake_pose_processor,
        )

        run = session.get(TrainingRun, str(result["training_run_id"]))
        assert run is not None
        assert run.provider_id == "reefpose"
        assert run.architecture == "reefpose-s"
        assert run.initial_checkpoint_source == "scratch"
        assert run.parameter_registry_version
        assert run.training_config_json["batch"] == 2
        assert run.training_config_json["input_height"] == 64
        assert run.training_config_json["input_width"] == 256

    assert result["provider_id"] == "reefpose"
    assert result["initialization_mode"] == "random"


def test_reefpose_workflow_rejects_wrong_architecture_and_cross_provider_replay(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }

    with app.state.session_factory() as session:
        with pytest.raises(Exception, match="ReefPose training requires architecture reefpose-s"):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={
                    "provider_id": "reefpose",
                    "architecture": "yolo11n-pose.yaml",
                    "training_config": {"epochs": 1},
                },
                processor=_fake_pose_processor,
            )

        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="provider-replay-workflow",
            workflow_node_run_id="provider-replay-node",
            processor=_fake_pose_processor,
        )

        with pytest.raises(Exception, match="provider changed"):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={
                    "provider_id": "reefpose",
                    "architecture": "reefpose-s",
                    "training_config": {"epochs": 1},
                },
                workflow_run_id="provider-replay-workflow",
                workflow_node_run_id="provider-replay-node",
                processor=_fake_pose_processor,
            )


def test_native_reefpose_workflow_executes_and_persists_best_checkpoint(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        PoseTrainingExportService,
        "_extract_exact_frames",
        staticmethod(_synthetic_exact_frames),
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": project["id"],
                "dataset_id": dataset["id"],
                "manifest_sha256": dataset["manifest_sha256"],
            },
            parameters={
                "provider_id": "reefpose",
                "architecture": "reefpose-s",
                "device": "cpu",
                "precision": "fp32",
                "random_seed": 0,
                "training_config": {
                    "epochs": 1,
                    "batch": 1,
                    "input_height": 64,
                    "input_width": 64,
                    "base_channels": 4,
                    "fpn_channels": 8,
                    "workers": 0,
                },
            },
        )

        run = session.get(TrainingRun, str(result["training_run_id"]))
        job = session.get(Job, str(result["training_job_id"]))
        assert run is not None and job is not None
        assert run.status == "completed"
        assert job.status == "succeeded"
        assert run.progress_epoch == 1
        assert run.metrics_json["selection_loss"] >= 0
        assert run.artifact_manifest_json["reproducibility"]["seed"] == 0
        assert run.artifact_manifest_json["dataset_format"] == "ultralytics_pose"
        assert run.artifact_manifest_json["best_checkpoint_path"] == run.result_checkpoint_path

    checkpoint = resolve_managed_project_path(test_settings, str(result["result_checkpoint_path"]))
    assert checkpoint.is_file()
    assert checkpoint.read_bytes()


def test_native_reefpose_retry_dispatches_through_normal_worker(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        PoseTrainingExportService,
        "_extract_exact_frames",
        staticmethod(_synthetic_exact_frames),
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    run_id, job_id = _queue_native_reefpose_run(
        app,
        test_settings,
        project=project,
        dataset=dataset,
    )

    assert process_next_thumbnail_job(test_settings, app.state.session_factory)

    with app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        job = session.get(Job, job_id)
        assert run is not None and job is not None
        assert run.status == "completed"
        assert job.status == "succeeded"


def test_native_reefpose_validation_dataset_uses_queued_split_snapshot(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    run_id, _job_id = _queue_native_reefpose_run(
        app,
        test_settings,
        project=project,
        dataset=dataset,
    )

    with app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        original = session.get(PoseTrainingDataset, str(dataset["id"]))
        assert run is not None and original is not None
        original_sha = original.manifest_sha256
        manifest = dict(run.artifact_manifest_json or {})
        manifest["pose_split_manifest"] = {
            **dict(manifest["pose_split_manifest"]),
            "validation_dataset_id": original.id,
            "validation_dataset_manifest_sha256": original_sha,
        }
        manifest["pose_split_manifest_sha256"] = canonical_json_sha256(
            manifest["pose_split_manifest"]
        )
        run.artifact_manifest_json = manifest
        session.flush()

        corrupted = dict(manifest)
        corrupted["pose_split_manifest"] = {
            **dict(manifest["pose_split_manifest"]),
            "validation_dataset_manifest_sha256": "0" * 64,
        }
        run.artifact_manifest_json = corrupted
        session.flush()
        with pytest.raises(Exception, match="split snapshot integrity changed"):
            _dataset_for_run(
                session,
                run=run,
                dataset_id=original.id,
                role="validation",
            )

        run.artifact_manifest_json = manifest
        original.manifest_sha256 = "f" * 64
        session.flush()

        with pytest.raises(Exception, match="validation dataset manifest changed"):
            _dataset_for_run(
                session,
                run=run,
                dataset_id=original.id,
                role="validation",
            )


def test_native_reefpose_cancellation_retries_from_resumable_checkpoint(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        PoseTrainingExportService,
        "_extract_exact_frames",
        staticmethod(_synthetic_exact_frames),
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    run_id, job_id = _queue_native_reefpose_run(
        app,
        test_settings,
        project=project,
        dataset=dataset,
        epochs=2,
    )
    original_fit = ReefPoseTrainer.fit

    def cancel_fit(self: ReefPoseTrainer, *args: object, **kwargs: object) -> object:
        del args
        epoch_callback = kwargs.get("epoch_callback")
        best_metrics = {
            "train_loss": 0.1,
            "train_heatmap_loss": 0.08,
            "train_visibility_loss": 0.2,
            "selection_loss": 0.1,
            "best_selection_loss": 0.1,
        }
        latest_metrics = {
            "train_loss": 0.5,
            "train_heatmap_loss": 0.45,
            "train_visibility_loss": 0.5,
            "selection_loss": 0.5,
            "best_selection_loss": 0.1,
        }
        for name, metrics in (
            ("best.pt", best_metrics),
            ("last.pt", latest_metrics),
            ("cancelled.pt", latest_metrics),
        ):
            save_checkpoint(
                self.config.output_dir / name,
                model=self.model,
                schema=self.schema,
                epoch=0,
                global_step=1,
                metrics=metrics,
                optimizer=self.optimizer,
                scaler=self.scaler,
                training_config=self.config.to_dict(),
                reproducibility=self.reproducibility,
            )
        assert callable(epoch_callback)
        epoch_callback(1, 2, latest_metrics)
        self.log_path.write_text('{"event":"before-cancel"}\n', encoding="utf-8")
        raise ReefPoseCancelledError("synthetic cancellation")

    monkeypatch.setattr(ReefPoseTrainer, "fit", cancel_fit)
    assert process_pose_training_job(test_settings, app.state.session_factory, job_id)

    with app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        job = session.get(Job, job_id)
        assert run is not None and job is not None
        assert run.status == job.status == "cancelled"
        assert run.result_checkpoint_path is None
        assert run.artifact_manifest_json["resume_checkpoint_path"]
        managed_best = resolve_managed_project_path(
            test_settings,
            str(run.artifact_manifest_json["resume_best_checkpoint_path"]),
        )
        assert managed_best.is_file()
        JobService(session).retry(job_id)
        session.refresh(run)
        assert run.status == "queued"

    monkeypatch.setattr(ReefPoseTrainer, "fit", original_fit)
    real_copy2 = shutil.copy2
    failed_once = {"value": False}

    def fail_resumed_finalization(
        source: object, destination: object, *args: object, **kwargs: object
    ):
        if (
            not failed_once["value"]
            and "reefpose-run-" in str(source)
            and Path(destination).name == "best.pt"
        ):
            failed_once["value"] = True
            raise OSError("synthetic resumed finalization failure")
        return real_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr("reefvision.jobs.reefpose_training.shutil.copy2", fail_resumed_finalization)
    assert not process_next_thumbnail_job(test_settings, app.state.session_factory)

    with app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        assert run is not None
        resume_path = str(run.artifact_manifest_json["resume_checkpoint_path"])
        assert Path(resume_path).name == "last.pt"
        JobService(session).retry(job_id)

    monkeypatch.setattr("reefvision.jobs.reefpose_training.shutil.copy2", real_copy2)
    assert process_next_thumbnail_job(test_settings, app.state.session_factory)

    with app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        job = session.get(Job, job_id)
        assert run is not None and job is not None
        assert run.status == "completed"
        assert job.status == "succeeded"
        assert run.result_checkpoint_path
        assert run.metrics_history_json["epoch"] == [1, 2]
        assert len(run.artifact_manifest_json["native_results_rows"]) == 2
        managed_log = resolve_managed_project_path(test_settings, str(run.logs_path))
        assert '"event":"before-cancel"' in managed_log.read_text(encoding="utf-8")


def test_registered_reefpose_checkpoint_starts_a_fresh_training_run(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        PoseTrainingExportService,
        "_extract_exact_frames",
        staticmethod(_synthetic_exact_frames),
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    parameters = {
        "provider_id": "reefpose",
        "architecture": "reefpose-s",
        "device": "cpu",
        "precision": "fp32",
        "training_config": {
            "epochs": 1,
            "batch": 1,
            "input_height": 64,
            "input_width": 64,
            "base_channels": 4,
            "fpn_channels": 8,
            "workers": 0,
        },
    }

    with app.state.session_factory() as session:
        first = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters=parameters,
            workflow_run_id="native-seed-source",
            workflow_node_run_id="native-seed-source-node",
        )
        registered = SemanticModelService(session, test_settings).register_model_from_run(
            str(project["id"]),
            RegisterModelFromRunRequest(
                training_run_id=str(first["training_run_id"]),
                display_name="Native ReefPose seed",
            ),
        )
        second = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            initial_model_payload={"model_id": registered.id},
            parameters={**parameters, "initialization_mode": "registered_model"},
            workflow_run_id="native-seed-target",
            workflow_node_run_id="native-seed-target-node",
        )
        second_run = session.get(TrainingRun, str(second["training_run_id"]))
        assert second_run is not None
        assert second_run.status == "completed"
        assert second_run.progress_epoch == 1
        assert second_run.artifact_manifest_json["initialization_mode"] == "registered_model"


def test_native_reefpose_finalization_failure_retries_without_retraining(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        PoseTrainingExportService,
        "_extract_exact_frames",
        staticmethod(_synthetic_exact_frames),
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    run_id, job_id = _queue_native_reefpose_run(
        app,
        test_settings,
        project=project,
        dataset=dataset,
    )
    real_copy2 = shutil.copy2
    failed_once = {"value": False}

    def fail_first_best_copy(source: object, destination: object, *args: object, **kwargs: object):
        if not failed_once["value"] and Path(destination).name == "best.pt":
            failed_once["value"] = True
            raise OSError("synthetic finalization failure")
        return real_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr("reefvision.jobs.reefpose_training.shutil.copy2", fail_first_best_copy)
    assert not process_pose_training_job(test_settings, app.state.session_factory, job_id)

    with app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        job = session.get(Job, job_id)
        assert run is not None and job is not None
        assert run.status == "failed"
        JobService(session).retry(job_id)

    monkeypatch.setattr("reefvision.jobs.reefpose_training.shutil.copy2", real_copy2)
    processed = process_pose_training_job(test_settings, app.state.session_factory, job_id)
    with app.state.session_factory() as session:
        retry_run = session.get(TrainingRun, run_id)
        assert retry_run is not None
        assert processed, retry_run.error_message

    with app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.result_checkpoint_path


def test_native_reefpose_execution_rejects_schema_drift_without_registration_artifact(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        PoseTrainingExportService,
        "_extract_exact_frames",
        staticmethod(_synthetic_exact_frames),
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    run_id, job_id = _queue_native_reefpose_run(
        app,
        test_settings,
        project=project,
        dataset=dataset,
    )

    with app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        frozen = session.get(PoseTrainingDataset, str(dataset["id"]))
        assert run is not None and frozen is not None
        original_manifest = frozen.manifest_sha256
        run.artifact_manifest_json = {
            **dict(run.artifact_manifest_json),
            "pose_schema_content_hash": "0" * 64,
        }
        session.commit()

    assert not process_pose_training_job(test_settings, app.state.session_factory, job_id)

    with app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        frozen = session.get(PoseTrainingDataset, str(dataset["id"]))
        experiment = session.scalar(
            select(ExperimentRecord).where(ExperimentRecord.training_run_id == run_id)
        )
        assert run is not None and frozen is not None
        assert run.status == "failed"
        assert "schema changed" in str(run.error_message)
        assert run.result_checkpoint_path is None
        assert experiment is None
        assert frozen.manifest_sha256 == original_manifest


def test_completed_native_reefpose_checkpoint_registers_and_runs_inference(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        PoseTrainingExportService,
        "_extract_exact_frames",
        staticmethod(_synthetic_exact_frames),
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        trained = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": project["id"],
                "dataset_id": dataset["id"],
                "manifest_sha256": dataset["manifest_sha256"],
            },
            parameters={
                "provider_id": "reefpose",
                "architecture": "reefpose-s",
                "device": "cpu",
                "precision": "fp32",
                "training_config": {
                    "epochs": 1,
                    "batch": 1,
                    "input_height": 64,
                    "input_width": 64,
                    "base_channels": 4,
                    "fpn_channels": 8,
                    "workers": 0,
                },
            },
        )
        registered = SemanticModelService(session, test_settings).register_model_from_run(
            str(project["id"]),
            RegisterModelFromRunRequest(
                training_run_id=str(trained["training_run_id"]),
                display_name="Native ReefPose workflow model",
            ),
        )
        binding = session.get(PoseModelSchemaBinding, registered.id)
        assert binding is not None
        assert binding.schema_id == dataset["pose_schema_id"]
        assert binding.schema_revision == dataset["pose_schema_revision"]

    assert registered.provider_name == "reefpose"
    assert registered.task == "pose"
    assert registered.metadata_json["source_training_run_id"] == trained["training_run_id"]
    assert (
        registered.metadata_json["source_pose_schema_content_hash"]
        == dataset["pose_schema_content_hash"]
    )
    pose_schema = registered.metadata_json["pose_landmark_schema"]
    assert pose_schema["schema_name"] == "Phase 9 repeated tentacle schema"
    assert pose_schema["keypoint_count"] == 2
    assert [item["id"] for item in pose_schema["definition"]["landmarks"]] == [
        "tentacle_1",
        "tentacle_2",
    ]
    assert registered.metadata_json["source_training_config"]["epochs"] == 1
    assert registered.metadata_json["source_device"] == "cpu"
    assert registered.metadata_json["source_precision"] == "fp32"
    assert registered.metadata_json["source_checkpoint_sha256"] == registered.sha256
    assert registered.metadata_json["source_checkpoint_size_bytes"] > 0

    image_path = tmp_path / "synthetic-animal.png"
    Image.new("RGB", (80, 48), color=(32, 64, 96)).save(image_path)
    checkpoint = resolve_managed_project_path(test_settings, registered.managed_path)
    provider = ReefPoseRegistrationProvider()
    provider.load_model(checkpoint, "cpu")
    predictions = provider.predict(
        image_path,
        DetectionSettings(confidence_threshold=0.0, iou_threshold=0.5, device="cpu"),
    )
    provider.unload_model()

    assert len(predictions) == 1
    assert len(predictions[0].keypoints or ()) == 2
    assert predictions[0].pose_schema["schema_revision"] == dataset["pose_schema_revision"]
    assert [item.landmark_id for item in predictions[0].keypoints or ()] == [
        "tentacle_1",
        "tentacle_2",
    ]


def _native_pose_workflow_graph(dataset_id: str) -> dict[str, object]:
    return {
        "graph_id": "phase2a-native-reefpose",
        "name": "Phase 2A native ReefPose",
        "nodes": [
            {
                "node_id": "dataset",
                "node_type": "pose_training_dataset",
                "parameters": {"dataset_id": dataset_id},
            },
            {
                "node_id": "train",
                "node_type": "pose_model_training",
                "parameters": {
                    "provider_id": "reefpose",
                    "architecture": "reefpose-s",
                    "device": "cpu",
                    "precision": "fp32",
                    "training_config": {
                        "epochs": 1,
                        "batch": 1,
                        "input_height": 64,
                        "input_width": 64,
                        "base_channels": 4,
                        "fpn_channels": 8,
                        "workers": 0,
                    },
                },
            },
            {
                "node_id": "register",
                "node_type": "register_trained_model",
                "parameters": {"display_name": "Repeated native study"},
            },
        ],
        "edges": [
            {
                "edge_id": "dataset-train",
                "source_node_id": "dataset",
                "source_port_id": "dataset",
                "target_node_id": "train",
                "target_port_id": "dataset",
            },
            {
                "edge_id": "train-register",
                "source_node_id": "train",
                "source_port_id": "training",
                "target_node_id": "register",
                "target_port_id": "training",
            },
        ],
    }


@pytest.mark.parametrize("cancel_parent", [True, False], ids=["workflow", "training-job"])
def test_cancelling_before_pose_worker_claim_closes_the_training_and_graph(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    cancel_parent: bool,
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    url = f"/api/v1/projects/{project['id']}"
    saved = client.post(
        url + "/workflow-graphs", json={"graph": _native_pose_workflow_graph(str(dataset["id"]))}
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(url + "/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert queued.status_code == 202, queued.text
    parent_id = queued.json()["job_id"]

    def cancel_before_claim(
        settings: Settings, factory: sessionmaker[Session], job_id: str
    ) -> bool:
        with factory() as session:
            child = session.get(Job, job_id)
            assert child is not None and child.status == "queued"
        target = parent_id if cancel_parent else job_id
        cancelled = client.post(f"/api/v1/jobs/{target}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        return process_pose_training_job(settings, factory, job_id)

    monkeypatch.setattr(
        "reefvision.jobs.reefpose_training.process_reefpose_training_job", cancel_before_claim
    )
    assert not process_workflow_run_job(app.state.settings, app.state.session_factory, parent_id)
    (training,) = client.get(url + "/training-runs").json()
    assert training["status"] == training["stage"] == "cancelled"
    assert training["completed_at"] and training["result_checkpoint_path"] is None
    child_job = client.get(f"/api/v1/jobs/{training['job_id']}").json()
    assert child_job["status"] == child_job["result_json"]["stage"] == "cancelled"
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json()
    assert detail["run"]["status"] == "cancelled"
    assert {n["node_id"]: n["status"] for n in detail["nodes"]} == {
        "dataset": "succeeded",
        "train": "cancelled",
        "register": "cancelled",
    }
    assert all(n["completed_at"] for n in detail["nodes"])
    assert len(detail["artifacts"]) == 1
    assert detail["artifacts"][0]["payload_json"]["manifest_sha256"] == dataset["manifest_sha256"]


def test_saved_native_reefpose_workflow_executes_and_replays(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        PoseTrainingExportService,
        "_extract_exact_frames",
        staticmethod(_synthetic_exact_frames),
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    url = f"/api/v1/projects/{project['id']}"
    saved = client.post(
        url + "/workflow-graphs", json={"graph": _native_pose_workflow_graph(str(dataset["id"]))}
    )
    assert saved.status_code == 201, saved.text
    models = {}
    for _ in range(2):
        queued = client.post(url + "/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert queued.status_code == 202, queued.text
        run_id, job_id = queued.json()["id"], queued.json()["job_id"]
        processed = process_workflow_run_job(app.state.settings, app.state.session_factory, job_id)
        if not processed:
            state = client.get(f"/api/v1/workflow-runs/{run_id}")
            pytest.fail(f"Native ReefPose saved workflow failed: {state.json()!r}")
        with app.state.session_factory() as session:
            run = session.get(WorkflowRun, run_id)
            assert run is not None and run.status == "succeeded"
            model_artifact = session.scalar(
                select(WorkflowArtifact).where(
                    WorkflowArtifact.workflow_run_id == run_id,
                    WorkflowArtifact.data_type == "model_reference",
                )
            )
            assert model_artifact is not None
            assert model_artifact.payload_json["provider_name"] == "reefpose"
            assert run.workflow_graph_record_id == saved.json()["id"]
            model = session.get(ModelRegistration, model_artifact.payload_json["model_id"])
            assert model is not None and model.display_name.startswith("Repeated native study")
            models[model.sha256] = (model.id, model.display_name)
            assert (
                model_artifact.payload_json["pose_schema_content_hash"]
                == dataset["pose_schema_content_hash"]
            )
    assert len(models) == len(set(models.values())) == 2


@pytest.mark.parametrize(
    "fault", ["missing", "provider", "artifact", "metrics", "intact", "historical", "checkpoint"]
)
def test_saved_pose_retry_requires_its_current_experiment_lineage(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    monkeypatch.setattr(
        PoseTrainingExportService,
        "_extract_exact_frames",
        staticmethod(_synthetic_exact_frames),
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    url = f"/api/v1/projects/{project['id']}"
    graph = _native_pose_workflow_graph(str(dataset["id"]))
    prior_checkpoint: bytes | None = None
    prior_training_id: str | None = None
    if fault == "checkpoint":
        prior = client.post(url + "/workflow-graphs", json={"graph": graph})
        assert prior.status_code == 201, prior.text
        prior_queued = client.post(
            url + "/workflow-runs", json={"graph_record_id": prior.json()["id"]}
        )
        assert prior_queued.status_code == 202, prior_queued.text
        assert process_workflow_run_job(app.state.settings, factory, prior_queued.json()["job_id"])
        prior_detail = client.get(f"/api/v1/workflow-runs/{prior_queued.json()['id']}").json()
        prior_artifact = next(
            row["payload_json"]
            for row in prior_detail["artifacts"]
            if row["data_type"] == "training_result"
        )
        prior_training_id = prior_artifact["training_run_id"]
        prior_path = resolve_managed_project_path(
            app.state.settings, prior_artifact["result_checkpoint_path"]
        )
        prior_checkpoint = prior_path.read_bytes()
        assert (
            hashlib.sha256(prior_checkpoint).hexdigest()
            == prior_artifact["result_checkpoint_sha256"]
        )
        assert ReefPoseRegistrationProvider().inspect_model(prior_path).task == "pose"
        # Reproduce using a training-only graph so registration cannot mask an incorrect result.
        nodes, edges = graph["nodes"], graph["edges"]
        assert isinstance(nodes, list) and isinstance(edges, list)
        graph["nodes"], graph["edges"] = nodes[:2], edges[:1]

    saved = client.post(url + "/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    queued = client.post(url + "/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert queued.status_code == 202, queued.text
    run_id, job_id = queued.json()["id"], queued.json()["job_id"]

    execute = WorkflowExecutionService.execute_node

    def interrupt_after_completed_child(
        service: WorkflowExecutionService, **kwargs: Any
    ) -> list[dict[str, Any]]:
        outputs = execute(service, **kwargs)
        if kwargs["step"].node_type == "pose_model_training":
            raise OSError("Synthetic interruption after durable training completion")
        return outputs

    with monkeypatch.context() as interrupted:
        interrupted.setattr(
            WorkflowExecutionService, "execute_node", interrupt_after_completed_child
        )
        assert not process_workflow_run_job(app.state.settings, factory, job_id)
    before = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    assert "interruption after durable training completion" in before["run"]["error_message"]
    assert "training_result" not in {row["data_type"] for row in before["artifacts"]}

    with factory() as session:
        child = session.scalar(
            select(TrainingRun).where(
                TrainingRun.project_id == project["id"], TrainingRun.id != prior_training_id
            )
        )
        assert child is not None and child.status == "completed" and child.result_checkpoint_path
        child_id = child.id
        child_job_id = child.job_id
        checkpoint = resolve_managed_project_path(app.state.settings, child.result_checkpoint_path)
        original_checkpoint = checkpoint.read_bytes()
        sha = hashlib.sha256(original_checkpoint).hexdigest()
        assert child.artifact_manifest_json["result_checkpoint_sha256"] == sha
        experiment = session.scalar(
            select(ExperimentRecord).where(ExperimentRecord.training_run_id == child_id)
        )
        assert experiment is not None
        experiment_id = experiment.id
        if fault in {"missing", "historical"}:
            session.delete(experiment)
            if fault == "historical":
                snapshot = dict(child.draft_snapshot_json)
                snapshot.pop("schema_version")
                snapshot.pop("pose_training_dataset_manifest_sha256")
                child.draft_snapshot_json = snapshot
                manifest = dict(child.artifact_manifest_json)
                for key in (
                    "result_checkpoint_path",
                    "result_checkpoint_sha256",
                    "best_checkpoint_sha256",
                ):
                    manifest.pop(key, None)
                manifest["artifacts"] = [
                    {key: value for key, value in artifact.items() if key != "sha256"}
                    for artifact in manifest["artifacts"]
                ]
                child.artifact_manifest_json = manifest
        elif fault == "provider":
            experiment.provider_id = "unrelated-provider"
        elif fault == "artifact":
            experiment.artifact_manifest_json = {
                **experiment.artifact_manifest_json,
                "best_checkpoint_sha256": "0" * 64,
            }
        elif fault == "metrics":
            experiment.summary_metrics_json = {**experiment.summary_metrics_json, "train_loss": -1}
        session.commit()

    if prior_checkpoint is not None:
        assert prior_checkpoint != original_checkpoint
        checkpoint.write_bytes(prior_checkpoint)
        denied = client.post(url + "/models/register-from-run", json={"training_run_id": child_id})
        assert denied.status_code == 400, denied.text
        assert "checkpoint checksum changed after completion" in denied.json()["detail"]
    retry = client.post(f"/api/v1/jobs/{job_id}/retry")
    assert retry.status_code == 200, retry.text
    processed = process_workflow_run_job(app.state.settings, factory, job_id)
    detail = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    training = [
        row["payload_json"] for row in detail["artifacts"] if row["data_type"] == "training_result"
    ]
    with factory() as session:
        expected_runs = {child_id, prior_training_id} if prior_training_id else {child_id}
        assert set(session.scalars(select(TrainingRun.id))) == expected_runs
        child_job = session.get(Job, child_job_id)
        assert child_job is not None and child_job.status == "succeeded"
    assert checkpoint.read_bytes() == (prior_checkpoint or original_checkpoint)
    if fault in {"intact", "historical"}:
        assert processed and detail["run"]["status"] == "succeeded", detail["run"]
        assert len(training) == 1
        assert training[0]["experiment_id"] == (experiment_id if fault == "intact" else None)
        assert training[0]["result_checkpoint_sha256"] == sha
        if fault == "historical":
            assert "result_checkpoint_sha256" not in training[0]["artifact_manifest"]
    else:
        expected = {
            "missing": "experiment registry record is missing",
            "checkpoint": "checkpoint checksum changed after completion",
        }.get(fault, "experiment provenance changed")
        assert not processed, {
            "run": detail["run"]["status"],
            "completed_checkpoint_sha256": sha,
            "replacement_checkpoint_sha256": hashlib.sha256(prior_checkpoint).hexdigest()
            if prior_checkpoint is not None
            else None,
            "published_checkpoint_sha256": [row["result_checkpoint_sha256"] for row in training],
        }
        assert detail["run"]["status"] == "failed" and expected in detail["run"]["error_message"]
        assert training == []
    if fault == "checkpoint":
        checkpoint.write_bytes(original_checkpoint)
        assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 200
        assert process_workflow_run_job(app.state.settings, factory, job_id)
        recovered = client.get(f"/api/v1/workflow-runs/{run_id}").json()
        output = next(
            row["payload_json"]
            for row in recovered["artifacts"]
            if row["data_type"] == "training_result"
        )
        assert output["training_run_id"] == child_id
        assert output["result_checkpoint_sha256"] == sha
        registered = client.post(
            url + "/models/register-from-run", json={"training_run_id": child_id}
        )
        assert registered.status_code == 200, registered.text
        assert registered.json()["sha256"] == sha


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("REEFPOSE_RUN_GPU_TESTS") != "1",
    reason="Set REEFPOSE_RUN_GPU_TESTS=1 for the explicit RTX validation run",
)
def test_native_reefpose_cuda_workflow_registration_and_inference(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert torch.cuda.is_available()
    monkeypatch.setattr(
        PoseTrainingExportService,
        "_extract_exact_frames",
        staticmethod(_synthetic_exact_frames),
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()

    with app.state.session_factory() as session:
        trained = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": project["id"],
                "dataset_id": dataset["id"],
                "manifest_sha256": dataset["manifest_sha256"],
            },
            parameters={
                "provider_id": "reefpose",
                "architecture": "reefpose-s",
                "device": "cuda",
                "precision": "amp",
                "random_seed": 71,
                "training_config": {
                    "epochs": 1,
                    "batch": 1,
                    "input_height": 64,
                    "input_width": 64,
                    "base_channels": 4,
                    "fpn_channels": 8,
                    "workers": 0,
                },
            },
        )
        registered = SemanticModelService(session, test_settings).register_model_from_run(
            str(project["id"]),
            RegisterModelFromRunRequest(
                training_run_id=str(trained["training_run_id"]),
                display_name="Phase 2A RTX 3090 validation",
            ),
        )

    image_path = tmp_path / "synthetic-gpu-animal.png"
    Image.new("RGB", (96, 64), color=(24, 72, 120)).save(image_path)
    checkpoint = resolve_managed_project_path(test_settings, registered.managed_path)
    provider = ReefPoseRegistrationProvider()
    provider.load_model(checkpoint, "cuda")
    predictions = provider.predict(
        image_path,
        DetectionSettings(confidence_threshold=0.0, iou_threshold=0.5, device="cuda"),
    )
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    peak_memory = torch.cuda.max_memory_allocated()
    provider.unload_model()

    assert len(predictions) == 1
    assert len(predictions[0].keypoints or ()) == 2
    evidence = {
        "schema_version": "reefpose-phase2a-gpu-validation-0001",
        "scientific_accuracy_validated": False,
        "device": torch.cuda.get_device_name(0),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "training_run_id": trained["training_run_id"],
        "training_job_id": trained["training_job_id"],
        "model_id": registered.id,
        "checkpoint_sha256": trained["result_checkpoint_sha256"],
        "training_metrics": trained["metrics"],
        "workflow_seconds": elapsed,
        "peak_gpu_memory_bytes": peak_memory,
        "inference_detection_count": len(predictions),
        "inference_keypoint_count": len(predictions[0].keypoints or ()),
        "source_image_size": [96, 64],
    }
    print("REEFPOSE_PHASE2A_GPU_EVIDENCE=" + json.dumps(evidence, sort_keys=True))
