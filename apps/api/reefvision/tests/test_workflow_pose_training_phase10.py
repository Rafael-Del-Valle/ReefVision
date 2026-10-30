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
    PoseTrainingDatasetItem,
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
    execute_pose_training_dataset_adapter,
)
from reefvision.services.workflow_runtime_adapters import (
    RUNTIME_ADAPTER_NODE_TYPES,
)
from reefvision.storage.projects import (
    resolve_managed_project_path,
)
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_active_learning_phase8 import (
    _build_temporal,
    _first_class,
    _track,
)
from reefvision.tests.test_pose_training_datasets_phase9 import (
    _persist_test_pose_schema,
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


def test_pose_workflow_replay_checks_secondary_checkpoint_bytes(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Freeze scientist-reviewed pose truth through the real API, then exercise
    # persisted checkpoint provenance with a lightweight training worker.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    secondary_bytes = b"phase10-secondary-pose-checkpoint"

    def processor_with_secondary_checkpoint(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as session:
            job = session.get(Job, job_id)
            assert job is not None
            run = session.get(TrainingRun, str(job.request_json["training_run_id"]))
            assert run is not None and run.result_checkpoint_path is not None
            assert run.result_checkpoint_path.endswith("/best.pt")
            last_path = run.result_checkpoint_path.removesuffix("best.pt") + "last.pt"
            resolve_managed_project_path(settings, last_path).write_bytes(secondary_bytes)
            run.artifact_manifest_json = {
                **dict(run.artifact_manifest_json or {}),
                "last_checkpoint_path": last_path,
            }
            session.commit()
        return True

    def execute(processor: Any) -> dict[str, Any]:
        with app.state.session_factory() as session:
            return create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=payload,
                parameters={"device": "cpu", "training_config": {"epochs": 1}},
                workflow_run_id="secondary-checkpoint-workflow",
                workflow_node_run_id="secondary-checkpoint-node",
                processor=processor,
            )

    result = execute(processor_with_secondary_checkpoint)
    with app.state.session_factory() as session:
        run = session.get(TrainingRun, result["training_run_id"])
        assert run is not None
        manifest = dict(run.artifact_manifest_json or {})
    assert manifest["best_checkpoint_sha256"] == result["result_checkpoint_sha256"]
    assert manifest["last_checkpoint_sha256"] == hashlib.sha256(secondary_bytes).hexdigest()

    last_checkpoint = resolve_managed_project_path(
        test_settings, str(manifest["last_checkpoint_path"])
    )
    try:
        last_checkpoint.write_bytes(b"altered-secondary-checkpoint")
        with pytest.raises(ValidationError, match="checkpoint artifact checksum changed"):
            execute(processor_with_secondary_checkpoint)
    finally:
        last_checkpoint.write_bytes(secondary_bytes)

    replayed = execute(processor_with_secondary_checkpoint)
    assert replayed["training_run_id"] == result["training_run_id"]
    with app.state.session_factory() as session:
        assert session.scalars(select(TrainingRun.id)).all() == [result["training_run_id"]]


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
        seed = session.get(ModelRegistration, model_id)
        assert seed is not None
        seed_sha256 = seed.sha256
        # These are the fields emitted by the real registered_model_source node.
        seed_reference = {
            "project_id": str(project["id"]),
            "model_id": model_id,
            "model_sha256": seed.sha256,
            "purpose": seed.purpose,
            "task": seed.task,
            "provider_name": seed.provider_name,
            "provider_version": seed.provider_version,
        }

    # A saved model-reference artifact pins both project ownership and
    # registered checkpoint bytes. Neither assertion may be silently ignored
    # even when the model ID itself still resolves to a valid local model.
    for seed_artifact, expected_error in (
        (
            {"model_id": model_id, "project_id": "unrelated-project"},
            "seed artifact project lineage changed",
        ),
        (
            {"model_id": model_id, "sha256": "0" * 64},
            "seed artifact checksum changed",
        ),
        (
            {"model_id": model_id, "source_model_sha256": "0" * 64},
            "seed artifact checksum changed",
        ),
        (
            {"model_id": model_id, "model_sha256": "0" * 64},
            "seed artifact checksum changed",
        ),
        (
            {"model_id": model_id, "purpose": "classifier"},
            "seed artifact metadata changed",
        ),
        (
            {"model_id": model_id, "task": "detect"},
            "seed artifact metadata changed",
        ),
        (
            {"model_id": model_id, "provider_name": "other-provider"},
            "seed artifact metadata changed",
        ),
        (
            {"model_id": model_id, "provider_version": "unexpected-version"},
            "seed artifact metadata changed",
        ),
    ):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match=expected_error),
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
                initial_model_payload=seed_artifact,
                parameters={"device": "cpu", "training_config": {"epochs": 1}},
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert session.scalars(select(TrainingRun.id)).all() == []

    # Reuse the actual API-frozen scientist-reviewed dataset. A partial or
    # blank saved-workflow identity must never launch an untraceable training
    # job or bypass node-level replay protection.
    for saved_run_id, saved_node_id in (
        ("saved-pose-run", None),
        (None, "saved-pose-node"),
        (" ", "saved-pose-node"),
        ("saved-pose-run", " "),
    ):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="workflow lineage requires both non-blank IDs"),
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
                parameters={"device": "cpu", "training_config": {"epochs": 1}},
                workflow_run_id=saved_run_id,
                workflow_node_run_id=saved_node_id,
                processor=_fake_pose_processor,
            )
    with app.state.session_factory() as session:
        assert session.scalars(select(TrainingRun.id)).all() == []

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
            initial_model_payload={**seed_reference, "sha256": seed_sha256},
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

    def retry_completed_node(
        *, run_name: str = "phase10-pose-retrain", notes: Any = None
    ) -> dict[str, Any]:
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
                    "run_name": run_name,
                    "notes": notes,
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

    # A persisted manifest must not advertise an optional checkpoint that
    # disappeared after training. The selected best.pt remains intact here,
    # so its valid digest alone must not authorize a missing last.pt artifact.
    missing_last = str(result["result_checkpoint_path"]).removesuffix("best.pt") + "last.pt"
    assert missing_last != result["result_checkpoint_path"]
    assert not resolve_managed_project_path(test_settings, missing_last).is_file()
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        original_manifest = dict(persisted.artifact_manifest_json or {})
        persisted.artifact_manifest_json = {
            **original_manifest,
            "last_checkpoint_path": missing_last,
        }
        session.commit()

    with pytest.raises(ValidationError, match="checkpoint artifact path changed or is missing"):
        retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        persisted.artifact_manifest_json = original_manifest
        session.commit()

    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # Changing the saved node's requested run name cannot relabel or reuse
    # an already completed scientist-verified training result.
    with pytest.raises(ValidationError, match="configuration changed"):
        retry_completed_node(run_name="different-scientific-run")

    # A saved workflow replay must not reuse weights after its experiment
    # notes change, even if all frozen training inputs remain identical.
    with pytest.raises(ValidationError, match="configuration changed"):
        retry_completed_node(notes="different-experimental-context")

    # Explicit non-string notes previously became None or coerced text,
    # allowing a saved workflow to silently reuse an unrelated checkpoint.
    for invalid_notes in (False, 0, [], {}, 2.5):
        with pytest.raises(ValidationError, match="notes must be a string or null"):
            retry_completed_node(notes=invalid_notes)

    with app.state.session_factory() as session:
        matching_runs = session.scalars(
            select(TrainingRun.id).where(TrainingRun.project_id == str(project["id"]))
        ).all()
        assert matching_runs == [result["training_run_id"]]

    # Simulate a worker retry while this same persisted child job is still
    # training. Replaying the saved node must not queue a second GPU job.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None and persisted.job_id is not None
        child_job = session.get(Job, persisted.job_id)
        assert child_job is not None
        persisted.status = "training"
        child_job.status = "running"
        session.commit()

    with pytest.raises(ValidationError, match="already has an active child run"):
        retry_completed_node()

    with app.state.session_factory() as session:
        matching_runs = session.scalars(
            select(TrainingRun.id).where(TrainingRun.project_id == str(project["id"]))
        ).all()
        assert matching_runs == [result["training_run_id"]]
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None and persisted.job_id is not None
        child_job = session.get(Job, persisted.job_id)
        assert child_job is not None
        persisted.status = "completed"
        child_job.status = "succeeded"
        session.commit()

    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

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

    # A successful child job must remain linked to the exact saved workflow
    # node, not merely to a job with a matching project and success status.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None and persisted.job_id is not None
        child_job = session.get(Job, persisted.job_id)
        assert child_job is not None
        original_request = dict(child_job.request_json or {})
        child_job.request_json = {
            **original_request,
            "workflow_node_run_id": "unrelated-node",
        }
        session.commit()

    with pytest.raises(ValidationError, match="child job lineage changed"):
        retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None and persisted.job_id is not None
        child_job = session.get(Job, persisted.job_id)
        assert child_job is not None
        child_job.request_json = original_request
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

    # The real registered seed's frozen identity must not be silently
    # relabeled during completed-node replay, even with intact model bytes.
    for field, corrupt_value in (
        ("initialization_mode", "random"),
        ("seed_model_id", "substituted-seed-model"),
        ("seed_model_sha256", "0" * 64),
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

        with pytest.raises(ValidationError, match="seed provenance changed"):
            retry_completed_node()

        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            persisted.draft_snapshot_json = original_snapshot
            session.commit()

        assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # Altering or removing the snapshot schema marker must not downgrade a
    # current scientist-verified run into unchecked legacy checkpoint replay.
    for version, expected_error in (
        ("pose-workflow-training-snapshot-9999", "snapshot schema changed"),
        (None, "checkpoint provenance is missing"),
    ):
        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            original_snapshot = dict(persisted.draft_snapshot_json or {})
            original_manifest = dict(persisted.artifact_manifest_json or {})
            tampered_snapshot = dict(original_snapshot)
            tampered_manifest = dict(original_manifest)
            if version is None:
                tampered_snapshot.pop("schema_version")
                tampered_manifest.pop("result_checkpoint_sha256")
            else:
                tampered_snapshot["schema_version"] = version
            persisted.draft_snapshot_json = tampered_snapshot
            persisted.artifact_manifest_json = tampered_manifest
            session.commit()

        with pytest.raises(ValidationError, match=expected_error):
            retry_completed_node()

        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            persisted.draft_snapshot_json = original_snapshot
            persisted.artifact_manifest_json = original_manifest
            session.commit()

        assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # The persisted training run must agree with the scientist-frozen dataset
    # and the recorded validation policy, not just its workflow snapshot.
    for field, corrupt_value, error in (
        ("dataset_manifest_sha256", "0" * 64, "dataset checksum changed"),
        ("initial_checkpoint_source", "scratch", "seed model changed"),
        (
            "resolved_model_asset_id",
            "builtin_architecture:yolo11n-pose.yaml",
            "seed model changed",
        ),
        ("provider_id", "corrupted-provider", "configuration changed"),
        ("run_name", "corrupted-run-name", "configuration changed"),
        ("resource_limits_json", {"max_gpu_memory_mb": 1024}, "configuration changed"),
        (
            "evaluation_config_json",
            {"validation_mode": "separate_frozen_pose_dataset"},
            "validation mode changed",
        ),
    ):
        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            original_value = getattr(persisted, field)
            setattr(persisted, field, corrupt_value)
            session.commit()

        with pytest.raises(ValidationError, match=error):
            retry_completed_node()

        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            setattr(persisted, field, original_value)
            session.commit()

        assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # The artifact manifest is itself returned to downstream Workflow Builder
    # nodes; a corrupted copy must not be mistaken for frozen provenance.
    for field, corrupt_value in (
        ("pose_training_dataset_id", "substituted-frozen-dataset"),
        ("pose_split_manifest_sha256", "0" * 64),
        ("pose_split_manifest", {"schema_version": "tampered"}),
    ):
        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            original_manifest = dict(persisted.artifact_manifest_json or {})
            persisted.artifact_manifest_json = {
                **original_manifest,
                field: corrupt_value,
            }
            session.commit()

        with pytest.raises(ValidationError, match="artifact provenance changed"):
            retry_completed_node()

        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            persisted.artifact_manifest_json = original_manifest
            session.commit()

        assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # Removing the stored digest or path must not bypass checkpoint integrity
    # for this newly completed, scientist-verified workflow training run.
    for missing_field in ("result_checkpoint_sha256", "result_checkpoint_path"):
        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            original_manifest = dict(persisted.artifact_manifest_json or {})
            tampered_manifest = dict(original_manifest)
            tampered_manifest.pop(missing_field)
            persisted.artifact_manifest_json = tampered_manifest
            session.commit()

        with pytest.raises(ValidationError, match="checkpoint provenance is missing"):
            retry_completed_node()

        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            persisted.artifact_manifest_json = original_manifest
            session.commit()

        assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    checkpoint = resolve_managed_project_path(test_settings, result["result_checkpoint_path"])
    checkpoint.write_bytes(b"changed-after-scientist-verified-pose-training")
    with pytest.raises(ValidationError, match="checkpoint checksum changed"):
        retry_completed_node()


def test_pose_workflow_rejects_explicitly_invalid_frozen_manifest_digest(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use a real scientist-reviewed, API-frozen pose dataset. A persisted
    # Workflow Builder artifact cannot bypass its checksum by supplying an
    # explicitly false or empty digest.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    parameters = {
        "initialization_mode": "random",
        "architecture": "yolo11n-pose.yaml",
        "training_config": {"epochs": 1},
    }

    for invalid_digest in (False, 0, "", None, "0" * 64):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="manifest no longer matches persisted truth"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload={**payload, "manifest_sha256": invalid_digest},
                parameters=parameters,
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(TrainingRun.id).where(TrainingRun.project_id == str(project["id"]))
            )
            is None
        )
        valid = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=payload,
            parameters=parameters,
            processor=_fake_pose_processor,
        )
    assert valid["pose_training_dataset_id"] == dataset["id"]


