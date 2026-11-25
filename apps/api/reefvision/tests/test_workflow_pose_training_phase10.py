from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ExperimentRecord,
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
    _materialized_pose_dataset_sha256,
    _prepare_clean_pose_training_output,
    _require_empty_pose_gpu_output,
    _require_trusted_pose_checkpoints,
    _resolve_unlinked_pose_run_path,
    _safe_extract_zip,
    _verified_pose_trainer_save_dir,
    _verify_postlaunch_pose_dataset,
    _verify_prelaunch_pose_dataset,
    materialize_pose_training_exports,
    process_pose_training_job,
)
from reefvision.jobs.training import (
    _complete_training_run,
)
from reefvision.services.workflow_pose_training import (
    _optional_payload,
    _reject_symlinked_training_path,
    _shared_pose_source_videos,
    _single_payload,
    create_pose_workflow_training_result,
    execute_pose_training_dataset_adapter,
)
from reefvision.services.workflow_runtime_adapters import (
    RUNTIME_ADAPTER_NODE_TYPES,
)
from reefvision.storage.datasets import (
    canonical_json_sha256,
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
            # The worker must persist the same artifact evidence in its
            # experiment record before Workflow Builder pins checkpoint hashes.
            experiment = session.scalar(
                select(ExperimentRecord).where(ExperimentRecord.training_run_id == run.id)
            )
            assert experiment is not None
            experiment.artifact_manifest_json = dict(run.artifact_manifest_json)
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

    # A real hard link preserves the secondary checkpoint digest but aliases
    # its bytes, so completed-node replay must reject it without deleting it.
    secondary_alias = last_checkpoint.parent / "last-hardlink-alias.pt"
    try:
        os.link(last_checkpoint, secondary_alias)
    except (OSError, NotImplementedError):
        pass  # Some filesystems do not support hard links.
    else:
        try:
            with pytest.raises(ValidationError, match="checkpoint artifact is hard-linked"):
                execute(processor_with_secondary_checkpoint)
        finally:
            secondary_alias.unlink()
        restored = execute(processor_with_secondary_checkpoint)
        assert restored["training_run_id"] == result["training_run_id"]

    # A current workflow must not become unchecked when a secondary checkpoint
    # digest is removed while its advertised file path remains intact.
    for digest_field in ("best_checkpoint_sha256", "last_checkpoint_sha256"):
        with app.state.session_factory() as session:
            run = session.get(TrainingRun, result["training_run_id"])
            assert run is not None
            original_manifest = dict(run.artifact_manifest_json or {})
            tampered_manifest = dict(original_manifest)
            tampered_manifest.pop(digest_field)
            run.artifact_manifest_json = tampered_manifest
            session.commit()

        with pytest.raises(ValidationError, match="checkpoint artifact checksum is missing"):
            execute(processor_with_secondary_checkpoint)

        with app.state.session_factory() as session:
            run = session.get(TrainingRun, result["training_run_id"])
            assert run is not None
            run.artifact_manifest_json = original_manifest
            session.commit()

        assert (
            execute(processor_with_secondary_checkpoint)["training_run_id"]
            == result["training_run_id"]
        )

    # A persisted digest without its corresponding checkpoint path is not
    # verifiable lineage. Removing the path must not downgrade replay checks.
    for path_field in ("best_checkpoint_path", "last_checkpoint_path"):
        with app.state.session_factory() as session:
            run = session.get(TrainingRun, result["training_run_id"])
            assert run is not None
            original_manifest = dict(run.artifact_manifest_json or {})
            tampered_manifest = dict(original_manifest)
            tampered_manifest.pop(path_field)
            run.artifact_manifest_json = tampered_manifest
            session.commit()

        with pytest.raises(ValidationError, match="checkpoint artifact path is missing"):
            execute(processor_with_secondary_checkpoint)

        with app.state.session_factory() as session:
            run = session.get(TrainingRun, result["training_run_id"])
            assert run is not None
            run.artifact_manifest_json = original_manifest
            session.commit()

        assert (
            execute(processor_with_secondary_checkpoint)["training_run_id"]
            == result["training_run_id"]
        )

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
                "reefvision_keypoint_names:\n"
                '  - "keypoint"\n'
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

    # The persisted training-run provenance must fingerprint the actual
    # materialized science input, including rewritten data.yaml and holdout
    # labels, not only the source ZIP bundle checksums.
    materialized_files = sorted(path for path in destination.rglob("*") if path.is_file())
    expected_digest = canonical_json_sha256(
        [
            {
                "path": path.relative_to(destination).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in materialized_files
        ]
    )
    assert independent["materialized_dataset_sha256"] == expected_digest
    assert independent["materialized_dataset_fingerprint_algorithm"] == "relative-posix-path-v1"
    replay = materialize_pose_training_exports(
        training_content=training,
        validation_content=validation,
        destination=tmp_path / "pose-dataset-replay",
    )
    assert replay["materialized_dataset_sha256"] == expected_digest

    no_validation_root = tmp_path / "pose-no-validation"

    exploratory = materialize_pose_training_exports(
        training_content=training,
        validation_content=None,
        destination=no_validation_root,
    )

    assert exploratory["validation_mode"] == "none"

    assert exploratory["validation_image_count"] == 0

    # Even independently frozen validation labels cannot be copied into a
    # training run whose class map interprets those label indices differently.
    mismatched = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(validation)) as original,
        zipfile.ZipFile(mismatched, "w", compression=zipfile.ZIP_DEFLATED) as modified,
    ):
        for member in original.namelist():
            content = original.read(member)
            if member == "data.yaml":
                content = content.replace(b'"animal"', b'"different-animal"')
            modified.writestr(member, content)

    mismatched_destination = tmp_path / "pose-incompatible-validation"
    with pytest.raises(ValidationError, match=r"incompatible data\.yaml"):
        materialize_pose_training_exports(
            training_content=training,
            validation_content=mismatched.getvalue(),
            destination=mismatched_destination,
        )
    # Rejected validation metadata must not strand a training dataset.
    # Retry the same saved-run destination using the reviewed frozen exports.
    assert not mismatched_destination.exists()
    corrected = materialize_pose_training_exports(
        training_content=training,
        validation_content=validation,
        destination=mismatched_destination,
    )
    assert corrected["validation_mode"] == "separate_frozen_pose_dataset"
    train_frame = mismatched_destination / "images/train/frame_00000001.png"
    holdout_frame = mismatched_destination / "images/val/frame_00000001.png"
    assert train_frame.read_bytes() == b"train"
    assert holdout_frame.read_bytes() == b"validation"


def test_pose_materialized_fingerprint_uses_portable_path_order(tmp_path: Path) -> None:
    # Mixed-case local artifacts sort differently on Windows, where Path
    # comparisons follow case-insensitive filename rules.
    root = tmp_path / "frozen-pose-input"
    reviewed_files = {
        "Z_review/pose.png": b"reviewed-upper",
        "a_review/pose.png": b"reviewed-lower",
    }
    for relative, content in reviewed_files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    expected = canonical_json_sha256(
        [
            {
                "path": relative,
                "sha256": hashlib.sha256(reviewed_files[relative]).hexdigest(),
            }
            for relative in sorted(reviewed_files)
        ]
    )
    assert _materialized_pose_dataset_sha256(root) == expected

    # Earlier Windows runs sorted Path objects case-insensitively. Preserve
    # those original scientific inputs without rewriting their saved digest.
    legacy_windows = canonical_json_sha256(
        [
            {
                "path": relative,
                "sha256": hashlib.sha256(reviewed_files[relative]).hexdigest(),
            }
            for relative in sorted(reviewed_files, key=str.casefold)
        ]
    )
    assert legacy_windows != expected
    _verify_prelaunch_pose_dataset(root, {"materialized_dataset_sha256": legacy_windows})

    # Newly versioned materializations cannot silently fall back to legacy
    # ordering. Nor can a historical manifest excuse edited frozen inputs.
    with pytest.raises(ValidationError, match="changed before GPU training"):
        _verify_prelaunch_pose_dataset(
            root,
            {
                "materialized_dataset_sha256": legacy_windows,
                "materialized_dataset_fingerprint_algorithm": "relative-posix-path-v1",
            },
        )
    (root / "Z_review" / "pose.png").write_bytes(b"altered-pose")
    with pytest.raises(ValidationError, match="changed before GPU training"):
        _verify_prelaunch_pose_dataset(root, {"materialized_dataset_sha256": legacy_windows})


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Real filesystem FIFOs require POSIX")
def test_pose_materialized_dataset_rejects_unhashed_filesystem_member(tmp_path: Path) -> None:
    # The frozen hash must not ignore a later non-file member in the training
    # tree: a real FIFO was previously silently omitted by is_file().
    root = tmp_path / "frozen-pose-input"
    root.mkdir()
    reviewed = root / "reviewed.png"
    reviewed.write_bytes(b"scientist-reviewed-frames")
    sealed_sha = _materialized_pose_dataset_sha256(root)

    os.mkfifo(root / "unreviewed-input")

    with pytest.raises(ValidationError, match="unsupported filesystem entry"):
        _verify_prelaunch_pose_dataset(
            root,
            {
                "materialized_dataset_sha256": sealed_sha,
                "materialized_dataset_fingerprint_algorithm": "relative-posix-path-v1",
            },
        )
    assert reviewed.read_bytes() == b"scientist-reviewed-frames"


