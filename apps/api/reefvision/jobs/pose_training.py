"""Ultralytics pose retraining from immutable ReefVision pose truth."""
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import io
import json
import shutil
import sys
import zipfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    PoseTrainingDataset,
    Project,
    TrainingRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.training import (
    _append_log,
    _collect_training_results,
    _complete_training_run,
    _on_fit_epoch_end,
    _on_train_end,
    _on_train_start,
    _relative_to_data_dir,
    _resolve_model_source,
)
from reefvision.ml.adapters.ultralytics_training import (
    configure_local_training_runtime,
    local_training_arguments,
    pose_trainer_class,
)
from reefvision.ml.dependencies import (
    configure_provider_runtime,
    require_provider_ready,
)
from reefvision.ml.providers import resolve_torch_device
from reefvision.services.pose_training_exports import (
    EXPORT_MANIFEST_FILENAME,
    PoseTrainingExportService,
)
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import (
    resolve_managed_project_path,
)


def _safe_extract_zip(
    content: bytes,
    destination: Path,
) -> None:
    """Extract an in-memory pose dataset without allowing path traversal."""

    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ValidationError(
            f"Pose export stage {destination.name} already exists; "
            "refusing to overwrite prior scientific data"
        ) from error

    try:
        root = destination.resolve()

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for item in archive.infolist():
                normalized = item.filename.replace(
                    "\\",
                    "/",
                )

                relative = Path(normalized)

                if relative.is_absolute() or ".." in relative.parts:
                    raise ValidationError("Pose training export contains an unsafe archive path")

                target = (destination / relative).resolve()

                if not target.is_relative_to(root):
                    raise ValidationError("Pose training export escaped the managed dataset root")

                if item.is_dir():
                    target.mkdir(
                        parents=True,
                        exist_ok=True,
                    )
                    continue

                target.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                with (
                    archive.open(item) as source,
                    target.open("wb") as output,
                ):
                    shutil.copyfileobj(
                        source,
                        output,
                    )
    except BaseException:
        shutil.rmtree(destination)
        raise