def test_pose_workflow_preserves_api_frozen_source_lineage_in_artifacts(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Produce the actual Workflow Builder dataset artifact from scientist-reviewed
    # truth, then check that downstream training enforces its source lineage.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    project_id = str(project["id"])
    with app.state.session_factory() as session:
        produced = execute_pose_training_dataset_adapter(
            session,
            test_settings,
            project_id,
            {
                "dataset_id": str(dataset["id"]),
                "manifest_sha256": str(dataset["manifest_sha256"]),
            },
            {},
        )
    payload = produced[0]["payload"]
    source_fields = (
        "source_round_id",
        "source_selection_sha256",
        "source_retraining_manifest_sha256",
    )
    assert all(field in payload for field in source_fields)
    parameters = {
        "initialization_mode": "random",
        "architecture": "yolo11n-pose.yaml",
        "training_config": {"epochs": 1},
    }

    # A persisted artifact that explicitly asserts null/false/foreign project
    # ownership must not be accepted as if its project_id were omitted.
    for invalid_project_id in (None, False, "foreign-project"):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="dataset belongs to another project"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=project_id,
                dataset_payload={**payload, "project_id": invalid_project_id},
                parameters=parameters,
                processor=_fake_pose_processor,
            )

    for field in source_fields:
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="source lineage no longer matches frozen truth"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=project_id,
                dataset_payload={**payload, field: f"tampered-{field}"},
                parameters=parameters,
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert (
            session.scalar(select(TrainingRun.id).where(TrainingRun.project_id == project_id))
            is None
        )
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters=parameters,
            processor=_fake_pose_processor,
        )
    assert result["pose_training_dataset_id"] == dataset["id"]