@pytest.mark.parametrize("blocked_area", ("dataset", "validation_stage"))
def test_pose_materialization_preserves_prior_scientific_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocked_area: str,
) -> None:
    # Interrupted training/holdout exports can contain reviewed images or model
    # evidence. Never delete them when retrying a saved Workflow Builder run.
    destination = tmp_path / "pose-dataset"
    blocked_path = (
        destination if blocked_area == "dataset" else tmp_path / ".pose-dataset-validation"
    )
    blocked_path.mkdir(parents=True)
    previous = blocked_path / "prior-science.txt"
    previous.write_bytes(b"preserve-previous-run")

    def forbidden_cleanup(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Existing scientific pose data must not be deleted")

    monkeypatch.setattr(shutil, "rmtree", forbidden_cleanup)
    with pytest.raises(ValidationError, match="refusing to overwrite prior scientific data"):
        materialize_pose_training_exports(
            training_content=_pose_export_zip(b"new-training"),
            validation_content=(
                _pose_export_zip(b"new-validation") if blocked_area == "validation_stage" else None
            ),
            destination=destination,
        )

    assert previous.read_bytes() == b"preserve-previous-run"
    assert not (destination / "data.yaml").exists()
    assert not (destination / "images").exists()

    if blocked_area == "dataset":
        # The extractor must also reject a directory filled between the
        # materializer's occupancy check and the first archive write.
        with pytest.raises(ValidationError, match="refusing to overwrite prior scientific data"):
            _safe_extract_zip(_pose_export_zip(b"new-training"), destination)
        assert previous.read_bytes() == b"preserve-previous-run"
        assert not (destination / "data.yaml").exists()
        assert not (destination / "images").exists()


def test_pose_materialization_preserves_validation_stage_raced_after_precheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate another scientist's run claiming the holdout stage after our
    # initial existence check but before the archive extractor's exclusive mkdir.
    destination = tmp_path / "pose-dataset"
    staging = tmp_path / ".pose-dataset-validation"
    original_extract = _safe_extract_zip

    def competing_claim(content: bytes, target: Path) -> None:
        if target == staging:
            staging.mkdir()
            (staging / "prior-science.txt").write_bytes(b"other-reviewed-run")
        original_extract(content, target)

    monkeypatch.setattr("reefvision.jobs.pose_training._safe_extract_zip", competing_claim)
    with pytest.raises(ValidationError, match="refusing to overwrite prior scientific data"):
        materialize_pose_training_exports(
            training_content=_pose_export_zip(b"reviewed-training"),
            validation_content=_pose_export_zip(b"new-holdout"),
            destination=destination,
        )

    assert (staging / "prior-science.txt").read_bytes() == b"other-reviewed-run"
    assert not (staging / "data.yaml").exists()
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed-training"


def test_pose_materialization_rejects_failed_final_holdout_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A locked staging directory after a valid split export must fail the job,
    # not leave raw reviewed holdout frames while reporting success.
    destination = tmp_path / "pose-dataset"
    staging = tmp_path / ".pose-dataset-validation"
    original_rmtree = shutil.rmtree

    def blocked_final_cleanup(path: Path, *args: Any, **kwargs: Any) -> None:
        if Path(path) == staging:
            raise OSError("independent validation staging is locked")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", blocked_final_cleanup)

    with pytest.raises(OSError, match="independent validation staging is locked"):
        materialize_pose_training_exports(
            training_content=_pose_export_zip(b"reviewed-training"),
            validation_content=_pose_export_zip(b"reviewed-holdout"),
            destination=destination,
        )

    staged_frame = staging / "images" / "train" / "frame_00000001.png"
    assert staged_frame.read_bytes() == b"reviewed-holdout"


def test_pose_materialization_preserves_replaced_holdout_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Another worker can rename our claimed stage and replace it after the
    # holdout has been copied. Never delete that unrelated scientist's files.
    import reefvision.jobs.pose_training as pose_job

    destination = tmp_path / "pose-dataset"
    staging = tmp_path / ".pose-dataset-validation"
    displaced = tmp_path / "original-reviewed-validation"
    original_copy = pose_job._copy_split

    def replace_stage_after_copy(
        source_root: Path,
        destination_root: Path,
        *,
        split_name: str,
        class_count: int,
        keypoint_count: int,
    ) -> None:
        original_copy(
            source_root,
            destination_root,
            split_name=split_name,
            class_count=class_count,
            keypoint_count=keypoint_count,
        )
        staging.rename(displaced)
        staging.mkdir()
        (staging / "unrelated-scientific-data.txt").write_bytes(b"retain-other-run")

    monkeypatch.setattr(pose_job, "_copy_split", replace_stage_after_copy)
    with pytest.raises(ValidationError, match="staging directory changed"):
        materialize_pose_training_exports(
            training_content=_pose_export_zip(b"reviewed-train"),
            validation_content=_pose_export_zip(b"independent-reviewed-holdout"),
            destination=destination,
        )

    assert (staging / "unrelated-scientific-data.txt").read_bytes() == b"retain-other-run"
    assert (displaced / "images/train/frame_00000001.png").read_bytes() == (
        b"independent-reviewed-holdout"
    )
    assert (destination / "images/val/frame_00000001.png").read_bytes() == (
        b"independent-reviewed-holdout"
    )


def test_pose_training_rechecks_frozen_holdout_bytes_before_gpu_launch(
    tmp_path: Path,
) -> None:
    # Reuse the frozen export fixture to simulate changes between dataset
    # preparation and actual Ultralytics execution, without launching a GPU.
    destination = tmp_path / "pose-dataset"
    materialization = materialize_pose_training_exports(
        training_content=_pose_export_zip(b"reviewed-training"),
        validation_content=_pose_export_zip(b"reviewed-holdout"),
        destination=destination,
    )
    _verify_prelaunch_pose_dataset(destination, materialization)
    dataset_relative = "project/training/run/pose-dataset"
    manifest = {
        "materialization": materialization,
        "validation_mode": materialization["validation_mode"],
        "dataset_output_path": dataset_relative,
    }
    _verify_postlaunch_pose_dataset(destination, materialization, manifest, dataset_relative)

    # A hard link outside the frozen run leaves the original hash and name
    # unchanged but permits external writes to scientist-reviewed frames.
    training_frame = destination / "images" / "train" / "frame_00000001.png"
    external_alias = tmp_path / "outside-frozen-run.png"
    try:
        os.link(training_frame, external_alias)
    except (OSError, NotImplementedError):
        pass  # Only this subcase is unsupported on filesystems without hard links.
    else:
        try:
            with pytest.raises(ValidationError, match="hard-linked file"):
                _verify_prelaunch_pose_dataset(destination, materialization)
        finally:
            external_alias.unlink()
        _verify_prelaunch_pose_dataset(destination, materialization)
        assert training_frame.read_bytes() == b"reviewed-training"

    # The GPU worker must also reject changed persisted provenance even
    # when the frozen training and validation bytes are untouched.
    altered_provenance = {**materialization, "validation_mode": "none"}
    with pytest.raises(ValidationError, match="materialization provenance changed"):
        _verify_postlaunch_pose_dataset(
            destination,
            materialization,
            {**manifest, "materialization": altered_provenance},
            dataset_relative,
        )

    # A changed top-level validation mode must not authorize false holdout claims.
    with pytest.raises(ValidationError, match="materialization provenance changed"):
        _verify_postlaunch_pose_dataset(
            destination, materialization, {**manifest, "validation_mode": "none"}, dataset_relative
        )

    # An unchanged digest must not authorize a different recorded dataset location.
    with pytest.raises(ValidationError, match="materialization provenance changed"):
        _verify_postlaunch_pose_dataset(
            destination,
            materialization,
            {**manifest, "dataset_output_path": "another-run/pose-dataset"},
            dataset_relative,
        )

    holdout_label = destination / "labels" / "val" / "frame_00000001.txt"
    holdout_label.write_bytes(holdout_label.read_bytes() + b"changed")
    with pytest.raises(ValidationError, match="changed before GPU training"):
        _verify_prelaunch_pose_dataset(destination, materialization)
    # A modified validation label must also invalidate the completed GPU job,
    # even if it passed the earlier preflight verification.
    with pytest.raises(ValidationError, match="changed during GPU training"):
        _verify_postlaunch_pose_dataset(destination, materialization, manifest, dataset_relative)

    with pytest.raises(ValidationError, match="missing materialized dataset provenance"):
        _verify_prelaunch_pose_dataset(destination, None)


def test_pose_materialization_rejects_identical_frames_in_independent_validation(
    tmp_path: Path,
) -> None:
    # Reuse the reviewed export fixture but rename the holdout frame. Different
    # file names must not conceal train/validation leakage of identical bytes.
    reviewed = _pose_export_zip(b"same-reviewed-frame")
    holdout = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(reviewed)) as original,
        zipfile.ZipFile(holdout, "w", compression=zipfile.ZIP_DEFLATED) as modified,
    ):
        for member in original.namelist():
            renamed = member.replace("frame_00000001", "frame_00000002")
            modified.writestr(renamed, original.read(member))

    destination = tmp_path / "pose-overlapping-splits"
    with pytest.raises(ValidationError, match="reuses a frozen training frame"):
        materialize_pose_training_exports(
            training_content=reviewed,
            validation_content=holdout.getvalue(),
            destination=destination,
        )
    # A held-out frame collision must not strand this immutable run ID.
    assert not destination.exists()
    assert not (destination.parent / f".{destination.name}-validation").exists()

    # Correcting the independent frozen export should succeed at the same path.
    corrected = materialize_pose_training_exports(
        training_content=reviewed,
        validation_content=_pose_export_zip(b"separately-reviewed-holdout-frame"),
        destination=destination,
    )
    assert corrected["validation_mode"] == "separate_frozen_pose_dataset"
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"same-reviewed-frame"
    assert (
        destination / "images/val/frame_00000001.png"
    ).read_bytes() == b"separately-reviewed-holdout-frame"


@pytest.mark.parametrize(
    ("tampered_split", "missing_member", "expected_error"),
    (
        (
            "training",
            "labels/train/frame_00000001.txt",
            "missing frame images or labels",
        ),
        (
            "validation",
            "images/train/frame_00000001.png",
            "missing images/train",
        ),
    ),
)
def test_pose_materialization_rejects_unpaired_reviewed_frames(
    tmp_path: Path,
    tampered_split: str,
    missing_member: str,
    expected_error: str,
) -> None:
    # Exercise the existing frozen export fixture without replacing its
    # independent validation frames with training images or labels.
    reviewed = _pose_export_zip(b"reviewed")
    missing_frame_partner = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(reviewed)) as original,
        zipfile.ZipFile(missing_frame_partner, "w", compression=zipfile.ZIP_DEFLATED) as modified,
    ):
        for member in original.namelist():
            if member != missing_member:
                modified.writestr(member, original.read(member))

    altered = missing_frame_partner.getvalue()
    destination = tmp_path / "pose-unpaired-frames"
    # One-frame exports lose a whole split directory when its only file is removed.
    # Check the actual early rejection, before any validation frame is copied.
    with pytest.raises(ValidationError, match=expected_error):
        materialize_pose_training_exports(
            training_content=altered if tampered_split == "training" else reviewed,
            validation_content=altered if tampered_split == "validation" else reviewed,
            destination=destination,
        )

    # An incomplete train or independent holdout must not strand the run ID.
    assert not destination.exists()
    corrected = materialize_pose_training_exports(
        training_content=reviewed,
        validation_content=_pose_export_zip(b"independent-reviewed-validation"),
        destination=destination,
    )
    assert corrected["validation_mode"] == "separate_frozen_pose_dataset"
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed"
    assert (
        destination / "images/val/frame_00000001.png"
    ).read_bytes() == b"independent-reviewed-validation"