def _frozen_pose_class_indices(content: bytes) -> dict[str, int]:
    """Read the stable class IDs bound to the export's split-local YOLO indices."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            manifest = json.loads(archive.read(EXPORT_MANIFEST_FILENAME))
    except (KeyError, ValueError, zipfile.BadZipFile) as error:
        raise ValidationError("Pose export is missing its frozen class mapping") from error

    classes = manifest.get("classes") if isinstance(manifest, dict) else None
    if not isinstance(classes, list) or not classes:
        raise ValidationError("Pose export is missing its frozen class mapping")

    indices: dict[str, int] = {}
    for record in classes:
        if not isinstance(record, dict):
            raise ValidationError("Pose export has an invalid frozen class mapping")
        label_id = record.get("label_class_id")
        index = record.get("class_index")
        if (
            not isinstance(label_id, str)
            or not label_id
            or label_id in indices
            or type(index) is not int
        ):
            raise ValidationError("Pose export has an invalid frozen class mapping")
        indices[label_id] = index
    if sorted(indices.values()) != list(range(len(indices))):
        raise ValidationError("Pose export has an invalid frozen class mapping")
    return indices


def _copy_split(
    source_root: Path,
    destination_root: Path,
    *,
    split_name: str,
    class_projection: dict[int, int],
) -> None:
    """Copy validation images and project their labels into the training class indices."""

    source_images = source_root / "images" / "train"
    source_labels = source_root / "labels" / "train"

    if not source_images.is_dir():
        raise ValidationError("Ultralytics pose export is missing images/train")

    if not source_labels.is_dir():
        raise ValidationError("Ultralytics pose export is missing labels/train")

    target_images = destination_root / "images" / split_name
    target_labels = destination_root / "labels" / split_name

    target_images.mkdir(
        parents=True,
        exist_ok=True,
    )
    target_labels.mkdir(
        parents=True,
        exist_ok=True,
    )

    for source in sorted(source_images.iterdir()):
        if source.is_file():
            shutil.copy2(
                source,
                target_images / source.name,
            )

    for source in sorted(source_labels.iterdir()):
        if source.is_file():
            projected_rows = []
            for row in source.read_text(encoding="utf-8").splitlines(keepends=True):
                if not row.strip():
                    projected_rows.append(row)
                    continue
                index, separator, pose = row.partition(" ")
                try:
                    projected_index = class_projection[int(index)]
                except (KeyError, ValueError) as error:
                    raise ValidationError(
                        "Pose validation label references an unknown export class index"
                    ) from error
                projected_rows.append(f"{projected_index}{separator}{pose}")
            (target_labels / source.name).write_text(
                "".join(projected_rows), encoding="utf-8", newline="\n"
            )


def materialize_pose_training_exports(
    *,
    training_content: bytes,
    validation_content: bytes | None,
    destination: Path,
) -> dict[str, object]:
    """Materialize immutable pose exports without reusing train frames as validation."""

    validation_stage = destination.parent / f".{destination.name}-validation"
    if validation_content is not None and (
        validation_stage.exists() or validation_stage.is_symlink()
    ):
        raise ValidationError(
            f"Pose export stage {validation_stage.name} already exists; "
            "refusing to overwrite prior scientific data"
        )

    class_projection: list[tuple[str, int, int]] = []
    if validation_content is not None:
        training_classes = _frozen_pose_class_indices(training_content)
        validation_classes = _frozen_pose_class_indices(validation_content)
        if missing := validation_classes.keys() - training_classes.keys():
            raise ValidationError(
                "Validation classes were not present in training ("
                + ", ".join(sorted(missing))
                + ")"
            )
        class_projection = [
            (label_id, index, training_classes[label_id])
            for label_id, index in validation_classes.items()
        ]

    _safe_extract_zip(
        training_content,
        destination,
    )

    yaml_path = destination / "data.yaml"

    if not yaml_path.is_file():
        raise ValidationError("Ultralytics pose export is missing data.yaml")

    yaml_text = yaml_path.read_text(
        encoding="utf-8",
    )

    if "train: images/train" not in yaml_text:
        raise ValidationError("Ultralytics pose export has an unexpected training path")

    validation_mode = "none"

    if validation_content is not None:
        # The exclusive directory claim can fail after the precheck.
        # Its cleanup belongs to the worker that actually acquired it.
        _safe_extract_zip(
            validation_content,
            validation_stage,
        )
        try:
            _copy_split(
                validation_stage,
                destination,
                split_name="val",
                class_projection={old: new for _, old, new in class_projection},
            )
        finally:
            shutil.rmtree(validation_stage)

        if "val: images/train" in yaml_text:
            yaml_text = yaml_text.replace(
                "val: images/train",
                "val: images/val",
                1,
            )
        elif "val:" not in yaml_text:
            yaml_text += "val: images/val\n"
        else:
            raise ValidationError("Ultralytics pose export has an unexpected validation path")

        validation_mode = "separate_frozen_pose_dataset"

    # When no separate validation dataset is supplied, data.yaml may
    # retain the interoperability export's val: images/train entry.
    # The production runner explicitly forces val=False in that case.
    # Therefore those frames are never silently treated as validation.
    # Ultralytics resolves an explicit `path: .` against its working directory.
    # Omitting this portable export header roots the splits at the managed YAML.
    yaml_path.write_text(
        yaml_text.removeprefix("path: .\n"),
        encoding="utf-8",
    )

    return {
        "validation_class_projection": [
            {
                "label_class_id": label_id,
                "validation_class_index": old,
                "training_class_index": new,
            }
            for label_id, old, new in class_projection
        ],
        "validation_mode": validation_mode,
        "data_yaml": str(yaml_path),
        "training_image_count": len(list((destination / "images" / "train").glob("*"))),
        "validation_image_count": (
            len(list((destination / "images" / "val").glob("*")))
            if validation_content is not None
            else 0
        ),
    }


def _claim_pose_training_output(output: Path) -> None:
    """Reserve a fresh log or trainer directory without deleting a prior run's evidence."""
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ValidationError(
            f"Pose training output {output.name} already exists; "
            "refusing to overwrite prior artifacts"
        ) from error