def test_pose_workflow_rejects_falsy_non_object_resource_limits_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Freeze real scientist-reviewed pose annotations through the API.
    # Invalid resource limits must fail before a training job is persisted.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    # An explicitly null policy must not silently remove GPU/resource limits.
    for invalid_limits in (None, [], "", 0, False):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="resource_limits must be an object"),
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
                parameters={
                    "initialization_mode": "random",
                    "architecture": "yolo11n-pose.yaml",
                    "training_config": {"epochs": 1},
                    "resource_limits": invalid_limits,
                },
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(TrainingRun.id).where(TrainingRun.project_id == str(project["id"]))
            )
            is None
        )


def test_pose_workflow_rejects_null_training_config_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A persisted graph's explicit null cannot silently become the defaults.
    # The input dataset is frozen from scientist-reviewed annotations via API.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="training_config must be an object"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={"training_config": None},
            processor=_fake_pose_processor,
        )

    with app.state.session_factory() as session:
        assert session.scalar(select(TrainingRun.id)) is None
        # Truly omitted configuration still receives the supported defaults.
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={"device": "cpu"},
            processor=_fake_pose_processor,
        )
    assert result["pose_training_dataset_id"] == dataset["id"]


def test_pose_workflow_rejects_lossy_run_names_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The dataset was frozen through the scientist-review API, not fabricated.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    parameters = {
        "initialization_mode": "random",
        "architecture": "yolo11n-pose.yaml",
        "training_config": {"epochs": 1},
    }
    for invalid_name, expected_error in (
        (False, "run_name must be a string"),
        (0, "run_name must be a string"),
        ([], "run_name must be a string"),
        ({}, "run_name must be a string"),
        ("", "run_name cannot be blank"),
        ("   ", "run_name cannot be blank"),
    ):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match=expected_error),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={**parameters, "run_name": invalid_name},
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(TrainingRun.id).where(TrainingRun.project_id == str(project["id"]))
            )
            is None
        )
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters=parameters,
            processor=_fake_pose_processor,
        )
    assert result["run_name"] == "workflow-pose-retrain"