@pytest.mark.parametrize("altered_split", ("training", "validation"))
def test_pose_materialization_rejects_unmapped_frozen_class_labels(
    tmp_path: Path,
    altered_split: str,
) -> None:
    # Reuse the frozen pose fixture, changing only the numeric class ID in
    # its label; neither training nor validation may reinterpret that truth.
    reviewed = _pose_export_zip(b"reviewed")
    independent_validation = _pose_export_zip(b"independent-validation")
    source_export = reviewed if altered_split == "training" else independent_validation
    altered = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(source_export)) as original,
        zipfile.ZipFile(altered, "w", compression=zipfile.ZIP_DEFLATED) as modified,
    ):
        for member in original.namelist():
            content = original.read(member)
            if member == "labels/train/frame_00000001.txt":
                content = content.replace(b"0 0.5", b"1 0.5", 1)
            modified.writestr(member, content)

    # Keep genuine training and validation image bytes distinct so label
    # integrity is evaluated independently of the leakage guard.
    training_export = reviewed
    validation_export = independent_validation
    if altered_split == "training":
        training_export = altered.getvalue()
    else:
        validation_export = altered.getvalue()

    destination = tmp_path / "pose-unmapped-class"
    with pytest.raises(ValidationError, match="invalid label class index"):
        materialize_pose_training_exports(
            training_content=training_export,
            validation_content=validation_export,
            destination=destination,
        )
    assert not (destination / "images" / "val").exists()
    # Invalid frozen labels must not strand a saved run or prevent its retry.
    assert not destination.exists()
    corrected = materialize_pose_training_exports(
        training_content=reviewed,
        validation_content=independent_validation,
        destination=destination,
    )
    assert corrected["validation_mode"] == "separate_frozen_pose_dataset"
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed"
    assert (destination / "images/val/frame_00000001.png").read_bytes() == b"independent-validation"


@pytest.mark.parametrize("altered_split", ("training", "validation"))
@pytest.mark.parametrize(
    ("altered_label", "expected_error"),
    (
        ("0 0.5 0.5 0.5 0.5 0.5 0.5", "invalid landmark layout"),
        ("0 nan 0.5 0.5 0.5 0.5 0.5 2", "invalid label coordinates"),
        ("0 0.5 0.5 0.5 0.5 0.5 0.5 3", "invalid label coordinates"),
        ("0 0.95 0.5 0.4 0.5 0.5 0.5 2", "invalid label coordinates"),
        ("0 0.5 0.05 0.5 0.4 0.5 0.5 2", "invalid label coordinates"),
    ),
)
def test_pose_materialization_rejects_malformed_frozen_pose_rows(
    tmp_path: Path,
    altered_split: str,
    altered_label: str,
    expected_error: str,
) -> None:
    # Reuse the same frozen export fixture for training and separate validation.
    # A row that cannot encode the reviewed schema must fail before val copying.
    reviewed = _pose_export_zip(b"reviewed")
    independent_validation = _pose_export_zip(b"independent-validation")
    source_export = reviewed if altered_split == "training" else independent_validation
    altered = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(source_export)) as original,
        zipfile.ZipFile(altered, "w", compression=zipfile.ZIP_DEFLATED) as modified,
    ):
        for member in original.namelist():
            content = original.read(member)
            if member == "labels/train/frame_00000001.txt":
                content = (altered_label + "\n").encode("utf-8")
            modified.writestr(member, content)

    # Keep genuine training and validation image bytes distinct so label
    # integrity is evaluated independently of the leakage guard.
    training_export = reviewed
    validation_export = independent_validation
    if altered_split == "training":
        training_export = altered.getvalue()
    else:
        validation_export = altered.getvalue()

    destination = tmp_path / "pose-invalid-row"
    with pytest.raises(ValidationError, match=expected_error):
        materialize_pose_training_exports(
            training_content=training_export,
            validation_content=validation_export,
            destination=destination,
        )
    assert not (destination / "images" / "val").exists()
    # Invalid frozen labels must not strand a saved run or prevent its retry.
    assert not destination.exists()
    corrected = materialize_pose_training_exports(
        training_content=reviewed,
        validation_content=independent_validation,
        destination=destination,
    )
    assert corrected["validation_mode"] == "separate_frozen_pose_dataset"
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed"
    assert (destination / "images/val/frame_00000001.png").read_bytes() == b"independent-validation"


@pytest.mark.parametrize(
    ("extra_yaml", "expected_error"),
    (
        ("train: /outside-of-frozen-export\n", r"noncanonical data\.yaml"),
        ("val: /outside-of-frozen-export\n", r"noncanonical data\.yaml"),
        ("path: /outside-of-frozen-export\n", r"noncanonical data\.yaml"),
        ("'train': /outside-of-frozen-export\n", r"noncanonical data\.yaml"),
        (
            '  - "unreviewed-landmark"\n',
            "noncanonical class/keypoint metadata",
        ),
    ),
)
def test_pose_materialization_rejects_overridden_frozen_dataset_paths(
    tmp_path: Path,
    extra_yaml: str,
    expected_error: str,
) -> None:
    # The same frozen pose ZIP fixture must never accept a later YAML key that
    # overrides its reviewed training/validation directory or managed root.
    stream = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(_pose_export_zip(b"reviewed"))) as original,
        zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as modified,
    ):
        for entry in original.namelist():
            content = original.read(entry)
            if entry == "data.yaml":
                content += extra_yaml.encode("utf-8")
            modified.writestr(entry, content)

    destination = tmp_path / "pose-dataset"
    with pytest.raises(ValidationError, match=expected_error):
        materialize_pose_training_exports(
            training_content=stream.getvalue(),
            validation_content=None,
            destination=destination,
        )

    # Invalid frozen YAML must not occupy the immutable run directory or
    # prevent the saved workflow from retrying with the correct reviewed export.
    assert not destination.exists()
    corrected = materialize_pose_training_exports(
        training_content=_pose_export_zip(b"reviewed"),
        validation_content=None,
        destination=destination,
    )
    assert corrected["training_image_count"] == 1
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed"


@pytest.mark.parametrize(
    ("tampered_field", "expected_error"),
    (
        ("job_request", "child job request checksum changed"),
        ("unsealed_workflow_node", "workflow child job lineage changed"),
        ("unsealed_workflow_flag", "workflow child job lineage changed"),
        ("frozen_dataset", "frozen dataset lineage changed"),
        ("run_manifest", "frozen snapshot lineage changed"),
        ("snapshot_manifest", "frozen snapshot lineage changed"),
        ("snapshot_split", "frozen split manifest changed"),
        ("snapshot_schema", "frozen schema lineage changed"),
        ("resolved_asset", "frozen initialization lineage changed"),
        ("architecture", "frozen architecture changed"),
        ("snapshot_seed", "frozen initialization lineage changed"),
    ),
)
def test_pose_worker_checks_frozen_lineage_before_export(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tampered_field: str,
    expected_error: str,
) -> None:
    # Exercise the actual queued worker using an API-frozen, scientist-reviewed
    # pose dataset. It must fail before export or provider/GPU initialization.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    project_id = str(project["id"])

    def tampered_worker(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        with factory() as session:
            job = session.get(Job, job_id)
            assert job is not None
            request = dict(job.request_json)
            if tampered_field == "job_request":
                job.request_json = {
                    **request,
                    "pose_training_dataset_manifest_sha256": "0" * 64,
                }
            elif tampered_field in {"unsealed_workflow_node", "unsealed_workflow_flag"}:
                # Reproduce a historical saved-workflow job queued before
                # whole-request sealing while retaining genuine frozen truth.
                run = session.get(TrainingRun, str(request["training_run_id"]))
                assert run is not None
                snapshot = dict(run.draft_snapshot_json or {})
                assert snapshot.pop("pose_child_job_request_sha256")
                run.draft_snapshot_json = snapshot
                if tampered_field == "unsealed_workflow_node":
                    request["workflow_node_run_id"] = "unrelated-saved-node"
                else:
                    request["created_by_workflow"] = False
                job.request_json = request
            elif tampered_field == "frozen_dataset":
                frozen = session.get(PoseTrainingDataset, str(dataset["id"]))
                assert frozen is not None
                frozen.manifest_sha256 = "0" * 64
            else:
                run = session.get(TrainingRun, str(request["training_run_id"]))
                assert run is not None
                if tampered_field == "run_manifest":
                    run.dataset_manifest_sha256 = "0" * 64
                elif tampered_field == "resolved_asset":
                    run.resolved_model_asset_id = "registered_model:unrelated-model"
                elif tampered_field == "architecture":
                    original = request["pose_training_architecture"]
                    run.architecture = (
                        "yolo11s-pose.yaml"
                        if original == "yolo11n-pose.yaml"
                        else "yolo11n-pose.yaml"
                    )
                    run.resolved_model_asset_id = f"builtin_architecture:{run.architecture}"
                else:
                    snapshot = dict(run.draft_snapshot_json or {})
                    if tampered_field == "snapshot_split":
                        split_manifest = snapshot.get("split_manifest")
                        assert isinstance(split_manifest, dict)
                        snapshot["split_manifest"] = {
                            **split_manifest,
                            "unreviewed_test_field": True,
                        }
                    elif tampered_field == "snapshot_schema":
                        snapshot["pose_schema_revision"] = 999
                    elif tampered_field == "snapshot_seed":
                        snapshot["seed_model_sha256"] = "0" * 64
                    else:
                        snapshot["pose_training_dataset_manifest_sha256"] = "0" * 64
                    run.draft_snapshot_json = snapshot
            session.commit()

        assert process_pose_training_job(settings, factory, job_id) is False
        with factory() as session:
            job = session.get(Job, job_id)
            assert job is not None and job.status == "failed"
            assert expected_error in (job.error_message or "")
            materialized = resolve_managed_project_path(
                settings,
                f"{project['storage_root']}/training/{request['training_run_id']}/pose-dataset",
            )
            assert not (materialized / "data.yaml").exists()
        return False

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="Pose training child job did not complete"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload={
                "project_id": project_id,
                "dataset_id": dataset["id"],
                "manifest_sha256": dataset["manifest_sha256"],
            },
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-lineage-run",
            workflow_node_run_id="saved-pose-lineage-node",
            processor=tampered_worker,
        )


