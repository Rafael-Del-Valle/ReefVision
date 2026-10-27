from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseLandmarkSchema,
    PoseLandmarkSchemaRevision,
    PoseModelSchemaBinding,
    PoseTrainingDataset,
    Project,
    TrainingRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.pose_training import (
    materialize_pose_training_exports,
)
from reefvision.jobs.training import (
    _complete_training_run,
)
from reefvision.services.workflow_pose_training import (
    create_pose_workflow_training_result,
)
from reefvision.services.workflow_runtime_adapters import (
    RUNTIME_ADAPTER_NODE_TYPES,
)
from reefvision.storage.projects import (
    resolve_managed_project_path,
)
from reefvision.tests.test_annotations import create_project
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
            "0 0.5 0.5 0.5 0.5 0.5 0.5 2\n",
        )
        archive.writestr(
            "data.yaml",
            (
                "path: .\n"
                "train: images/train\n"
                "val: images/train\n"
                "kpt_shape: [1, 3]\n"
                "names:\n"
                '  0: "animal"\n'
            ),
        )

    return stream.getvalue()


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

    # The real persisted run must pin its model bytes, not just calculate a
    # new digest each time Workflow Builder retries a completed node.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        assert (
            persisted.artifact_manifest_json["result_checkpoint_sha256"]
            == result["result_checkpoint_sha256"]
        )
        assert (
            persisted.artifact_manifest_json["result_checkpoint_path"]
            == result["result_checkpoint_path"]
        )

    def retry_completed_node() -> dict[str, Any]:
        with app.state.session_factory() as session:
            return create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload={
                    "project_id": project["id"],
                    "dataset_id": dataset["id"],
                    "manifest_sha256": dataset["manifest_sha256"],
                },
                initial_model_payload={"model_id": model_id},
                parameters={
                    "run_name": "phase10-pose-retrain",
                    "device": "cpu",
                    "precision": "fp32",
                    "random_seed": 31,
                    "training_config": {"epochs": 1},
                },
                workflow_run_id="phase10-workflow",
                workflow_node_run_id="phase10-pose-training-node",
                processor=_fake_pose_processor,
            )

    reused = retry_completed_node()
    assert reused["training_run_id"] == result["training_run_id"]
    assert reused["result_checkpoint_sha256"] == result["result_checkpoint_sha256"]

    # The recovered child job must still belong to this project's saved run.
    # Exercise a real persisted job against a second valid project, then
    # restore it to verify that the original frozen result remains reusable.
    foreign_project = create_project(client, "Phase 10 foreign job ownership")
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None and persisted.job_id is not None
        child_job = session.get(Job, persisted.job_id)
        assert child_job is not None
        original_project_id = child_job.project_id
        child_job.project_id = str(foreign_project["id"])
        session.commit()

    with pytest.raises(ValidationError, match="job project ownership changed"):
        retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None and persisted.job_id is not None
        child_job = session.get(Job, persisted.job_id)
        assert child_job is not None
        child_job.project_id = original_project_id
        session.commit()

    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # A real API-frozen, scientist-reviewed pose dataset underlies this run.
    # Corrupt only the persisted child-run snapshot and verify that replay
    # cannot silently return its checkpoint with falsified dataset lineage.
    for field, corrupt_value in (
        ("pose_training_dataset_manifest_sha256", "0" * 64),
        ("pose_schema_id", "corrupted-schema-id"),
        ("split_manifest", {"schema_version": "tampered"}),
    ):
        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            original_snapshot = dict(persisted.draft_snapshot_json or {})
            persisted.draft_snapshot_json = {
                **original_snapshot,
                field: corrupt_value,
            }
            session.commit()

        with pytest.raises(ValidationError, match="frozen provenance changed"):
            retry_completed_node()

        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            persisted.draft_snapshot_json = original_snapshot
            session.commit()

        assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    checkpoint = resolve_managed_project_path(test_settings, result["result_checkpoint_path"])
    checkpoint.write_bytes(b"changed-after-scientist-verified-pose-training")
    with pytest.raises(ValidationError, match="checkpoint checksum changed"):
        retry_completed_node()


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


def test_pose_validation_rejects_second_verified_round_from_same_video(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Freeze two independently reviewed rounds via the real API, but reuse
    # the same source video. Separate dataset IDs cannot prevent video leakage.
    project, training = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, str(training["id"]))
        assert frozen is not None
        item = frozen.manifest_json["items"][0]
        video_id = item["video_id"]
        track_id = item["video_track_id"]

    created = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json={
            "name": "Independent review, same source video",
            "video_id": video_id,
            "track_ids": [track_id],
            "selection_unit": "frame",
            "requested_size": 1,
            "minimum_frame_spacing": 1,
        },
    )
    assert created.status_code == 201, created.text
    round_id = created.json()["id"]
    candidate_response = client.get(f"/api/v1/pose-active-learning-rounds/{round_id}/candidates")
    assert candidate_response.status_code == 200, candidate_response.text
    candidate_id = candidate_response.json()[0]["id"]
    reviewed = client.put(
        f"/api/v1/pose-active-learning-candidates/{candidate_id}/review",
        json={"action": "verify", "reviewed_by": "scientist"},
    )
    assert reviewed.status_code == 200, reviewed.text
    frozen_validation = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_id}/training-dataset",
        json={"name": "Validation from reused source video", "created_by": "scientist"},
    )
    assert frozen_validation.status_code == 201, frozen_validation.text
    validation = frozen_validation.json()
    assert validation["id"] != training["id"]

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="independent source videos"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": project["id"],
                "dataset_id": training["id"],
                "manifest_sha256": training["manifest_sha256"],
            },
            validation_dataset_payload={
                "project_id": project["id"],
                "dataset_id": validation["id"],
                "manifest_sha256": validation["manifest_sha256"],
            },
            parameters={"training_config": {"epochs": 1}},
            processor=_fake_pose_processor,
        )


def test_pose_seed_rejects_distinct_schema_identity_with_matching_content(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The dataset is frozen from a real scientist-verified active-learning round.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    model_id = _seed_model(app, project, dataset)

    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, str(dataset["id"]))
        assert frozen is not None
        source_revision = session.scalar(
            select(PoseLandmarkSchemaRevision).where(
                PoseLandmarkSchemaRevision.schema_id == frozen.pose_schema_id,
                PoseLandmarkSchemaRevision.revision == frozen.pose_schema_revision,
            )
        )
        assert source_revision is not None

        # Two project schemas can describe identical landmarks yet represent
        # different scientist-managed identities and review lineage.
        other_schema = PoseLandmarkSchema(
            project_id=str(project["id"]),
            name="Independent schema with identical landmarks",
        )
        session.add(other_schema)
        session.flush()
        session.add(
            PoseLandmarkSchemaRevision(
                schema_id=other_schema.id,
                revision=1,
                schema_version=source_revision.schema_version,
                groups_json=source_revision.groups_json,
                expanded_labels_json=source_revision.expanded_labels_json,
                keypoint_count=source_revision.keypoint_count,
                allows_repeated_labels=source_revision.allows_repeated_labels,
                content_hash=source_revision.content_hash,
            )
        )
        binding = session.get(PoseModelSchemaBinding, model_id)
        assert binding is not None
        binding.schema_id = other_schema.id
        binding.schema_revision = 1
        session.commit()

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="schema identity does not match"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": project["id"],
                "dataset_id": dataset["id"],
                "manifest_sha256": dataset["manifest_sha256"],
            },
            initial_model_payload={"model_id": model_id},
            parameters={"training_config": {"epochs": 1}},
            processor=_fake_pose_processor,
        )