def test_pose_workflow_rejects_lossy_device_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use a scientist-reviewed pose dataset frozen through the real API.
    # A non-string or empty device must fail before a training job is queued.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    parameters = {
        "initialization_mode": "random",
        "architecture": "yolo11n-pose.yaml",
        "training_config": {"epochs": 1},
    }
    for invalid_device in (False, 0, None, [], {}, "", "   "):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="device must be a non-blank string"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={**parameters, "device": invalid_device},
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(TrainingRun.id).where(TrainingRun.project_id == str(project["id"]))
            )
            is None
        )
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={**parameters, "device": " cpu "},
            processor=_fake_pose_processor,
        )
    assert result["device"] == "cpu"


def test_pose_workflow_rejects_lossy_random_seeds_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use an API-frozen scientist-reviewed dataset, not a synthetic manifest.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    parameters = {
        "initialization_mode": "random",
        "architecture": "yolo11n-pose.yaml",
        "training_config": {"epochs": 1},
    }
    # Unicode superscript digits cannot be parsed as integers; huge seeds
    # must not overflow the persisted signed 64-bit training-run column.
    for invalid_seed in (True, False, -1, 2.5, "2.5", "invalid", "²", 2**63, "9" * 5000):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="random_seed must be a non-negative integer"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={**parameters, "random_seed": invalid_seed},
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(TrainingRun.id).where(TrainingRun.project_id == str(project["id"]))
            )
            is None
        )

    # Zero is a legitimate reproducible seed, not a missing configuration.
    with app.state.session_factory() as session:
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={**parameters, "random_seed": 0},
            processor=_fake_pose_processor,
        )
    assert result["random_seed"] == 0

    # The worker accepts a seed in Ultralytics training_config as well as
    # ReefVision's top-level random_seed. A saved scientific run must never
    # advertise one seed while its training arguments execute with another.
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match=r"training_config\.seed must match random_seed"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={
                **parameters,
                "random_seed": 8,
                "training_config": {"epochs": 1, "seed": 7},
            },
            processor=_fake_pose_processor,
        )

    # A legacy graph that specifies only training_config.seed must persist
    # the effective worker seed in the TrainingRun and downstream artifact.
    with app.state.session_factory() as session:
        configured_result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={**parameters, "training_config": {"epochs": 1, "seed": 7}},
            processor=_fake_pose_processor,
        )
    assert configured_result["random_seed"] == 7
    with app.state.session_factory() as session:
        saved_run = session.get(TrainingRun, configured_result["training_run_id"])
        assert saved_run is not None
        assert saved_run.random_seed == 7
        assert saved_run.training_config_json["seed"] == 7


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

    # A persisted Workflow Builder parameter must be an actual boolean:
    # "false" is truthy in Python, while 0/[] previously became False.
    for invalid_flag in ("false", "true", 0, 1, []):
        with (
            app.state.session_factory() as session,
            pytest.raises(
                ValidationError,
                match="require_validation_dataset must be a boolean",
            ),
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
                parameters={
                    "require_validation_dataset": invalid_flag,
                    "training_config": {"epochs": 1},
                },
                processor=_fake_pose_processor,
            )

    # The saved node must not silently override a requested validation mode.
    # This dataset was frozen through the scientist-review API.
    for invalid_val in (True, "false", 0, None):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match=r"training_config\.val must match"),
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
                parameters={"training_config": {"epochs": 1, "val": invalid_val}},
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(TrainingRun.id).where(TrainingRun.project_id == str(project["id"]))
            )
            is None
        )

    # Explicit False remains valid and does not claim independent validation.
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
            initial_model_payload={"model_id": model_id},
            parameters={
                "require_validation_dataset": False,
                "training_config": {"epochs": 1, "val": False},
            },
            processor=_fake_pose_processor,
        )
    assert result["validation_mode"] == "none"


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