@pytest.mark.parametrize(
    ("alias", "expected_error"),
    (
        ("./images/train/frame_00000001.png", "duplicate archive path"),
        ("IMAGES/TRAIN/FRAME_00000001.PNG", "duplicate archive path"),
        ("images/train/frame_00000001.png.", "noncanonical archive path"),
        ("images/train/frame_00000001.png ", "noncanonical archive path"),
        ("images/train/CON.png", "Windows-unsafe archive path"),
        ("images/train/com¹.txt", "Windows-unsafe archive path"),
        ("images/train/frame:alternate.png", "Windows-unsafe archive path"),
        ("images/train/frame?.png", "Windows-unsafe archive path"),
        ("images/train/\x01frame.png", "Windows-unsafe archive path"),
    ),
)
def test_pose_materialization_rejects_aliased_archive_entries(
    tmp_path: Path,
    alias: str,
    expected_error: str,
) -> None:
    # A single frozen export must not overwrite verified image bytes through
    # a second ZIP member, including aliases that collide only on Windows.
    stream = io.BytesIO(_pose_export_zip(b"reviewed"))
    with zipfile.ZipFile(stream, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(alias, b"substituted")

    destination = tmp_path / "pose-ambiguous"
    with pytest.raises(ValidationError, match=expected_error):
        materialize_pose_training_exports(
            training_content=stream.getvalue(),
            validation_content=None,
            destination=destination,
        )

    assert not destination.exists()
    # A corrected frozen export can retry the same managed destination without
    # deleting partially created scientific data from the rejected archive.
    corrected = materialize_pose_training_exports(
        training_content=_pose_export_zip(b"reviewed"),
        validation_content=None,
        destination=destination,
    )
    assert corrected["training_image_count"] == 1
    assert (destination / "images" / "train" / "frame_00000001.png").read_bytes() == b"reviewed"


def test_pose_materialization_rejects_ambiguous_frozen_landmark_names(
    tmp_path: Path,
) -> None:
    # The exported external names must uniquely identify each anatomical point.
    # An ambiguous saved header must fail before the immutable run is claimed.
    def export_with_second_name(second_name: bytes) -> bytes:
        stream = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(_pose_export_zip(b"reviewed-frame"))) as original,
            zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as rewritten,
        ):
            for member in original.namelist():
                content = original.read(member)
                if member == "data.yaml":
                    content = content.replace(b"kpt_shape: [1, 3]", b"kpt_shape: [2, 3]")
                    content = content.replace(
                        b'  - "keypoint"\n',
                        b'  - "keypoint"\n  - "' + second_name + b'"\n',
                    )
                elif member.startswith("labels/train/"):
                    content = content.replace(b"0.5 0.5 2\n", b"0.5 0.5 2 0.25 0.75 2\n")
                rewritten.writestr(member, content)
        return stream.getvalue()

    destination = tmp_path / "frozen-pose-names"
    with pytest.raises(ValidationError, match="noncanonical class/keypoint metadata"):
        materialize_pose_training_exports(
            training_content=export_with_second_name(b"keypoint"),
            validation_content=None,
            destination=destination,
        )
    assert not destination.exists()

    corrected = materialize_pose_training_exports(
        training_content=export_with_second_name(b"other_keypoint"),
        validation_content=None,
        destination=destination,
    )
    assert corrected["training_image_count"] == 1
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed-frame"


@pytest.mark.parametrize(
    ("class_names", "expected_error"),
    (
        ((b"animal", b"animal"), "noncanonical class/keypoint metadata"),
        ((b" ", b"other"), "noncanonical class/keypoint metadata"),
    ),
)
def test_pose_materialization_rejects_ambiguous_frozen_class_names(
    tmp_path: Path,
    class_names: tuple[bytes, bytes],
    expected_error: str,
) -> None:
    # Two distinct class IDs must not silently share an empty or duplicate
    # scientific label in a frozen export from the saved workflow.
    reviewed = _pose_export_zip(b"reviewed-science-frame")
    altered = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(reviewed)) as original,
        zipfile.ZipFile(altered, "w", compression=zipfile.ZIP_DEFLATED) as rewritten,
    ):
        for member in original.namelist():
            content = original.read(member)
            if member == "data.yaml":
                content = content.replace(
                    b'  0: "animal"\n',
                    b'  0: "' + class_names[0] + b'"\n  1: "' + class_names[1] + b'"\n',
                )
            rewritten.writestr(member, content)

    destination = tmp_path / "frozen-pose-classes"
    with pytest.raises(ValidationError, match=expected_error):
        materialize_pose_training_exports(
            training_content=altered.getvalue(),
            validation_content=None,
            destination=destination,
        )
    assert not destination.exists()

    # A genuine corrected frozen export can occupy the original run path.
    result = materialize_pose_training_exports(
        training_content=reviewed,
        validation_content=None,
        destination=destination,
    )
    assert result["training_image_count"] == 1
    image_path = destination / "images/train/frame_00000001.png"
    assert image_path.read_bytes() == b"reviewed-science-frame"


def test_pose_materialization_missing_header_allows_corrected_frozen_export(
    tmp_path: Path,
) -> None:
    # A reviewed export lacking its required header must not occupy the run
    # directory, or a subsequently corrected export cannot be materialized.
    reviewed = _pose_export_zip(b"reviewed-frame")
    incomplete = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(reviewed)) as original,
        zipfile.ZipFile(incomplete, "w", compression=zipfile.ZIP_DEFLATED) as altered,
    ):
        for member in original.namelist():
            if member != "data.yaml":
                altered.writestr(member, original.read(member))

    destination = tmp_path / "pose-missing-header"
    with pytest.raises(ValidationError, match=r"missing data\.yaml"):
        materialize_pose_training_exports(
            training_content=incomplete.getvalue(),
            validation_content=None,
            destination=destination,
        )
    assert not destination.exists()

    result = materialize_pose_training_exports(
        training_content=reviewed,
        validation_content=None,
        destination=destination,
    )
    assert result["training_image_count"] == 1
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed-frame"


def test_pose_materialization_rejects_corrupt_frame_before_creating_dataset(
    tmp_path: Path,
) -> None:
    # Repack an actual frozen export with stored frame bytes, then mutate the
    # frame without updating the ZIP CRC. Archive paths and metadata stay valid.
    pristine = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(_pose_export_zip(b"reviewed-frame"))) as original,
        zipfile.ZipFile(pristine, "w", compression=zipfile.ZIP_STORED) as repacked,
    ):
        for name in original.namelist():
            repacked.writestr(name, original.read(name))

    valid_export = pristine.getvalue()
    assert valid_export.count(b"reviewed-frame") == 1
    corrupt_export = valid_export.replace(b"reviewed-frame", b"tampered-frame", 1)
    destination = tmp_path / "pose-corrupt-frame"
    with pytest.raises(ValidationError, match="corrupt archive member"):
        materialize_pose_training_exports(
            training_content=corrupt_export,
            validation_content=None,
            destination=destination,
        )

    # An invalid ZIP must not strand an occupied immutable run destination.
    assert not destination.exists()
    corrected = materialize_pose_training_exports(
        training_content=valid_export,
        validation_content=None,
        destination=destination,
    )
    assert corrected["training_image_count"] == 1
    assert (destination / "images" / "train" / "frame_00000001.png").read_bytes() == (
        b"reviewed-frame"
    )


