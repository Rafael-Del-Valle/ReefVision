"""Ultralytics pose retraining from immutable ReefVision pose truth."""
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import io
import json
import math
import re
import shutil
import stat
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
    PoseTrainingExportService,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import (
    resolve_managed_project_path,
)


def _safe_extract_zip(
    content: bytes,
    destination: Path,
) -> None:
    """Extract an in-memory pose dataset without allowing path traversal."""

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    root = destination.resolve()

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        # Preflight every entry before extracting any files. Aliases such as
        # ./data.yaml and data.yaml otherwise overwrite the same scientific
        # artifact, while case-only aliases behave differently on Windows.
        seen_paths: set[str] = set()
        file_paths: set[str] = set()
        windows_device_names = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        for prefix in ("COM", "LPT"):
            for digit in "123456789¹²³":
                windows_device_names.add(f"{prefix}{digit}")
        for item in archive.infolist():
            # Reviewed exports contain only regular files and directories.
            # A Unix link or device entry must never masquerade as image truth.
            if item.create_system == 3 and stat.S_IFMT(item.external_attr >> 16) not in (
                0,
                stat.S_IFREG,
                stat.S_IFDIR,
            ):
                raise ValidationError("Pose training export contains a special archive member")
            relative = Path(item.filename.replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValidationError("Pose training export contains an unsafe archive path")
            # Windows ignores trailing dots and spaces in ordinary file paths.
            # Reject these aliases before any reviewed image bytes are written.
            if any(part.rstrip(" .") != part for part in relative.parts):
                raise ValidationError("Pose training export contains a noncanonical archive path")
            # NTFS device names, alternate data streams and invalid path
            # characters must never alter reviewed training artifacts.
            if any(
                any(ord(char) < 32 or char in '<>:"|?*' for char in part)
                or part.split(".", 1)[0].upper() in windows_device_names
                for part in relative.parts
            ):
                raise ValidationError("Pose training export contains a Windows-unsafe archive path")
            key = "/".join(relative.parts).casefold()
            if not key or key in seen_paths:
                raise ValidationError("Pose training export contains a duplicate archive path")
            seen_paths.add(key)
            if not item.is_dir():
                file_paths.add(key)

        # A file cannot also be a parent directory, even when that directory
        # appears only implicitly in another ZIP entry. Check all paths before
        # writing any verified training data.
        for key in seen_paths:
            components = key.split("/")
            if any(
                "/".join(components[:index]) in file_paths for index in range(1, len(components))
            ):
                raise ValidationError(
                    "Pose training export contains a file-directory archive collision"
                )

        for item in archive.infolist():
            normalized = item.filename.replace(
                "\\",
                "/",
            )

            relative = Path(normalized)

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


def _verify_pose_export_frame_pairs(
    source_root: Path,
    *,
    class_count: int,
    keypoint_count: int,
) -> None:
    """Require one exported annotation file for each frozen PNG frame."""

    images = source_root / "images" / "train"
    labels = source_root / "labels" / "train"
    if not images.is_dir() or not labels.is_dir():
        raise ValidationError("Ultralytics pose export is missing frame images or labels")

    image_files = list(images.iterdir())
    label_files = list(labels.iterdir())
    if (
        not image_files
        or any(not path.is_file() or path.suffix != ".png" for path in image_files)
        or any(not path.is_file() or path.suffix != ".txt" for path in label_files)
        or {path.stem for path in image_files} != {path.stem for path in label_files}
    ):
        raise ValidationError("Ultralytics pose export has unmatched image/label frame sets")

    # An annotation referring to an absent class would be silently
    # misinterpreted or fail only after an expensive offline GPU launch.
    # Check both frozen training truth and independently reviewed validation.
    for label_path in label_files:
        rows = label_path.read_text(encoding="utf-8").splitlines()
        if not rows:
            raise ValidationError("Ultralytics pose export contains an invalid label class index")
        for row in rows:
            tokens = row.split()
            if (
                not tokens
                or re.fullmatch(r"(0|[1-9][0-9]*)", tokens[0]) is None
                or int(tokens[0]) >= class_count
            ):
                raise ValidationError(
                    "Ultralytics pose export contains an invalid label class index"
                )

            # Each reviewed pose must have class, normalized box geometry,
            # and exactly three values for every frozen schema landmark.
            if len(tokens) != 5 + 3 * keypoint_count:
                raise ValidationError("Ultralytics pose export has invalid landmark layout")
            try:
                numbers = [float(value) for value in tokens[1:]]
            except ValueError as exc:
                raise ValidationError("Ultralytics pose export has invalid label coordinates") from exc
            if (
                not all(math.isfinite(value) for value in numbers)
                or not all(0 <= value <= 1 for value in numbers[:4])
                or numbers[2] <= 0
                or numbers[3] <= 0
                or any(
                    not (
                        0 <= numbers[index] <= 1
                        and 0 <= numbers[index + 1] <= 1
                        and numbers[index + 2] in (0, 1, 2)
                    )
                    for index in range(4, len(numbers), 3)
                )
            ):
                raise ValidationError("Ultralytics pose export has invalid label coordinates")


def _copy_split(
    source_root: Path,
    destination_root: Path,
    *,
    split_name: str,
    class_count: int,
    keypoint_count: int,
) -> None:
    """Copy one exported Ultralytics train split into another named split."""

    source_images = source_root / "images" / "train"
    source_labels = source_root / "labels" / "train"

    if not source_images.is_dir():
        raise ValidationError("Ultralytics pose export is missing images/train")

    if not source_labels.is_dir():
        raise ValidationError("Ultralytics pose export is missing labels/train")

    _verify_pose_export_frame_pairs(
        source_root,
        class_count=class_count,
        keypoint_count=keypoint_count,
    )

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
            shutil.copy2(
                source,
                target_labels / source.name,
            )


def materialize_pose_training_exports(
    *,
    training_content: bytes,
    validation_content: bytes | None,
    destination: Path,
) -> dict[str, object]:
    """Materialize immutable pose exports without reusing train frames as validation."""

    # The destination is deleted and rebuilt on each training run. A symlink
    # here (or in an ancestor) could redirect exported scientific data outside
    # the managed run; a pre-existing validation-stage symlink is just as unsafe.
    if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents):
        raise ValidationError("Pose training export destination contains a symbolic link")
    validation_stage = destination.parent / f".{destination.name}-validation"
    if validation_content is not None and validation_stage.is_symlink():
        raise ValidationError("Pose training validation staging path is a symbolic link")

    shutil.rmtree(
        destination,
        ignore_errors=True,
    )

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

    # The internal frozen-data exporter writes a canonical dataset header.
    # A substring check could accept comments or duplicate YAML keys, allowing
    # a later train/val/path declaration to silently redirect scientific data.
    top_level = [line for line in yaml_text.splitlines() if line and not line[0].isspace()]
    if (
        len(top_level) != 6
        or top_level[:3] != ["path: .", "train: images/train", "val: images/train"]
        or re.fullmatch(r"kpt_shape: \[[1-9]\d*, 3\]", top_level[3]) is None
        or top_level[4:] != ["names:", "reefvision_keypoint_names:"]
    ):
        raise ValidationError("Ultralytics pose export has a noncanonical data.yaml")

    # Require the nested class map and ordered landmarks to match the
    # canonical frozen exporter too. The six outer YAML keys alone do not
    # detect duplicate class indices or extra keypoints within a section.
    yaml_lines = yaml_text.splitlines()
    landmark_header = yaml_lines.index("reefvision_keypoint_names:")
    class_lines = yaml_lines[5:landmark_header]
    landmark_lines = yaml_lines[landmark_header + 1 :]
    expected_landmarks = int(top_level[3].split("[", 1)[1].split(",", 1)[0])
    if not class_lines or len(landmark_lines) != expected_landmarks:
        raise ValidationError("Ultralytics pose export has noncanonical class/keypoint metadata")

    try:
        for index, line in enumerate(class_lines):
            prefix = f"  {index}: "
            if not line.startswith(prefix):
                raise ValueError("Unexpected class index")
            display_name = json.loads(line[len(prefix) :])
            if not isinstance(display_name, str) or json.dumps(display_name) != line[len(prefix) :]:
                raise ValueError("Unexpected class display name")

        for line in landmark_lines:
            if not line.startswith("  - "):
                raise ValueError("Unexpected landmark entry")
            landmark_name = json.loads(line[4:])
            if not isinstance(landmark_name, str) or json.dumps(landmark_name) != line[4:]:
                raise ValueError("Unexpected landmark name")
    except ValueError as exc:
        raise ValidationError(
            "Ultralytics pose export has noncanonical class/keypoint metadata"
        ) from exc

    _verify_pose_export_frame_pairs(
        destination,
        class_count=len(class_lines),
        keypoint_count=expected_landmarks,
    )

    validation_mode = "none"

    if validation_content is not None:
        validation_stage = destination.parent / f".{destination.name}-validation"

        shutil.rmtree(
            validation_stage,
            ignore_errors=True,
        )

        try:
            _safe_extract_zip(
                validation_content,
                validation_stage,
            )

            # A separate frozen split must use exactly the training export's
            # landmark ordering and class map. Otherwise Ultralytics silently
            # interprets validation labels using the wrong scientific schema.
            validation_yaml = validation_stage / "data.yaml"
            if (
                not validation_yaml.is_file()
                or validation_yaml.read_text(encoding="utf-8") != yaml_text
            ):
                raise ValidationError(
                    "Ultralytics pose validation export has incompatible data.yaml"
                )

            _copy_split(
                validation_stage,
                destination,
                split_name="val",
                class_count=len(class_lines),
                keypoint_count=expected_landmarks,
            )
        finally:
            shutil.rmtree(
                validation_stage,
                ignore_errors=True,
            )

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
    yaml_path.write_text(
        yaml_text,
        encoding="utf-8",
    )

    return {
        "validation_mode": validation_mode,
        "data_yaml": str(yaml_path),
        "training_image_count": len(list((destination / "images" / "train").glob("*"))),
        "validation_image_count": (
            len(list((destination / "images" / "val").glob("*")))
            if validation_content is not None
            else 0
        ),
    }