def test_pose_validation_rejects_distinct_schema_identity_with_matching_content(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Freeze two scientist-reviewed datasets from independent source videos.
    # Equal landmark definitions are not enough when their schema IDs differ.
    project, training = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)

    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={
            "file": (
                "independent-validation.mp4",
                io.BytesIO(b"independent-pose-validation-video"),
                "video/mp4",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    video_id = imported.json()["id"]
    track = _track(client, str(video_id), _first_class(project))
    _build_temporal(client, str(track["id"]))
    _persist_test_pose_schema(
        client,
        project_id=str(project["id"]),
        track_id=str(track["id"]),
    )

    created = client.post(
        f"/api/v1/projects/{project['id']}/pose-active-learning-rounds",
        json={
            "name": "Independent validation with distinct schema identity",
            "video_id": video_id,
            "track_ids": [track["id"]],
            "selection_unit": "frame",
            "requested_size": 1,
            "minimum_frame_spacing": 0,
        },
    )
    assert created.status_code == 201, created.text
    round_id = created.json()["id"]
    candidates = client.get(f"/api/v1/pose-active-learning-rounds/{round_id}/candidates")
    assert candidates.status_code == 200, candidates.text
    reviewed = client.put(
        f"/api/v1/pose-active-learning-candidates/{candidates.json()[0]['id']}/review",
        json={"action": "verify", "reviewed_by": "scientist"},
    )
    assert reviewed.status_code == 200, reviewed.text
    frozen = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_id}/training-dataset",
        json={"name": "Independent validation truth", "created_by": "scientist"},
    )
    assert frozen.status_code == 201, frozen.text
    validation = frozen.json()
    assert training["pose_schema_content_hash"] == validation["pose_schema_content_hash"]
    assert training["pose_schema_id"] != validation["pose_schema_id"]

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="same landmark schema identity and revision"),
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

    with app.state.session_factory() as session:
        assert session.scalar(select(TrainingRun.id)) is None


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