def test_pose_materialization_rejects_unsafe_holdout_member_before_training_output(
    tmp_path: Path,
) -> None:
    # Valid frozen training and validation frames can be bundled with an
    # unsafe supplementary review file. Reject the entire holdout before
    # claiming the immutable training output, not during second extraction.
    training = _pose_export_zip(b"reviewed-training")
    valid_holdout = _pose_export_zip(b"reviewed-validation")
    holdout_stream = io.BytesIO(valid_holdout)
    with zipfile.ZipFile(holdout_stream, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("notes/../another-run.txt", b"unreviewed")

    destination = tmp_path / "pose-unsafe-holdout"
    with pytest.raises(ValidationError, match="unsafe archive path"):
        materialize_pose_training_exports(
            training_content=training,
            validation_content=holdout_stream.getvalue(),
            destination=destination,
        )
    assert not destination.exists()
    assert not (tmp_path / ".pose-unsafe-holdout-validation").exists()

    corrected = materialize_pose_training_exports(
        training_content=training,
        validation_content=valid_holdout,
        destination=destination,
    )
    assert corrected["validation_mode"] == "separate_frozen_pose_dataset"
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed-training"
    assert (destination / "images/val/frame_00000001.png").read_bytes() == b"reviewed-validation"


def test_pose_materialization_rejects_corrupt_unread_holdout_member(
    tmp_path: Path,
) -> None:
    # Training and held-out frame pairs are valid, but an additional saved
    # review artifact has a broken CRC. Frame-only preflight would miss it,
    # then strand the immutable training directory during holdout extraction.
    training = _pose_export_zip(b"reviewed-training")
    holdout_stream = io.BytesIO(_pose_export_zip(b"reviewed-validation"))
    with zipfile.ZipFile(holdout_stream, "a", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("review-notes.txt", b"reviewed-notes")

    valid_holdout = holdout_stream.getvalue()
    assert valid_holdout.count(b"reviewed-notes") == 1
    corrupt_holdout = valid_holdout.replace(b"reviewed-notes", b"tampered-notes", 1)
    with zipfile.ZipFile(io.BytesIO(corrupt_holdout)) as archive:
        assert archive.testzip() == "review-notes.txt"

    destination = tmp_path / "pose-corrupt-holdout"
    with pytest.raises(ValidationError, match="corrupt archive member"):
        materialize_pose_training_exports(
            training_content=training,
            validation_content=corrupt_holdout,
            destination=destination,
        )
    assert not destination.exists()
    assert not (tmp_path / ".pose-corrupt-holdout-validation").exists()

    # A corrected held-out bundle must be retryable at the original run path.
    corrected = materialize_pose_training_exports(
        training_content=training,
        validation_content=valid_holdout,
        destination=destination,
    )
    assert corrected["validation_mode"] == "separate_frozen_pose_dataset"
    assert (destination / "images/train/frame_00000001.png").read_bytes() == b"reviewed-training"
    assert (destination / "images/val/frame_00000001.png").read_bytes() == b"reviewed-validation"


@pytest.mark.parametrize("alias", ("images", "labels/train"))
def test_pose_materialization_rejects_file_directory_archive_collisions(
    tmp_path: Path,
    alias: str,
) -> None:
    # Valid frame bytes are present, but a later member declares one of their
    # parent directories to be a regular file. Preflight must reject the ZIP
    # before any scientist-reviewed frame is extracted.
    stream = io.BytesIO(_pose_export_zip(b"reviewed"))
    with zipfile.ZipFile(stream, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(alias, b"not a directory")

    destination = tmp_path / "pose-file-directory-collision"
    with pytest.raises(ValidationError, match="file-directory archive collision"):
        materialize_pose_training_exports(
            training_content=stream.getvalue(),
            validation_content=None,
            destination=destination,
        )

    assert not (destination / "images" / "train" / "frame_00000001.png").exists()


@pytest.mark.parametrize("special_type", (stat.S_IFLNK, stat.S_IFIFO))
def test_pose_materialization_rejects_special_archive_members(
    tmp_path: Path,
    special_type: int,
) -> None:
    # Use the existing reviewed pose export fixture. Unix symlink/device
    # entries must fail preflight before any verified frame is written.
    stream = io.BytesIO(_pose_export_zip(b"reviewed"))
    member = zipfile.ZipInfo("images/train/unreviewed.png")
    member.create_system = 3
    member.external_attr = (special_type | 0o777) << 16
    with zipfile.ZipFile(stream, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, b"not-an-image")

    destination = tmp_path / "pose-special-member"
    with pytest.raises(ValidationError, match="special archive member"):
        materialize_pose_training_exports(
            training_content=stream.getvalue(),
            validation_content=None,
            destination=destination,
        )

    assert not (destination / "images" / "train" / "frame_00000001.png").exists()


def test_pose_training_completion_rejects_missing_or_redirected_checkpoints(
    tmp_path: Path,
) -> None:
    # The worker must not mark a trained pose model successful without a
    # locally produced checkpoint; older registered model bytes are protected.
    output = tmp_path / "run" / "runs" / "pose"
    weights = output / "weights"
    weights.mkdir(parents=True)
    with pytest.raises(ValidationError, match="no usable checkpoints"):
        _require_trusted_pose_checkpoints(output)

    best = weights / "best.pt"
    best.write_bytes(b"")
    with pytest.raises(ValidationError, match="checkpoint is empty or redirected"):
        _require_trusted_pose_checkpoints(output)

    best.write_bytes(b"new-run-pose-checkpoint")
    _require_trusted_pose_checkpoints(output)
    best.unlink()
    last = weights / "last.pt"
    last.write_bytes(b"new-run-last-checkpoint")
    _require_trusted_pose_checkpoints(output)
    last.unlink()

    prior = tmp_path / "registered-model.pt"
    prior.write_bytes(b"preserve-existing-registered-weights")
    # A real hard link aliases prior registered-model bytes while lstat()
    # still reports an ordinary nonempty file. Do not publish this as new.
    try:
        os.link(prior, best)
    except (OSError, NotImplementedError):
        pass  # Some filesystems do not support hard links.
    else:
        with pytest.raises(ValidationError, match="checkpoint is hard-linked"):
            _require_trusted_pose_checkpoints(output)
        assert prior.read_bytes() == b"preserve-existing-registered-weights"
        best.unlink()
    try:
        best.symlink_to(prior)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Checkpoint symlink creation unavailable: {exc}")
    with pytest.raises(ValidationError, match="checkpoint is empty or redirected"):
        _require_trusted_pose_checkpoints(output)
    assert prior.read_bytes() == b"preserve-existing-registered-weights"


@pytest.mark.parametrize("output_name", ("pose-dataset", "ultralytics", "runs", "runs/pose"))
def test_pose_run_output_rejects_redirect_into_another_managed_run(
    tmp_path: Path,
    output_name: str,
) -> None:
    # The generic managed-path resolver follows symlinks inside data_root.
    # A symlinked dataset/log/GPU project root must never redirect cleanup,
    # training outputs, or checkpoint writes into another scientific run.
    settings = Settings(data_dir=tmp_path / "managed")
    training_root = settings.resolved_data_dir / "projects" / "p1" / "training"
    prior_run = training_root / "prior-run"
    prior_run.mkdir(parents=True)
    marker = prior_run / "registered-model-checkpoint.pt"
    marker.write_bytes(b"preserve-existing-user-trained-weights")

    current_run = training_root / "current-run"
    current_run.mkdir()
    linked_output = current_run / output_name
    linked_output.parent.mkdir(parents=True, exist_ok=True)
    try:
        linked_output.symlink_to(prior_run, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation is unavailable on this host: {exc}")

    relative = f"projects/p1/training/current-run/{output_name}"
    # This would previously resolve to the prior-run directory, making
    # shutil.rmtree() and training.log writes target preserved user data.
    assert resolve_managed_project_path(settings, relative) == prior_run.resolve()
    with pytest.raises(ValidationError, match="output path contains a symbolic link"):
        _resolve_unlinked_pose_run_path(settings, relative)
    assert marker.read_bytes() == b"preserve-existing-user-trained-weights"

    linked_output.unlink()
    assert (
        _resolve_unlinked_pose_run_path(settings, relative) == (current_run / output_name).resolve()
    )


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS junctions require Windows")
def test_pose_run_output_rejects_windows_junction_into_another_run(tmp_path: Path) -> None:
    # A genuine Windows directory junction is not a symbolic link.
    # Training must never follow it into an earlier registered-model run.
    settings = Settings(data_dir=tmp_path / "managed")
    training_root = settings.resolved_data_dir / "projects" / "p1" / "training"
    prior_output = training_root / "prior-run" / "runs"
    prior_output.mkdir(parents=True)
    checkpoint = prior_output / "registered-model-checkpoint.pt"
    checkpoint.write_bytes(b"preserve-registered-pose-weights")

    current_run = training_root / "current-run"
    current_run.mkdir()
    junction = current_run / "runs"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(prior_output)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        assert not junction.is_symlink()
        relative = "projects/p1/training/current-run/runs/pose"
        with pytest.raises(ValidationError, match="output path contains a Windows junction"):
            _resolve_unlinked_pose_run_path(settings, relative)
        # The service-layer checkpoint and seed-model guard must reject the
        # same junction on replay, even when its final target is managed.
        with pytest.raises(ValidationError, match="artifact path contains a Windows junction"):
            _reject_symlinked_training_path(settings, relative)
        # Even an alias resolving to the expected run must not pass the
        # trainer's post-fit checkpoint provenance check.
        with pytest.raises(
            ValidationError, match="trainer output path contains a Windows junction"
        ):
            _verified_pose_trainer_save_dir(junction, prior_output)
        # A direct materialization must reject redirected ancestors as well.
        with pytest.raises(ValidationError, match="export path contains a Windows junction"):
            materialize_pose_training_exports(
                training_content=_pose_export_zip(b"reviewed"),
                validation_content=None,
                destination=junction / "frozen-export",
            )
        # Fingerprinting must also reject a junction swapped in at the root,
        # not only junctions discovered underneath the dataset directory.
        with pytest.raises(ValidationError, match="dataset path contains a Windows junction"):
            _materialized_pose_dataset_sha256(junction)
        assert checkpoint.read_bytes() == b"preserve-registered-pose-weights"
    finally:
        junction.rmdir()

    # The temporary validation-stage directory is a sibling of the frozen
    # dataset, so it requires its own junction guard before export or cleanup.
    stage_junction = current_run / ".frozen-export-validation"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(stage_junction), str(prior_output)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        with pytest.raises(ValidationError, match="export path contains a Windows junction"):
            materialize_pose_training_exports(
                training_content=_pose_export_zip(b"reviewed-train"),
                validation_content=_pose_export_zip(b"reviewed-holdout"),
                destination=current_run / "frozen-export",
            )
        assert not (current_run / "frozen-export").exists()
        assert checkpoint.read_bytes() == b"preserve-registered-pose-weights"
    finally:
        stage_junction.rmdir()

    # A junction inserted inside an already-frozen dataset must not be
    # silently skipped by hashing or followed into another scientific run.
    frozen_dataset = current_run / "pose-dataset"
    frozen_dataset.mkdir()
    nested_junction = frozen_dataset / "reviewed-frames"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(nested_junction), str(prior_output)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        assert not nested_junction.is_symlink()
        with pytest.raises(ValidationError, match="Windows junction"):
            _materialized_pose_dataset_sha256(frozen_dataset)
        assert checkpoint.read_bytes() == b"preserve-registered-pose-weights"
    finally:
        nested_junction.rmdir()


def test_pose_training_output_cleanup_preserves_prior_run_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An interrupted run may contain checkpoints already used by registered
    # models. Refuse this run ID without deleting or mixing its original bytes.
    output_root = tmp_path / "training" / "current-run" / "ultralytics"
    old_checkpoint = output_root / "runs" / "pose" / "weights" / "best.pt"
    old_checkpoint.parent.mkdir(parents=True)
    old_checkpoint.write_bytes(b"checkpoint-from-interrupted-attempt")

    def unexpected_cleanup(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("pose training must preserve previous run artifacts")

    with monkeypatch.context() as patch:
        patch.setattr(shutil, "rmtree", unexpected_cleanup)
        with pytest.raises(ValidationError, match="already exists"):
            _prepare_clean_pose_training_output(output_root)

    assert old_checkpoint.read_bytes() == b"checkpoint-from-interrupted-attempt"

    # A genuinely new run can create its own empty log directory, but neither
    # its nonempty nor its empty output may be silently reused.
    fresh_root = tmp_path / "training" / "fresh-run" / "ultralytics"
    _prepare_clean_pose_training_output(fresh_root)
    assert fresh_root.is_dir()
    assert list(fresh_root.iterdir()) == []
    with pytest.raises(ValidationError, match="already exists"):
        _prepare_clean_pose_training_output(fresh_root)
    assert old_checkpoint.read_bytes() == b"checkpoint-from-interrupted-attempt"


def test_pose_training_refuses_reused_gpu_output_and_preserves_checkpoints(
    tmp_path: Path,
) -> None:
    # The Ultralytics trainer writes under runs/pose, not ultralytics/. A
    # retried run must neither mix old weights nor erase a registered model.
    output_root = tmp_path / "runs" / "pose"
    _require_empty_pose_gpu_output(output_root)
    output_root.mkdir(parents=True)
    _require_empty_pose_gpu_output(output_root)

    checkpoint = output_root / "weights" / "best.pt"
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"preserve-registered-user-trained-weights")
    with pytest.raises(ValidationError, match="refusing to reuse previous artifacts"):
        _require_empty_pose_gpu_output(output_root)
    assert checkpoint.read_bytes() == b"preserve-registered-user-trained-weights"


def test_pose_training_refuses_unexpected_trainer_checkpoint_directory(
    tmp_path: Path,
) -> None:
    # Ultralytics must not register artifacts from another run if its
    # save_dir differs from the immutable workflow run's allocated path.
    expected = tmp_path / "training" / "frozen-run" / "runs" / "pose"
    unrelated = tmp_path / "training" / "other-run" / "runs" / "pose"
    expected.mkdir(parents=True)
    unrelated.mkdir(parents=True)
    checkpoint = unrelated / "best.pt"
    checkpoint.write_bytes(b"preserve-unrelated-scientific-checkpoint")

    assert _verified_pose_trainer_save_dir(expected, expected) == expected
    with pytest.raises(ValidationError, match="does not match queued training run"):
        _verified_pose_trainer_save_dir(unrelated, expected)
    assert checkpoint.read_bytes() == b"preserve-unrelated-scientific-checkpoint"

    linked = tmp_path / "linked-run-output"
    try:
        linked.symlink_to(expected, target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    with pytest.raises(ValidationError, match="contains a symbolic link"):
        _verified_pose_trainer_save_dir(linked, expected)


def test_pose_materialization_rejects_symlinked_export_destinations(
    tmp_path: Path,
) -> None:
    # A previously prepared run or validation stage can be redirected to a
    # different directory. No copied pose images should follow that redirect.
    archive = _pose_export_zip(b"reviewed-pose-export")
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("unchanged", encoding="utf-8")

    linked_destination = tmp_path / "pose-dataset"
    try:
        linked_destination.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation is unavailable on this host: {exc}")

    with pytest.raises(ValidationError, match="destination contains a symbolic link"):
        materialize_pose_training_exports(
            training_content=archive,
            validation_content=None,
            destination=linked_destination,
        )
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert not (outside / "data.yaml").exists()

    # The redirected root has the same bytes as the sealed input, so a
    # fingerprint comparison alone cannot establish the saved run lineage.
    sealed_digest = _materialized_pose_dataset_sha256(outside)
    with pytest.raises(ValidationError, match="dataset path contains a symbolic link"):
        _verify_prelaunch_pose_dataset(
            linked_destination,
            {
                "materialized_dataset_sha256": sealed_digest,
                "materialized_dataset_fingerprint_algorithm": "relative-posix-path-v1",
            },
        )
    assert marker.read_text(encoding="utf-8") == "unchanged"

    linked_parent = tmp_path / "redirected-run"
    linked_parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError, match="destination contains a symbolic link"):
        materialize_pose_training_exports(
            training_content=archive,
            validation_content=None,
            destination=linked_parent / "pose-dataset",
        )
    assert not (outside / "pose-dataset").exists()

    validation_stage = tmp_path / ".safe-pose-dataset-validation"
    validation_stage.symlink_to(outside, target_is_directory=True)
    destination = tmp_path / "safe-pose-dataset"
    with pytest.raises(ValidationError, match="validation staging path is a symbolic link"):
        materialize_pose_training_exports(
            training_content=archive,
            validation_content=archive,
            destination=destination,
        )
    assert not destination.exists()
    assert marker.read_text(encoding="utf-8") == "unchanged"


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

    # An actual local registration must not silently fall back to its filename
    # when persisted source-architecture lineage is a malformed JSON array.
    with app.state.session_factory() as session:
        registered = session.get(ModelRegistration, model_id)
        assert registered is not None
        original_metadata = dict(registered.metadata_json or {})
        registered.metadata_json = {**original_metadata, "source_architecture": []}
        session.commit()

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="seed source architecture metadata is invalid"),
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
            initial_model_payload=seed_reference,
            parameters={"device": "cpu", "training_config": {"epochs": 1}},
            processor=_fake_pose_processor,
        )

    with app.state.session_factory() as session:
        assert session.scalars(select(TrainingRun.id)).all() == []
        registered = session.get(ModelRegistration, model_id)
        assert registered is not None
        registered.metadata_json = original_metadata
        session.commit()

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
        experiment = session.scalar(
            select(ExperimentRecord).where(
                ExperimentRecord.training_run_id == result["training_run_id"]
            )
        )
        assert experiment is not None
        assert experiment.project_id == project["id"]
        assert experiment.summary_metrics_json == result["metrics"]
        assert experiment.comparison_warnings_json == result["warnings"]
        assert (
            experiment.artifact_manifest_json["result_checkpoint_path"]
            == result["result_checkpoint_path"]
        )
        assert (
            experiment.artifact_manifest_json["result_checkpoint_sha256"]
            == result["result_checkpoint_sha256"]
        )
        assert (
            experiment.artifact_manifest_json["best_checkpoint_sha256"]
            == result["result_checkpoint_sha256"]
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

    # Keep the selected checkpoint bytes intact, but alias the inode. A saved
    # workflow must reject it despite matching both previously frozen digests.
    selected_checkpoint = resolve_managed_project_path(
        test_settings, str(result["result_checkpoint_path"])
    )
    selected_alias = selected_checkpoint.parent / "best-hardlink-alias.pt"
    try:
        os.link(selected_checkpoint, selected_alias)
    except (OSError, NotImplementedError):
        pass  # Unsupported filesystems still exercise normal replay above.
    else:
        try:
            with pytest.raises(ValidationError, match="checkpoint artifact is hard-linked"):
                retry_completed_node()
        finally:
            selected_alias.unlink()
        assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # This API-frozen, scientist-verified dataset produced a real persisted
    # experiment record. A changed software environment cannot be replayed
    # under the originally frozen checkpoint and workflow lineage.
    with app.state.session_factory() as session:
        experiment = session.scalar(
            select(ExperimentRecord).where(
                ExperimentRecord.training_run_id == result["training_run_id"]
            )
        )
        assert experiment is not None
        original_packages = dict(experiment.package_versions_json)
        assert experiment.artifact_manifest_json[
            "experiment_package_versions_sha256"
        ] == canonical_json_sha256(original_packages)
        experiment.package_versions_json = {
            **original_packages,
            "tampered-runtime-package": "0.0.0",
        }
        session.commit()

    with pytest.raises(ValidationError, match="package-version provenance changed"):
        retry_completed_node()

    with app.state.session_factory() as session:
        experiment = session.scalar(
            select(ExperimentRecord).where(
                ExperimentRecord.training_run_id == result["training_run_id"]
            )
        )
        assert experiment is not None
        experiment.package_versions_json = original_packages
        session.commit()
    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # Removing the digest from both persisted manifests must not silently
    # downgrade a completed v4 run to unchecked software provenance.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        experiment = session.scalar(
            select(ExperimentRecord).where(
                ExperimentRecord.training_run_id == result["training_run_id"]
            )
        )
        assert persisted is not None and experiment is not None
        original_manifest = dict(persisted.artifact_manifest_json)
        stripped_manifest = {
            key: value
            for key, value in original_manifest.items()
            if key != "experiment_package_versions_sha256"
        }
        persisted.artifact_manifest_json = stripped_manifest
        experiment.artifact_manifest_json = dict(stripped_manifest)
        session.commit()

    with pytest.raises(ValidationError, match="package-version provenance changed"):
        retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        experiment = session.scalar(
            select(ExperimentRecord).where(
                ExperimentRecord.training_run_id == result["training_run_id"]
            )
        )
        assert persisted is not None and experiment is not None
        persisted.artifact_manifest_json = original_manifest
        experiment.artifact_manifest_json = dict(original_manifest)
        session.commit()
    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # A completed saved Workflow Builder node must have one unambiguous child
    # training run. A second older completed record must not be silently
    # ignored simply because its checkpoint was not chosen by the sort order.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        duplicate_id = str(uuid4())
        duplicate = TrainingRun(
            **{
                column.name: getattr(persisted, column.name)
                for column in TrainingRun.__table__.columns
                if column.name not in {"id", "job_id", "created_at"}
            },
            id=duplicate_id,
            job_id=None,
            created_at=persisted.created_at - timedelta(seconds=1),
        )
        session.add(duplicate)
        session.commit()

    with pytest.raises(ValidationError, match="multiple completed child runs"):
        retry_completed_node()

    with app.state.session_factory() as session:
        duplicate = session.get(TrainingRun, duplicate_id)
        assert duplicate is not None
        session.delete(duplicate)
        session.commit()
    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # The saved workflow must retain the provider parameter-registry version
    # used to configure this actual scientist-verified training run. Neither
    # rewriting the run nor removing its frozen assertion may authorize replay.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        original_registry = persisted.parameter_registry_version
        original_snapshot = dict(persisted.draft_snapshot_json or {})
        assert original_snapshot["schema_version"] == "pose-workflow-training-snapshot-0004"
        assert original_snapshot["parameter_registry_version"] == original_registry
        persisted.parameter_registry_version = "substituted-provider-registry"
        session.commit()

    with pytest.raises(ValidationError, match="provider registry version changed"):
        retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        persisted.parameter_registry_version = original_registry
        persisted.draft_snapshot_json = {
            key: value
            for key, value in original_snapshot.items()
            if key != "parameter_registry_version"
        }
        session.commit()

    with pytest.raises(ValidationError, match="provider registry version changed"):
        retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        persisted.draft_snapshot_json = original_snapshot
        session.commit()

    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # A completed v4 snapshot cannot evade frozen metrics, package versions,
    # or provider-registry assertions by changing only the schema marker.
    for downgraded_schema in (
        "pose-workflow-training-snapshot-0001",
        "pose-workflow-training-snapshot-0002",
        "pose-workflow-training-snapshot-0003",
        None,
    ):
        with app.state.session_factory() as session:
            persisted = session.get(TrainingRun, result["training_run_id"])
            assert persisted is not None
            persisted.draft_snapshot_json = {
                **original_snapshot,
                "schema_version": downgraded_schema,
            }
            session.commit()

        with pytest.raises(ValidationError, match="snapshot schema changed"):
            retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        persisted.draft_snapshot_json = original_snapshot
        session.commit()

    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # A saved Workflow Builder replay must not return altered epoch-level
    # metrics merely because its final experiment summary still matches.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        original_history = dict(persisted.metrics_history_json or {})
        assert original_snapshot["metrics_history_sha256"]
        persisted.metrics_history_json = {**original_history, "epoch": [999]}
        session.commit()

    with pytest.raises(ValidationError, match="metrics history changed"):
        retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        persisted.metrics_history_json = original_history
        session.commit()

    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # JSON arrays of key/value pairs convert to the original dict and would
    # pass a hash check that silently coerces malformed epoch-level evidence.
    # The saved scientist-verified training run must reject that type change.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        persisted.metrics_history_json = [[key, value] for key, value in original_history.items()]
        session.commit()

    with pytest.raises(ValidationError, match="metrics history changed"):
        retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        persisted.metrics_history_json = original_history
        session.commit()

    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # A persisted JSON array of metric pairs must not be silently coerced
    # into the original summary dictionary during scientific replay.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        original_summary = dict(persisted.metrics_json or {})
        persisted.metrics_json = [[key, value] for key, value in original_summary.items()]
        session.commit()

    with pytest.raises(ValidationError, match="summary metrics must be a JSON object"):
        retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        persisted.metrics_json = original_summary
        session.commit()

    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # A malformed array of key/value pairs must not be accepted as an
    # unchanged frozen checkpoint manifest during completed-node replay.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        original_manifest = dict(persisted.artifact_manifest_json or {})
        persisted.artifact_manifest_json = [
            [key, value] for key, value in original_manifest.items()
        ]
        session.commit()

    with pytest.raises(ValidationError, match="artifact manifest must be a JSON object"):
        retry_completed_node()

    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        persisted.artifact_manifest_json = original_manifest
        session.commit()

    assert retry_completed_node()["training_run_id"] == result["training_run_id"]

    # The experiment registry is a second persisted scientific record, not
    # merely an ID to expose downstream. A replay must reject inconsistent
    # metadata or checkpoint evidence without starting another training run.
    # Removing a digest or frozen dataset identity is also a provenance change.
    missing_checkpoint_digest = dict(result["artifact_manifest"])
    missing_checkpoint_digest.pop("result_checkpoint_sha256")
    missing_dataset_identity = dict(result["artifact_manifest"])
    missing_dataset_identity.pop("pose_training_dataset_id")
    for field, corrupt_value in (
        ("provider_id", "unrelated-provider"),
        ("summary_metrics_json", {"metrics/mAP50-95(P)": 0.01}),
        ("comparison_warnings_json", ["altered scientific warning"]),
        (
            "artifact_manifest_json",
            {
                **result["artifact_manifest"],
                "native_results_rows": [{"epoch": 1, "metrics/mAP50-95(P)": 0.01}],
            },
        ),
        (
            "artifact_manifest_json",
            {**result["artifact_manifest"], "result_checkpoint_sha256": "0" * 64},
        ),
        ("artifact_manifest_json", missing_checkpoint_digest),
        ("artifact_manifest_json", missing_dataset_identity),
    ):
        with app.state.session_factory() as session:
            experiment = session.scalar(
                select(ExperimentRecord).where(
                    ExperimentRecord.training_run_id == result["training_run_id"]
                )
            )
            assert experiment is not None
            original_value = getattr(experiment, field)
            setattr(experiment, field, corrupt_value)
            session.commit()

        with pytest.raises(ValidationError, match="experiment provenance changed"):
            retry_completed_node()

        with app.state.session_factory() as session:
            experiment = session.scalar(
                select(ExperimentRecord).where(
                    ExperimentRecord.training_run_id == result["training_run_id"]
                )
            )
            assert experiment is not None
            setattr(experiment, field, original_value)
            session.commit()

        assert retry_completed_node()["training_run_id"] == result["training_run_id"]

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

    # New jobs seal the entire queued request. Removing a frozen manifest
    # assertion must not turn a modern job into an unchecked legacy request.
    with app.state.session_factory() as session:
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None and persisted.job_id is not None
        child_job = session.get(Job, persisted.job_id)
        assert child_job is not None
        original_request = dict(child_job.request_json)
        expected_request_digest = persisted.draft_snapshot_json["pose_child_job_request_sha256"]
        assert expected_request_digest == canonical_json_sha256(original_request)
        dropped_digest_request = dict(original_request)
        dropped_digest_request.pop("pose_training_dataset_manifest_sha256")
        child_job.request_json = dropped_digest_request
        session.commit()

    with pytest.raises(ValidationError, match="child job request checksum changed"):
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
        (None, "snapshot schema changed"),
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
    original_checkpoint_bytes = checkpoint.read_bytes()
    checkpoint.write_bytes(b"changed-after-scientist-verified-pose-training")
    with pytest.raises(ValidationError, match=r"checkpoint (?:artifact )?checksum changed"):
        retry_completed_node()
    checkpoint.write_bytes(original_checkpoint_bytes)

    # A newly completed workflow always creates a persisted experiment.
    # Losing that registry record must not silently publish experiment_id=None
    # on replay of this scientist-reviewed frozen training dataset.
    with app.state.session_factory() as session:
        experiment = session.scalar(
            select(ExperimentRecord).where(
                ExperimentRecord.training_run_id == result["training_run_id"]
            )
        )
        assert experiment is not None
        session.delete(experiment)
        session.commit()

    with pytest.raises(ValidationError, match="experiment registry record is missing"):
        retry_completed_node()

    with app.state.session_factory() as session:
        assert session.scalars(select(TrainingRun.id)).all() == [result["training_run_id"]]


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


def test_pose_workflow_rejects_noninteger_epochs_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A scientist-reviewed dataset is frozen through the actual API.
    # bool and fractional/string epochs must not become a different run via int().
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    for invalid_epochs in (True, False, 1.5, 1.0, "1", None, [], {}):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match=r"training_config\.epochs must be an integer"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={"device": "cpu", "training_config": {"epochs": invalid_epochs}},
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert session.scalar(select(TrainingRun.id)) is None
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={"device": "cpu", "training_config": {"epochs": 1}},
            processor=_fake_pose_processor,
        )
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        assert persisted.progress_total_epochs == 1
        assert persisted.training_config_json["epochs"] == 1


def test_pose_workflow_pins_offline_amp_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The dataset is frozen through the scientist-review API. Reject an AMP
    # request that the offline worker would silently override to fp32.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    for invalid_amp in (True, 1, "false", None, [], {}):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match=r"training_config\.amp must be false"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={"device": "cpu", "training_config": {"epochs": 1, "amp": invalid_amp}},
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert session.scalar(select(TrainingRun.id)) is None
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={"device": "cpu", "training_config": {"epochs": 1}},
            processor=_fake_pose_processor,
        )
        persisted = session.get(TrainingRun, result["training_run_id"])
        assert persisted is not None
        assert persisted.training_config_json["amp"] is False
        # Windows forces single-process loading at the GPU worker. The saved
        # experiment must reflect those actual settings, not requested defaults.
        assert persisted.training_config_json["workers"] == (0 if sys.platform == "win32" else 2)
        if sys.platform == "win32":
            assert any(
                "Windows pose training uses workers=0" in warning
                for warning in persisted.warnings_json
            )