def process_pose_training_job(
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

            # A saved Workflow Builder job seals the exact frozen source and
            # split digests at queue time. Verify them before exporting a single
            # training image or starting the GPU, not only after completion.
            if job.project_id != run.project_id or run.job_id != job.id:
                raise ValidationError("Queued pose training job ownership changed")
            request = job.request_json
            snapshot = run.draft_snapshot_json
            sealed_digest = (
                snapshot.get("pose_child_job_request_sha256")
                if isinstance(snapshot, dict)
                else None
            )
            if sealed_digest is not None and (
                not isinstance(sealed_digest, str)
                or sealed_digest != canonical_json_sha256(request)
            ):
                raise ValidationError("Queued pose training child job request checksum changed")
            expected_lineage = {
                "pose_training_dataset_id": training_dataset.id,
                "pose_training_dataset_manifest_sha256": training_dataset.manifest_sha256,
                "pose_validation_dataset_id": (
                    validation_dataset.id if validation_dataset is not None else None
                ),
                "pose_validation_dataset_manifest_sha256": (
                    validation_dataset.manifest_sha256 if validation_dataset is not None else None
                ),
                "pose_split_manifest_sha256": run.split_manifest_sha256,
            }
            for field, expected_value in expected_lineage.items():
                if (sealed_digest is not None and field not in request) or (
                    field in request and request[field] != expected_value
                ):
                    raise ValidationError("Queued pose training frozen dataset lineage changed")

            # The sealed request also has to agree with its persisted run and
            # scientist-reviewed snapshot. A queued run's source manifest can
            # otherwise drift independently of the child job request.
            if sealed_digest is not None and (
                run.dataset_manifest_sha256 != training_dataset.manifest_sha256
                or snapshot.get("pose_training_dataset_id") != training_dataset.id
                or snapshot.get("pose_training_dataset_manifest_sha256")
                != training_dataset.manifest_sha256
                or snapshot.get("pose_validation_dataset_id")
                != (validation_dataset.id if validation_dataset is not None else None)
                or snapshot.get("pose_validation_dataset_manifest_sha256")
                != (validation_dataset.manifest_sha256 if validation_dataset is not None else None)
            ):
                raise ValidationError("Queued pose training frozen snapshot lineage changed")

            # A sealed Workflow Builder child must also retain the frozen
            # train/validation split definition, not just its stored digest.
            # Detect changed snapshot contents before exporting reviewed frames.
            if sealed_digest is not None and (
                not isinstance(snapshot.get("split_manifest"), dict)
                or canonical_json_sha256(snapshot["split_manifest"]) != run.split_manifest_sha256
            ):
                raise ValidationError("Queued pose training frozen split manifest changed")

            # Independently verify the scientist-reviewed snapshot's landmark
            # schema before exporting data or starting the GPU. Dataset identity
            # alone cannot detect an altered saved keypoint definition.
            if sealed_digest is not None and (
                snapshot.get("pose_schema_id") != training_dataset.pose_schema_id
                or snapshot.get("pose_schema_revision") != training_dataset.pose_schema_revision
                or snapshot.get("pose_schema_content_hash")
                != training_dataset.pose_schema_content_hash
            ):
                raise ValidationError("Queued pose training frozen schema lineage changed")

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

            shutil.rmtree(
                save_root,
                ignore_errors=True,
            )

            save_root.mkdir(
                parents=True,
                exist_ok=True,
            )

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
                    "project": str(
                        resolve_managed_project_path(
                            settings,
                            f"{base_relative}/runs",
                        )
                    ),
                    "name": "pose",
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