def _process_ultralytics_pose_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    """Run one real Ultralytics pose-training child job."""

    run_id: str | None = None

    with factory() as session:
        job = session.get(
            Job,
            job_id,
        )

        if job is None or job.job_type != "training" or job.status != "queued":
            return False

        run_id = str(job.request_json.get("training_run_id") or "")

        run = session.get(
            TrainingRun,
            run_id,
        )

        if run is None:
            job.status = "failed"
            job.error_message = "Pose training run is missing"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False

        run.status = "preflight"
        run.stage = "preflight"
        run.started_at = datetime.now(UTC)
        run.error_message = None

        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        job.result_json = {
            "stage": "preflight",
            "task": "pose",
        }

        session.commit()

    try:
        with factory() as session:
            run = session.get(
                TrainingRun,
                run_id,
            )
            job = session.get(
                Job,
                job_id,
            )

            if run is None or job is None:
                raise RuntimeError("Pose training run or job disappeared")

            if run.task != "pose":
                raise ValidationError("Pose trainer can execute only task=pose")

            if run.provider_id != "ultralytics":
                raise ValidationError("Phase 10B pose training requires the Ultralytics provider")

            training_dataset_id = str(job.request_json.get("pose_training_dataset_id") or "")

            validation_dataset_id = (
                str(job.request_json.get("pose_validation_dataset_id") or "") or None
            )

            training_dataset = session.get(
                PoseTrainingDataset,
                training_dataset_id,
            )

            if training_dataset is None or training_dataset.project_id != run.project_id:
                raise ValidationError("Pose training dataset is unavailable")

            validation_dataset = (
                session.get(
                    PoseTrainingDataset,
                    validation_dataset_id,
                )
                if validation_dataset_id
                else None
            )

            if validation_dataset_id and (
                validation_dataset is None or validation_dataset.project_id != run.project_id
            ):
                raise ValidationError("Pose validation dataset is unavailable")

            project = session.get(
                Project,
                run.project_id,
            )

            if project is None:
                raise ValidationError("Pose training project is unavailable")

            if run.initial_checkpoint_source == "scratch":
                if run.initial_checkpoint_model_id:
                    raise ValidationError("Random pose initialization cannot use a seed checkpoint")
                if run.architecture not in {f"yolo11{scale}-pose.yaml" for scale in "nslmx"}:
                    raise ValidationError(
                        "Random pose training requires a YOLO11 pose architecture"
                    )
            elif run.initial_checkpoint_source != "registered_model":
                raise ValidationError(
                    "Pose training requires random or registered_model initialization"
                )
            checkpoint_source = _resolve_model_source(settings, session, run)
            if run.initial_checkpoint_model_id:
                # Recheck schema and checksum at execution, after any queue delay.
                from reefvision.services.workflow_pose_training import _seed_pose_model

                _seed_pose_model(
                    session,
                    settings,
                    project_id=run.project_id,
                    payload={"model_id": run.initial_checkpoint_model_id},
                    dataset=training_dataset,
                )

            require_provider_ready(
                "ultralytics",
                settings,
            )

            run.status = "preparing_dataset"
            run.stage = "preparing_dataset"

            job.result_json = {
                "stage": "preparing_dataset",
                "task": "pose",
            }

            session.commit()

            exporter = PoseTrainingExportService(
                session,
                settings,
            )

            training_export = exporter.export(
                training_dataset.id,
                "ultralytics_pose",
            )

            validation_export = (
                exporter.export(
                    validation_dataset.id,
                    "ultralytics_pose",
                )
                if validation_dataset is not None
                else None
            )

            base_relative = f"{project.storage_root}/training/{run.id}"

            dataset_relative = f"{base_relative}/pose-dataset"

            dataset_root = resolve_managed_project_path(
                settings,
                dataset_relative,
            )

            materialized = materialize_pose_training_exports(
                training_content=(training_export.content),
                validation_content=(
                    validation_export.content if validation_export is not None else None
                ),
                destination=dataset_root,
            )

            save_root = resolve_managed_project_path(
                settings,
                f"{base_relative}/ultralytics",
            )
            _claim_pose_training_output(save_root)
            trainer_root = resolve_managed_project_path(settings, f"{base_relative}/runs/pose")
            _claim_pose_training_output(trainer_root)

            logs_path = save_root / "training.log"

            _append_log(
                logs_path,
                (
                    f"[{datetime.now(UTC).isoformat()}] "
                    "immutable scientist-verified pose "
                    "dataset prepared"
                ),
            )

            configure_provider_runtime(settings)

            run.status = "training"
            run.stage = "training"
            run.logs_path = _relative_to_data_dir(
                settings,
                logs_path,
            )

            run.artifact_manifest_json = {
                **dict(run.artifact_manifest_json or {}),
                "initialization_mode": "registered_model"
                if run.initial_checkpoint_model_id
                else "random",
                "effective_precision": "fp32",
                "pretrained": False,
                "task": "pose",
                "dataset_format": ("ultralytics_pose"),
                "pose_training_dataset_id": (training_dataset.id),
                "pose_training_dataset_manifest_sha256": (training_dataset.manifest_sha256),
                "pose_validation_dataset_id": (
                    validation_dataset.id if validation_dataset is not None else None
                ),
                "pose_validation_dataset_manifest_sha256": (
                    validation_dataset.manifest_sha256 if validation_dataset is not None else None
                ),
                "pose_schema_id": (training_dataset.pose_schema_id),
                "pose_schema_revision": (training_dataset.pose_schema_revision),
                "pose_schema_content_hash": (training_dataset.pose_schema_content_hash),
                "validation_mode": (materialized["validation_mode"]),
                "validation_class_projection": materialized["validation_class_projection"],
                "training_export_bundle_sha256": (training_export.bundle_sha256),
                "validation_export_bundle_sha256": (
                    validation_export.bundle_sha256 if validation_export is not None else None
                ),
                "dataset_output_path": (dataset_relative),
                "materialization": materialized,
            }

            job.result_json = {
                "stage": "training",
                "task": "pose",
                "dataset_output_path": (dataset_relative),
                "validation_mode": (materialized["validation_mode"]),
            }

            session.commit()

        configure_local_training_runtime(settings)

        from ultralytics import YOLO

        cancellation_requested = {"value": False}

        model = YOLO(checkpoint_source)

        last_reported_epoch = {"value": 0}

        def report_fit_epoch_end(
            trainer: Any,
        ) -> None:
            total = int(
                getattr(
                    trainer,
                    "epochs",
                    0,
                )
            )

            epoch = min(
                int(
                    getattr(
                        trainer,
                        "epoch",
                        0,
                    )
                )
                + 1,
                total,
            )

            if epoch <= last_reported_epoch["value"]:
                return

            _on_fit_epoch_end(
                settings,
                factory,
                job_id,
                run_id,
                trainer,
                cancellation_requested,
            )

            last_reported_epoch["value"] = epoch

        def report_train_start(
            trainer: Any,
        ) -> None:
            last_reported_epoch["value"] = 0

            _on_train_start(
                settings,
                factory,
                job_id,
                run_id,
                trainer,
            )

        model.add_callback(
            "on_fit_epoch_end",
            report_fit_epoch_end,
        )

        model.add_callback(
            "on_train_start",
            report_train_start,
        )

        model.add_callback(
            "on_train_end",
            lambda trainer: _on_train_end(
                settings,
                factory,
                job_id,
                run_id,
                trainer,
            ),
        )

        with factory() as session:
            run = session.get(
                TrainingRun,
                run_id,
            )

            job = session.get(
                Job,
                job_id,
            )

            if run is None or job is None:
                raise RuntimeError("Pose training run disappeared before launch")

            project = session.get(
                Project,
                run.project_id,
            )

            if project is None:
                raise RuntimeError("Pose training project disappeared before launch")

            base_relative = f"{project.storage_root}/training/{run.id}"

            dataset_root = resolve_managed_project_path(
                settings,
                f"{base_relative}/pose-dataset",
            )

            train_args = dict(run.training_config_json or {})

            if sys.platform == "win32":
                train_args["workers"] = 0

            train_args["amp"] = False
            if run.precision == "amp":
                run.warnings_json = [
                    *list(run.warnings_json or []),
                    "AMP requires an upstream pretrained-weight check; this run uses fp32 offline.",
                ]
                session.commit()

            if run.random_seed is not None:
                train_args["seed"] = run.random_seed

            validation_mode = str(
                dict(run.artifact_manifest_json or {}).get("validation_mode") or "none"
            )

            train_args.update(
                {
                    "data": str(dataset_root / "data.yaml"),
                    "device": (resolve_torch_device(run.device)),
                    "project": str(trainer_root.parent),
                    "name": trainer_root.name,
                    # This is the exact directory this worker already claimed.
                    "exist_ok": True,
                    "save": True,
                    "verbose": False,
                    # Never evaluate the training frames as if
                    # they were independent validation truth.
                    "val": (validation_mode == "separate_frozen_pose_dataset"),
                }
            )

            _append_log(
                resolve_managed_project_path(
                    settings,
                    run.logs_path or "",
                ),
                (
                    f"[{datetime.now(UTC).isoformat()}] "
                    "launching Ultralytics pose retraining; "
                    f"validation_mode={validation_mode}"
                ),
            )

        model.train(trainer=pose_trainer_class(), **local_training_arguments(train_args))

        with factory() as session:
            run = session.get(
                TrainingRun,
                run_id,
            )

            job = session.get(
                Job,
                job_id,
            )

            if run is None or job is None:
                raise RuntimeError("Pose training run disappeared after execution")

            trainer = model.trainer

            if trainer is None:
                raise RuntimeError("Ultralytics pose trainer unavailable after execution")

            save_dir = Path(str(trainer.save_dir)).resolve()

            results_csv = save_dir / "results.csv"

            _collect_training_results(
                settings,
                run,
                job,
                save_dir,
                results_csv,
                tuning_enabled=False,
            )

            manifest = dict(run.artifact_manifest_json or {})

            validation_mode = str(manifest.get("validation_mode") or "none")

            if validation_mode == "none":
                warning = (
                    "Pose retraining used no separate "
                    "validation dataset. Training metrics "
                    "must not be interpreted as independent "
                    "validation performance."
                )

                warnings = list(run.warnings_json or [])

                if warning not in warnings:
                    warnings.append(warning)

                run.warnings_json = warnings

            if cancellation_requested["value"] or job.status == "cancel_requested":
                job.status = "cancelled"
                run.status = "cancelled"
                run.stage = "cancelled"

                _append_log(
                    resolve_managed_project_path(
                        settings,
                        run.logs_path or "",
                    ),
                    (f"[{datetime.now(UTC).isoformat()}] pose training cancelled"),
                )
            else:
                if not run.result_checkpoint_path:
                    raise ValidationError("Completed pose training did not produce a checkpoint")
                selected = resolve_managed_project_path(settings, run.result_checkpoint_path)
                checksum, size = hash_model_file(selected)
                if not size:
                    raise ValidationError("Completed pose training checkpoint is empty")
                run.artifact_manifest_json = {
                    **run.artifact_manifest_json,
                    "result_checkpoint_sha256": checksum,
                }
                _complete_training_run(
                    session,
                    run,
                    job,
                )

                _append_log(
                    resolve_managed_project_path(
                        settings,
                        run.logs_path or "",
                    ),
                    (f"[{datetime.now(UTC).isoformat()}] pose training completed"),
                )

            run.completed_at = datetime.now(UTC)
            job.completed_at = datetime.now(UTC)

            session.commit()

        return True

    except Exception as exc:
        with factory() as session:
            job = session.get(
                Job,
                job_id,
            )

            run = (
                session.get(
                    TrainingRun,
                    run_id,
                )
                if run_id
                else None
            )

            cancelled = job is not None and job.status == "cancel_requested"

            final_status = "cancelled" if cancelled else "failed"

            if job is not None:
                job.status = final_status
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)

            if run is not None:
                run.status = final_status
                run.stage = final_status
                run.error_message = str(exc)
                run.completed_at = datetime.now(UTC)

                if run.logs_path:
                    with suppress(Exception):
                        _append_log(
                            resolve_managed_project_path(
                                settings,
                                run.logs_path,
                            ),
                            (f"[{datetime.now(UTC).isoformat()}] failure: {exc}"),
                        )

            session.commit()

        return False


def process_pose_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    """Dispatch one pose-training job to its persisted provider."""

    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "training" or job.status != "queued":
            return False
        run_id = str(job.request_json.get("training_run_id") or "")
        run = session.get(TrainingRun, run_id)
        if run is None:
            return _process_ultralytics_pose_training_job(settings, factory, job_id)
        provider_id = run.provider_id
    if provider_id == "reefpose":
        from reefvision.jobs.reefpose_training import process_reefpose_training_job

        return process_reefpose_training_job(settings, factory, job_id)
    return _process_ultralytics_pose_training_job(settings, factory, job_id)