def test_pose_workflow_requires_effective_fp32_precision_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep the original scientist-reviewed, API-frozen dataset intact.
    # A saved workflow must record effective fp32, not an AMP mode
    # that the offline worker silently ignores.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    dataset_payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }
    for invalid_precision in (None, False, 0, [], {}, "", " fp32 ", "amp", "FP32"):
        with (
            app.state.session_factory() as session,
            pytest.raises(
                ValidationError, match=r"precision must be fp32 \(offline AMP disabled\)"
            ),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={
                    "precision": invalid_precision,
                    "training_config": {"epochs": 1},
                },
                processor=_fake_pose_processor,
            )

    with app.state.session_factory() as session:
        assert session.scalar(select(TrainingRun.id)) is None
        valid = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={
                "device": "cpu",
                "precision": "fp32",
                "training_config": {"epochs": 1},
            },
            processor=_fake_pose_processor,
        )
    assert valid["precision"] == "fp32"


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
        (" phase10-pose-retrain", "run_name must not contain surrounding whitespace"),
        ("phase10-pose-retrain ", "run_name must not contain surrounding whitespace"),
        ("\tphase10-pose-retrain", "run_name must not contain surrounding whitespace"),
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
    # An invalid or noncanonical device must fail before a training job is queued.
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
    for invalid_device in (False, 0, None, [], {}, "", "   ", " cpu", "cpu ", "\tcuda:0"):
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="device must be a non-blank canonical string"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={**parameters, "device": invalid_device},
                processor=_fake_pose_processor,
            )

    # The real offline worker forcibly replaces these Ultralytics args,
    # so a frozen workflow must not persist contradictory scientific inputs.
    for worker_field, worker_value in (
        ("data", "/tmp/alternate.yaml"),
        ("device", "cuda:0"),
        ("project", "/tmp/alternate"),
        ("name", "alternate-run"),
        ("exist_ok", False),
        ("save", False),
        ("verbose", True),
    ):
        with (
            app.state.session_factory() as session,
            pytest.raises(
                ValidationError,
                match=rf"training_config\.{worker_field} is managed by",
            ),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=dataset_payload,
                parameters={
                    **parameters,
                    "device": "cpu",
                    "training_config": {"epochs": 1, worker_field: worker_value},
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
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={**parameters, "device": "cpu"},
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
    # A decimal string with surrounding whitespace must not be normalized
    # into a different saved random seed without the scientist's consent.
    for invalid_seed in (
        True,
        False,
        -1,
        2.5,
        "2.5",
        "invalid",
        "²",
        2**63,
        "9" * 5000,
        " 7",
        "7 ",
        "\t7",
    ):
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

    # Both frozen datasets came from genuine independently verified rounds.
    # Even when a later source-video revision carries a different digest,
    # sharing the original video identity is still training/validation leakage.
    with app.state.session_factory() as session:
        training_row = session.get(PoseTrainingDataset, str(training["id"]))
        validation_row = session.get(PoseTrainingDataset, str(validation["id"]))
        assert training_row is not None and validation_row is not None
        training_items = training_row.manifest_json["items"]
        validation_items = validation_row.manifest_json["items"]
        assert training_items[0]["video_id"] == validation_items[0]["video_id"]
        different_digest = "0" * 64
        if different_digest == training_items[0]["video_sha256"]:
            different_digest = "1" * 64
        revised_items = [{**item, "video_sha256": different_digest} for item in validation_items]
        assert _shared_pose_source_videos(training_items, revised_items)

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


@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("metadata", "seed metadata must be a JSON object"),
        ("size", "seed checkpoint size differs from registry"),
        ("hardlink", "seed checkpoint is hard-linked"),
        ("path", "seed checkpoint is outside its model registry"),
    ],
)
def test_pose_workflow_rejects_corrupt_seed_registry_from_verified_truth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    expected_error: str,
) -> None:
    # Freeze a scientist-verified round and register a local, schema-bound
    # checkpoint before corrupting registry metadata or file independence.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    model_id = _seed_model(app, project, dataset)

    with app.state.session_factory() as session:
        model = session.get(ModelRegistration, model_id)
        assert model is not None
        if corruption == "metadata":
            # A list of pairs is not a valid architecture metadata object.
            model.metadata_json = cast(Any, [["source_architecture", "yolo11n-pose.pt"]])
        elif corruption == "size":
            # Leave the actual checkpoint and checksum intact.
            model.file_size_bytes += 1
        elif corruption == "path":
            checkpoint = resolve_managed_project_path(test_settings, model.managed_path)
            misplaced = f"{project['storage_root']}/training-output/{model.id}.pt"
            destination = resolve_managed_project_path(test_settings, misplaced)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(checkpoint.read_bytes())
            model.managed_path = misplaced
        else:
            checkpoint = resolve_managed_project_path(test_settings, model.managed_path)
            alias = checkpoint.with_name("external-seed-alias.pt")
            try:
                os.link(checkpoint, alias)
            except OSError as exc:
                pytest.skip(f"Filesystem does not support hard links: {exc}")
            assert checkpoint.stat().st_nlink > 1
        session.commit()

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
            initial_model_payload={"model_id": model_id},
            parameters={"training_config": {"epochs": 1}},
            processor=_fake_pose_processor,
        )

    with app.state.session_factory() as session:
        assert session.scalar(select(TrainingRun.id)) is None


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

    # Saved graph inputs must not change the registered model identity by trimming whitespace.
    for invalid_architecture in (
        None,
        False,
        0,
        [],
        {},
        "",
        "   ",
        123,
        " yolo11n-pose.yaml",
        "yolo11n-pose.yaml ",
        "\tyolo11n-pose.yaml",
    ):
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

    # Newly queued saved-workflow jobs carry immutable source and split
    # digests in their request. Detect a worker changing one while leaving
    # dataset IDs and otherwise valid checkpoint bytes untouched.
    def substituted_manifest_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as child_session:
            job = child_session.get(Job, job_id)
            assert job is not None
            request = dict(job.request_json)
            assert request["pose_training_dataset_manifest_sha256"] == dataset["manifest_sha256"]
            assert len(request["pose_split_manifest_sha256"]) == 64
            job.request_json = {
                **request,
                "pose_training_dataset_manifest_sha256": "0" * 64,
            }
            child_session.commit()
        return True

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="child job frozen manifest lineage changed"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="tampered-frozen-manifest-node",
            processor=substituted_manifest_processor,
        )

    # The first completion also rejects missing frozen lineage fields, even
    # when the worker preserves the dataset ID and valid checkpoint bytes.
    def removed_manifest_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as child_session:
            job = child_session.get(Job, job_id)
            assert job is not None
            request = dict(job.request_json)
            assert "pose_training_dataset_manifest_sha256" in request
            request.pop("pose_training_dataset_manifest_sha256")
            job.request_json = request
            child_session.commit()
        return True

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="child job request checksum changed"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="removed-frozen-manifest-node",
            processor=removed_manifest_processor,
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
    substituted_artifact_run_ids: list[str] = []

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
            substituted_artifact_run_ids.append(run.id)
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

    # Rejected first-completion replay must roll back checkpoint finalization.
    # The worker's completed run remains intact for scientific forensics.
    assert len(substituted_artifact_run_ids) == 1
    with app.state.session_factory() as session:
        run = session.get(TrainingRun, substituted_artifact_run_ids[0])
        assert run is not None and run.status == "completed"
        assert run.artifact_manifest_json["pose_schema_id"] == "substituted-pose-schema"
        assert "result_checkpoint_sha256" not in run.artifact_manifest_json

    # A completed worker may leave an experiment record with altered frozen
    # schema lineage even when the training run itself is still intact.
    # Finalization must reject that independent evidence before syncing digests.
    def altered_experiment_lineage_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as child_session:
            job = child_session.get(Job, job_id)
            assert job is not None
            run_id = str(job.request_json["training_run_id"])
            experiment = child_session.scalar(
                select(ExperimentRecord).where(ExperimentRecord.training_run_id == run_id)
            )
            assert experiment is not None
            experiment.artifact_manifest_json = {
                **dict(experiment.artifact_manifest_json or {}),
                "pose_schema_content_hash": "altered-experiment-schema",
            }
            child_session.commit()
        return True

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="experiment artifact provenance changed"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="tampered-experiment-artifact-node",
            processor=altered_experiment_lineage_processor,
        )

    # The worker's experiment registry also copies native training rows.
    # If those rows change independently, first completion must reject the
    # record instead of overwriting it with the training run's manifest.
    altered_native_run_ids: list[str] = []

    def altered_experiment_native_metrics_processor(
        settings: Settings,
        factory: sessionmaker[Session],
        job_id: str,
    ) -> bool:
        assert _fake_pose_processor(settings, factory, job_id)
        with factory() as child_session:
            job = child_session.get(Job, job_id)
            assert job is not None
            run_id = str(job.request_json["training_run_id"])
            altered_native_run_ids.append(run_id)
            experiment = child_session.scalar(
                select(ExperimentRecord).where(ExperimentRecord.training_run_id == run_id)
            )
            assert experiment is not None
            experiment.artifact_manifest_json = {
                **dict(experiment.artifact_manifest_json or {}),
                "native_results_rows": [{"epoch": 1, "metrics/mAP50-95(P)": 0.0}],
            }
            child_session.commit()
        return True

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="experiment artifact provenance changed"),
    ):
        create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={"training_config": {"epochs": 1}},
            workflow_run_id="saved-pose-run",
            workflow_node_run_id="tampered-experiment-native-metrics-node",
            processor=altered_experiment_native_metrics_processor,
        )
    assert len(altered_native_run_ids) == 1
    with app.state.session_factory() as session:
        run = session.get(TrainingRun, altered_native_run_ids[0])
        assert run is not None
        assert "result_checkpoint_sha256" not in dict(run.artifact_manifest_json or {})

    # The first completion must not commit newly pinned checkpoint digests
    # when the worker's independent experiment summary contradicts its run.
    # Exercise both comparison metrics and warnings from the API-frozen truth.
    for field, corrupted in (
        ("summary_metrics_json", {"metrics/mAP50-95(P)": 0.0}),
        ("comparison_warnings_json", ["altered-scientific-warning"]),
    ):
        created_run_ids: list[str] = []

        def altered_experiment_summary_processor(
            settings: Settings,
            factory: sessionmaker[Session],
            job_id: str,
            summary_field: str = field,
            summary_value: Any = corrupted,
            run_ids: list[str] = created_run_ids,
        ) -> bool:
            assert _fake_pose_processor(settings, factory, job_id)
            with factory() as child_session:
                job = child_session.get(Job, job_id)
                assert job is not None
                run_id = str(job.request_json["training_run_id"])
                run_ids.append(run_id)
                experiment = child_session.scalar(
                    select(ExperimentRecord).where(ExperimentRecord.training_run_id == run_id)
                )
                assert experiment is not None
                setattr(experiment, summary_field, summary_value)
                child_session.commit()
            return True

        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="experiment summary provenance changed"),
        ):
            create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=project_id,
                dataset_payload=payload,
                parameters={"training_config": {"epochs": 1}},
                workflow_run_id="saved-pose-run",
                workflow_node_run_id=f"altered-experiment-{field}",
                processor=altered_experiment_summary_processor,
            )
        assert len(created_run_ids) == 1
        with app.state.session_factory() as session:
            run = session.get(TrainingRun, created_run_ids[0])
            assert run is not None
            assert run.status == "completed"
            assert "result_checkpoint_sha256" not in dict(run.artifact_manifest_json or {})

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

    # A rejected, out-of-run checkpoint must never reach the file hasher,
    # even if the worker copied legitimate bytes into that other directory.
    with monkeypatch.context() as patch:
        patch.setattr(
            "reefvision.services.workflow_pose_training.hash_model_file",
            lambda _path: pytest.fail("Rejected pose checkpoint was hashed"),
        )
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