def test_pose_workflow_rejects_lossy_initialization_mode_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The dataset was frozen through scientist review, not a synthetic manifest.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    for invalid_mode in (None, False, 0, [], {}, ""):
        with (
            app.state.session_factory() as session,
            pytest.raises(
                ValidationError,
                match="initialization_mode must be random or registered_model",
            ),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={
                    "initialization_mode": invalid_mode,
                    "training_config": {"epochs": 1},
                },
                processor=_fake_pose_processor,
            )

    # Even with a seed artifact, False must not silently select registered_model.
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="initialization_mode must be"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            initial_model_payload={"model_id": "unused"},
            parameters={"initialization_mode": False},
            processor=_fake_pose_processor,
        )

    # A connected but empty seed-model artifact must not be interpreted as
    # an unconnected optional port and silently produce random-init science.
    for requested_parameters, expected_error in (
        (
            {"training_config": {"epochs": 1}},
            "Pose retraining requires a registered seed model",
        ),
        (
            {"initialization_mode": "random", "training_config": {"epochs": 1}},
            "Random initialization cannot use an initial model",
        ),
    ):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match=expected_error),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                initial_model_payload={},
                parameters=requested_parameters,
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert session.scalar(select(TrainingRun.id)) is None
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={"training_config": {"epochs": 1}},
            processor=_fake_pose_processor,
        )
    assert result["initialization_mode"] == "random"