def test_pose_workflow_replay_rejects_non_object_snapshot(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise persisted, scientist-reviewed dataset provenance rather than
    # constructing a synthetic TrainingRun without its child job.
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    payload = {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "manifest_sha256": dataset["manifest_sha256"],
    }

    def execute() -> dict[str, Any]:
        with app.state.session_factory() as session:
            return create_pose_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload=payload,
                parameters={"device": "cpu", "training_config": {"epochs": 1}},
                workflow_run_id="snapshot-object-workflow",
                workflow_node_run_id="snapshot-object-node",
                processor=_fake_pose_processor,
            )

    result = execute()
    with app.state.session_factory() as session:
        run = session.get(TrainingRun, result["training_run_id"])
        assert run is not None
        original = dict(run.draft_snapshot_json or {})
        run.draft_snapshot_json = list(original.items())
        session.commit()

    with pytest.raises(ValidationError, match="snapshot must be a JSON object"):
        execute()


@pytest.mark.parametrize("payload", [None, [], [["dataset_id", "forged"]], "text", 7])
def test_pose_training_rejects_non_object_input_artifact_payloads(payload: object) -> None:
    # A persisted JSON list of pairs must not be coerced into trusted lineage.
    artifact = SimpleNamespace(payload_json=payload)
    with pytest.raises(ValidationError, match="must be a JSON object"):
        _single_payload({"training_dataset": [artifact]}, "training_dataset")
    with pytest.raises(ValidationError, match="must be a JSON object"):
        _optional_payload({"validation_dataset": [artifact]}, "validation_dataset")