def test_pose_workflow_rejects_lossy_architecture_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use scientist-reviewed, API-frozen truth: architecture is model provenance.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    parameters = {"training_config": {"epochs": 1}}

    for invalid_architecture in (None, False, 0, [], {}, "", "   ", 123):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="architecture must be a non-blank string"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={**parameters, "architecture": invalid_architecture},
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert session.scalar(select(TrainingRun.id)) is None
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters=parameters,
            processor=_fake_pose_processor,
        )

    assert result["architecture"] == "yolo11n-pose.yaml"


def test_pose_workflow_first_completion_rejects_substituted_child_job_lineage(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The training input is frozen through scientist review and the real API.
    # A completed worker must not relabel another workflow node's job before
    # the first result artifact is returned (not just on a later retry).
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    project_id = str(project["id"])
    payload = {
        "project_id": project_id,
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }

    def substituted_job_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as session:
            job = session.get(Job, job_id)
            assert job is not None
            job.request_json = {
                **dict(job.request_json),
                "workflow_node_run_id": "substituted-pose-node",
            }
            session.commit()
        return True

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="child job lineage changed"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="original-pose-node",
            processor=substituted_job_processor,
        )

    # A different successful job with copied request metadata must not
    # replace the exact child job queued by this saved workflow node.
    def substituted_job_identity_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as child_session:
            original = child_session.get(Job, job_id)
            assert original is not None
            replacement = Job(
                project_id=original.project_id,
                job_type="training",
                status="succeeded",
                progress_current=original.progress_current,
                progress_total=original.progress_total,
                request_json=dict(original.request_json),
                result_json=dict(original.result_json or {}),
            )
            child_session.add(replacement)
            child_session.flush()
            run = child_session.get(TrainingRun, str(original.request_json["training_run_id"]))
            assert run is not None
            run.job_id = replacement.id
            child_session.commit()
        return True

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="child job identity changed"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="substituted-job-identity-node",
            processor=substituted_job_identity_processor,
        )

    # The first result must also reject a worker-mutated frozen artifact
    # manifest, before a downstream node can consume the false schema lineage.
    def substituted_artifact_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as child_session:
            job = child_session.get(Job, job_id)
            assert job is not None
            run = child_session.get(TrainingRun, str(job.request_json["training_run_id"]))
            assert run is not None
            run.artifact_manifest_json = {
                **dict(run.artifact_manifest_json or {}),
                "pose_schema_id": "substituted-pose-schema",
            }
            child_session.commit()
        return True

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="artifact provenance changed"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="tampered-artifact-node",
            processor=substituted_artifact_processor,
        )

    # A worker may assert a checkpoint digest or path before completion.
    # Finalization must reject contradictory assertions rather than replacing
    # them with the current file identity and concealing provenance drift.
    for field, corrupted_value, expected_error in (
        ("result_checkpoint_sha256", "0" * 64, "worker checkpoint checksum changed"),
        (
            "result_checkpoint_path",
            "substituted-training-output/weights/best.pt",
            "worker checkpoint path changed",
        ),
        (
            "best_checkpoint_path",
            "substituted-training-output/weights/best.pt",
            "checkpoint artifact path changed",
        ),
        (
            "last_checkpoint_path",
            "substituted-training-output/weights/last.pt",
            "checkpoint artifact path changed",
        ),
    ):

        def conflicting_checkpoint_manifest_processor(
            settings: Settings,
            factory: sessionmaker[Session],
            job_id: str,
            *,
            manifest_field: str = field,
            manifest_value: str = corrupted_value,
        ) -> bool:
            assert _fake_pose_processor(settings, factory, job_id)
            with factory() as child_session:
                job = child_session.get(Job, job_id)
                assert job is not None
                run = child_session.get(TrainingRun, str(job.request_json["training_run_id"]))
                assert run is not None
                run.artifact_manifest_json = {
                    **dict(run.artifact_manifest_json or {}),
                    manifest_field: manifest_value,
                }
                child_session.commit()
            return True

        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match=expected_error),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=project_id,
                dataset_payload=payload,
                parameters={"training_config": {"epochs": 1}},
                workflow_run_id="saved-pose-run",
                workflow_node_run_id=f"conflicting-{field}-node",
                processor=conflicting_checkpoint_manifest_processor,
            )

    # A worker must not silently relabel the model architecture after training
    # and expose a checkpoint under different scientific configuration.
    def substituted_configuration_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as child_session:
            job = child_session.get(Job, job_id)
            assert job is not None
            run = child_session.get(TrainingRun, str(job.request_json["training_run_id"]))
            assert run is not None
            run.architecture = "yolo11x-pose.yaml"
            child_session.commit()
        return True

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="configuration changed"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="tampered-config-node",
            processor=substituted_configuration_processor,
        )

    # Frozen review evidence can be changed by a worker after preflight.
    # First completion must recheck the persisted items before publishing
    # the checkpoint, even when the dataset manifest itself was not changed.
    original_review: dict[str, Any] | None = None

    def tampered_frozen_truth_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        nonlocal original_review
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as child_session:
            frozen_item = child_session.scalar(
                select(PoseTrainingDatasetItem).where(
                    PoseTrainingDatasetItem.dataset_id == str(dataset["id"])
                )
            )
            assert frozen_item is not None
            original_review = dict(frozen_item.review_provenance_json)
            frozen_item.review_provenance_json = {
                **original_review,
                "action": "unverified_after_training",
            }
            child_session.commit()
        return True

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item fingerprints no longer match"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="tampered-frozen-truth-node",
            processor=tampered_frozen_truth_processor,
        )

    assert original_review is not None
    with app.state.session_factory() as session:
        frozen_item = session.scalar(
            select(PoseTrainingDatasetItem).where(
                PoseTrainingDatasetItem.dataset_id == str(dataset["id"])
            )
        )
        assert frozen_item is not None
        frozen_item.review_provenance_json = original_review
        session.commit()

    # A copied, checksummed checkpoint from a different output directory is
    # not the trained artifact of this node, even when its bytes are identical.
    def substituted_checkpoint_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as child_session:
            job = child_session.get(Job, job_id)
            assert job is not None
            run = child_session.get(TrainingRun, str(job.request_json["training_run_id"]))
            assert run is not None
            assert run.result_checkpoint_path is not None
            original = resolve_managed_project_path(settings, run.result_checkpoint_path)
            substituted_relative = (
                f"{project['storage_root']}/training/{run.id}/runs/other/weights/best.pt"
            )
            substituted = resolve_managed_project_path(settings, substituted_relative)
            substituted.parent.mkdir(parents=True, exist_ok=True)
            substituted.write_bytes(original.read_bytes())
            run.result_checkpoint_path = substituted_relative
            child_session.commit()
        return True

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="checkpoint belongs to another output"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="substituted-checkpoint-node",
            processor=substituted_checkpoint_processor,
        )

    # Training can finish after another writer changes the registered seed
    # checkpoint. First completion must reject that drift, not publish the
    # output as though it used the originally verified seed bytes.
    seed_model_id = _seed_model(app, project, dataset)
    with app.state.session_factory() as session:
        seed = session.get(ModelRegistration, seed_model_id)
        assert seed is not None
        seed_checkpoint = resolve_managed_project_path(test_settings, seed.managed_path)
    original_seed_bytes = seed_checkpoint.read_bytes()

    def changed_seed_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        seed_checkpoint.write_bytes(b"modified-after-pose-training-started")
        return True

    try:
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="seed checkpoint checksum changed"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=project_id,
                dataset_payload=payload,
                initial_model_payload={"model_id": seed_model_id},
                parameters={"training_config": {"epochs": 1}},
                workflow_run_id="saved-pose-run",
                workflow_node_run_id="changed-seed-checkpoint-node",
                processor=changed_seed_processor,
            )
    finally:
        seed_checkpoint.write_bytes(original_seed_bytes)

    # The legitimate saved-node lineage must still complete and expose a
    # checksummed checkpoint when its worker has not changed the child job.
    with app.state.session_factory() as session:
        valid = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="legitimate-pose-node",
            processor=_fake_pose_processor,
        )
    assert valid["workflow_node_run_id"] == "legitimate-pose-node"
    assert valid["pose_training_dataset_id"] == dataset["id"]
    assert len(valid["result_checkpoint_sha256"]) == 64
