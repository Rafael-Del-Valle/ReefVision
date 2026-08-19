"""Ultralytics training from immutable image/mask/fragment classification snapshots."""

from __future__ import annotations

import shutil
import zipfile
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ClassificationDatasetSample,
    ClassificationDatasetSnapshot,
    ExperimentRecord,
    ImageAsset,
    Job,
    MaskAnnotation,
    Project,
    TrainingRun,
)
from reefvision.jobs.classification_inference import _masked_crop, _padded_bounds
from reefvision.jobs.classification_training import _model_source
from reefvision.jobs.training import (
    _append_log,
    _last_metrics,
    _on_fit_epoch_end,
    _on_train_end,
    _on_train_start,
    _package_versions_snapshot,
    _read_results_csv,
    _relative_to_data_dir,
)
from reefvision.ml.classification import CLASSIFICATION_TASK
from reefvision.ml.training_devices import resolve_training_device
from reefvision.storage.classification_exports import (
    CLASSIFICATION_SPLIT_DIRECTORIES,
    classification_class_key,
)
from reefvision.storage.datasets import canonical_json_bytes, canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path


_METADATA_CONFIG_KEYS = {
    "classification_dataset_snapshot_id",
    "classification_scope",
    "classification_label_set_id",
    "classification_label_set_key",
    "classification_cardinality",
    "classification_mode",
    "minimum_crop_size_px",
    "padding_fraction",
    "mask_background",
}


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mask_geometry(mask: MaskAnnotation) -> dict[str, Any]:
    """Match the immutable geometry contract used by ClassificationDatasetService."""

    return {
        "geometry_kind": mask.geometry_kind,
        "mask_path": mask.mask_path,
        "polygon_json": mask.polygon_json,
        "bounds": [mask.x_min, mask.y_min, mask.x_max, mask.y_max],
        "area_pixels": mask.area_pixels,
        "revision": mask.revision,
        "status": mask.status,
        "provenance_json": mask.provenance_json or {},
    }


def _sample_payload(sample: ClassificationDatasetSample) -> dict[str, Any]:
    return {
        "target_kind": sample.target_kind,
        "target_key": sample.target_key,
        "image_id": sample.image_id,
        "image_sha256": sample.source_image_sha256,
        "mask_annotation_id": sample.mask_annotation_id,
        "fragment_key": sample.fragment_key,
        "label_class_ids": list(sample.label_class_ids_json or []),
        "assignment_ids": list(sample.assignment_ids_json or []),
        "assignment_revisions": dict(sample.assignment_revisions_json or {}),
        "target_revision": sample.target_revision,
        "target_checksum": sample.target_checksum,
        "geometry": dict(sample.geometry_json or {}),
    }


def _classification_class_map(
    snapshot: ClassificationDatasetSnapshot,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    by_class_id: dict[str, dict[str, Any]] = {}
    output: dict[str, dict[str, Any]] = {}
    for raw in snapshot.class_map_json or []:
        class_record = dict(raw)
        class_id = str(class_record.get("id") or "")
        if not class_id:
            raise RuntimeError("Classification snapshot contains a class without an id")
        resolved = classification_class_key(class_record, mode="multiclass")
        if resolved is None:
            raise RuntimeError("Classification snapshot class could not be materialized")
        class_key, class_label = resolved
        if class_key in output:
            raise RuntimeError("Classification snapshot produces duplicate dataset class folders")
        by_class_id[class_id] = class_record
        output[class_key] = {
            "label": class_label,
            "label_class_id": class_id,
            "class_index": int(class_record["class_index"]),
            "scientific_name": class_record.get("scientific_name"),
            "state_name": class_record.get("state_name"),
        }
    if len(output) < 2:
        raise RuntimeError("Classification snapshot must expose at least two classes")
    folder_by_class_id = {
        str(metadata["label_class_id"]): class_key
        for class_key, metadata in output.items()
    }
    return output, folder_by_class_id


def _validate_source_image(sample: ClassificationDatasetSample, image: ImageAsset) -> Path:
    if image.sha256.casefold() != sample.source_image_sha256.casefold():
        raise RuntimeError(
            f"Source image changed after classification snapshot creation: {sample.image_id}"
        )
    if (
        image.width_px != sample.source_image_width_px
        or image.height_px != sample.source_image_height_px
    ):
        raise RuntimeError(
            f"Source image dimensions changed after classification snapshot creation: {sample.image_id}"
        )
    if canonical_json_sha256(_sample_payload(sample)) != sample.sample_sha256:
        raise RuntimeError(
            f"Classification snapshot sample integrity check failed: {sample.target_key}"
        )
    return Path(sample.source_image_managed_path)


def _materialize_snapshot_dataset(
    settings: Settings,
    session: Session,
    *,
    snapshot: ClassificationDatasetSnapshot,
    samples: list[ClassificationDatasetSample],
    project: Project,
    run: TrainingRun,
) -> dict[str, Any]:
    """Create an Ultralytics directory dataset while verifying snapshot immutability."""

    if canonical_json_sha256(dict(snapshot.manifest_json or {})) != snapshot.manifest_sha256:
        raise RuntimeError("Classification snapshot manifest integrity check failed")
    if snapshot.cardinality != "single":
        raise RuntimeError("Snapshot training currently requires single-label classification")

    class_map, folder_by_class_id = _classification_class_map(snapshot)
    config = dict(run.training_config_json or {})
    minimum_crop_size_px = int(config.get("minimum_crop_size_px", 10))
    padding_fraction = float(config.get("padding_fraction", 0.0))
    mask_background = str(config.get("mask_background", "black"))
    if mask_background not in {"keep", "black"}:
        raise RuntimeError("Classification mask background must be keep or black")

    base_relative = f"{project.storage_root}/training/{run.id}"
    dataset_output = f"{base_relative}/classification-dataset"
    dataset_manifest = f"{dataset_output}/export-manifest.json"
    dataset_archive = f"{dataset_output}.zip"
    dataset_root = resolve_managed_project_path(settings, dataset_output)
    archive_path = resolve_managed_project_path(settings, dataset_archive)
    shutil.rmtree(dataset_root, ignore_errors=True)
    archive_path.unlink(missing_ok=True)
    dataset_root.mkdir(parents=True, exist_ok=False)

    image_ids = sorted({sample.image_id for sample in samples})
    images = {
        image.id: image
        for image in session.scalars(select(ImageAsset).where(ImageAsset.id.in_(image_ids)))
    }
    if len(images) != len(image_ids):
        raise RuntimeError("A classification snapshot source image no longer exists")

    mask_ids = sorted(
        {
            str(sample.mask_annotation_id)
            for sample in samples
            if sample.mask_annotation_id is not None
        }
    )
    masks = (
        {
            mask.id: mask
            for mask in session.scalars(select(MaskAnnotation).where(MaskAnnotation.id.in_(mask_ids)))
        }
        if mask_ids
        else {}
    )
    if len(masks) != len(mask_ids):
        raise RuntimeError("A classification snapshot source mask no longer exists")

    split_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    manifest_items: list[dict[str, Any]] = []
    removed = 0
    for sample in samples:
        if sample.split not in CLASSIFICATION_SPLIT_DIRECTORIES:
            continue
        labels = list(sample.label_class_ids_json or [])
        if len(labels) != 1:
            raise RuntimeError(
                f"Single-label snapshot sample has {len(labels)} classes: {sample.target_key}"
            )
        class_id = str(labels[0])
        class_key = folder_by_class_id.get(class_id)
        if class_key is None:
            raise RuntimeError(
                f"Snapshot sample references a class missing from its class map: {class_id}"
            )
        image = images[sample.image_id]
        stored_path = _validate_source_image(sample, image)
        source_path = resolve_managed_project_path(settings, stored_path.as_posix())
        if not source_path.is_file():
            raise FileNotFoundError(
                f"Managed source image is missing for classification: {sample.image_id}"
            )

        crop_bbox = [0, 0, image.width_px, image.height_px]
        with Image.open(source_path) as source:
            source_rgb = source.convert("RGB")
            if sample.target_kind == "image":
                crop = source_rgb.copy()
            elif sample.target_kind in {"mask", "fragment"}:
                if sample.mask_annotation_id is None:
                    raise RuntimeError(f"Snapshot target is missing its source mask: {sample.target_key}")
                mask = masks[str(sample.mask_annotation_id)]
                if mask.image_id != image.id or mask.deleted_at is not None:
                    raise RuntimeError(f"Snapshot source mask is unavailable: {sample.target_key}")
                if sample.target_revision is None or mask.revision != sample.target_revision:
                    raise RuntimeError(
                        f"Source mask changed after classification snapshot creation: {sample.target_key}"
                    )
                current_geometry = _mask_geometry(mask)
                if canonical_json_sha256(current_geometry) != sample.target_checksum:
                    raise RuntimeError(
                        f"Source mask geometry changed after classification snapshot creation: {sample.target_key}"
                    )
                if dict(sample.geometry_json or {}) != current_geometry:
                    raise RuntimeError(
                        f"Stored classification snapshot geometry no longer matches: {sample.target_key}"
                    )
                if None in {mask.x_min, mask.y_min, mask.x_max, mask.y_max}:
                    raise RuntimeError(f"Snapshot mask lacks usable bounds: {sample.target_key}")
                width = float(mask.x_max) - float(mask.x_min)
                height = float(mask.y_max) - float(mask.y_min)
                if width < minimum_crop_size_px or height < minimum_crop_size_px:
                    removed += 1
                    continue
                bounds = _padded_bounds(
                    x_min=float(mask.x_min),
                    y_min=float(mask.y_min),
                    x_max=float(mask.x_max),
                    y_max=float(mask.y_max),
                    image_width=image.width_px,
                    image_height=image.height_px,
                    padding_fraction=padding_fraction,
                )
                left, top, right, bottom = bounds
                if right <= left or bottom <= top:
                    removed += 1
                    continue
                crop_bbox = [left, top, right, bottom]
                crop = _masked_crop(
                    settings,
                    source_rgb,
                    image,
                    mask,
                    bounds,
                    background=mask_background,
                )
            else:
                raise RuntimeError(
                    f"Unsupported classification snapshot target kind: {sample.target_kind}"
                )

        split_directory = CLASSIFICATION_SPLIT_DIRECTORIES[sample.split]
        destination_root = dataset_root / split_directory / class_key
        destination_root.mkdir(parents=True, exist_ok=True)
        filename = f"{sha256(sample.id.encode('utf-8')).hexdigest()[:24]}.jpg"
        destination = destination_root / filename
        try:
            crop.save(destination, format="JPEG", quality=95, optimize=True)
        finally:
            crop.close()
        manifest_items.append(
            {
                "sample_id": sample.id,
                "sample_sha256": sample.sample_sha256,
                "target_kind": sample.target_kind,
                "target_key": sample.target_key,
                "image_id": image.id,
                "image_sha256": image.sha256,
                "mask_annotation_id": sample.mask_annotation_id,
                "fragment_key": sample.fragment_key,
                "group_key": sample.group_key,
                "split": sample.split,
                "dataset_split_directory": split_directory,
                "source_geometry_checksum": sample.target_checksum,
                "source_revision": sample.target_revision,
                "crop_bbox": crop_bbox,
                "class_key": class_key,
                "source_label_class_id": class_id,
                "crop_path": destination.relative_to(dataset_root).as_posix(),
                "crop_sha256": _file_sha256(destination),
            }
        )
        split_counts[sample.split] += 1
        class_counts[class_key] += 1

    if split_counts.get("train", 0) <= 0:
        raise RuntimeError("No training samples remained after snapshot preprocessing")
    represented = [key for key, count in class_counts.items() if count > 0]
    if len(represented) < 2:
        raise RuntimeError("Snapshot preprocessing left fewer than two represented classes")

    source_snapshot_file = dataset_root / "classification-snapshot-manifest.json"
    source_snapshot_file.write_bytes(canonical_json_bytes(dict(snapshot.manifest_json or {})))
    export_manifest = {
        "schema": "reefvision-classification-training-export-v2",
        "format": "classification",
        "export_id": run.id,
        "classification_dataset_snapshot_id": snapshot.id,
        "snapshot_manifest_sha256": snapshot.manifest_sha256,
        "split_manifest_sha256": run.split_manifest_sha256,
        "classification_mode": "multiclass",
        "classification_scope": snapshot.target_kind,
        "classification_label_set_id": snapshot.label_set_id,
        "classification_label_set": dict(snapshot.manifest_json or {}).get("label_set", {}),
        "classification_cardinality": snapshot.cardinality,
        "minimum_crop_size_px": minimum_crop_size_px,
        "padding_fraction": padding_fraction,
        "mask_background": mask_background,
        "split_directory_map": CLASSIFICATION_SPLIT_DIRECTORIES,
        "split_counts": dict(split_counts),
        "class_counts": dict(class_counts),
        "class_map": class_map,
        "removed_during_preprocessing_count": removed,
        "items": manifest_items,
    }
    manifest_path = resolve_managed_project_path(settings, dataset_manifest)
    manifest_path.write_bytes(canonical_json_bytes(export_manifest))
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(dataset_root.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(dataset_root).as_posix())

    return {
        "dataset_output_path": dataset_output,
        "dataset_manifest_path": dataset_manifest,
        "dataset_archive_path": dataset_archive,
        "manifest_sha256": canonical_json_sha256(export_manifest),
        "item_count": len(manifest_items),
        "split_counts": dict(split_counts),
        "class_counts": dict(class_counts),
        "class_map": class_map,
        "removed_during_preprocessing_count": removed,
        "archive_size_bytes": archive_path.stat().st_size,
    }


def process_snapshot_classification_training_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    run_id: str | None = None
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "training" or job.status != "queued":
            return False
        run_id = str(job.request_json.get("training_run_id", ""))
        run = session.get(TrainingRun, run_id)
        if run is None or run.task != CLASSIFICATION_TASK:
            return False
        snapshot_id = str(
            dict(run.training_config_json or {}).get("classification_dataset_snapshot_id") or ""
        )
        if not snapshot_id:
            return False
        run.status = "preparing_dataset"
        run.stage = "preparing_dataset"
        run.started_at = datetime.now(UTC)
        run.error_message = None
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        job.result_json = {"stage": "preparing_dataset"}
        session.commit()

    try:
        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None:
                raise RuntimeError("Classification training records are incomplete")
            snapshot_id = str(run.training_config_json["classification_dataset_snapshot_id"])
            snapshot = session.get(ClassificationDatasetSnapshot, snapshot_id)
            project = session.get(Project, run.project_id)
            if snapshot is None or snapshot.project_id != run.project_id or project is None:
                raise RuntimeError("Classification run references a missing snapshot or project")
            if snapshot.manifest_sha256 != run.dataset_manifest_sha256:
                raise RuntimeError("Classification snapshot manifest changed after training was queued")
            samples = list(
                session.scalars(
                    select(ClassificationDatasetSample)
                    .where(ClassificationDatasetSample.snapshot_id == snapshot.id)
                    .order_by(
                        ClassificationDatasetSample.split,
                        ClassificationDatasetSample.group_key,
                        ClassificationDatasetSample.target_key,
                    )
                )
            )
            export_result = _materialize_snapshot_dataset(
                settings,
                session,
                snapshot=snapshot,
                samples=samples,
                project=project,
                run=run,
            )
            base_relative = f"{project.storage_root}/training/{run.id}"
            dataset_root = resolve_managed_project_path(
                settings,
                str(export_result["dataset_output_path"]),
            )
            save_root = resolve_managed_project_path(settings, f"{base_relative}/ultralytics")
            shutil.rmtree(save_root, ignore_errors=True)
            save_root.mkdir(parents=True, exist_ok=True)
            logs_path = save_root / "training.log"
            _append_log(
                logs_path,
                f"[{datetime.now(UTC).isoformat()}] immutable classification snapshot prepared",
            )
            checkpoint_source = _model_source(settings, session, run)
            config = dict(run.training_config_json or {})
            run.status = "training"
            run.stage = "training"
            run.logs_path = _relative_to_data_dir(settings, logs_path)
            run.artifact_manifest_json = {
                **dict(run.artifact_manifest_json or {}),
                "classification_dataset_snapshot_id": snapshot.id,
                "classification_scope": snapshot.target_kind,
                "classification_label_set_id": snapshot.label_set_id,
                "classification_label_set_key": config.get("classification_label_set_key"),
                "classification_cardinality": snapshot.cardinality,
                "classification_mode": "multiclass",
                "minimum_crop_size_px": int(config.get("minimum_crop_size_px", 10)),
                "padding_fraction": float(config.get("padding_fraction", 0.0)),
                "mask_background": str(config.get("mask_background", "black")),
                "dataset_output_path": export_result["dataset_output_path"],
                "dataset_manifest_path": export_result["dataset_manifest_path"],
                "dataset_archive_path": export_result["dataset_archive_path"],
                "dataset_export_result": export_result,
                "resolved_architecture_path": checkpoint_source
                if run.initial_checkpoint_source == "scratch"
                else None,
            }
            job.result_json = {
                "stage": "training",
                "classification_dataset_snapshot_id": snapshot.id,
                "dataset_output_path": export_result["dataset_output_path"],
            }
            session.commit()

        from ultralytics import YOLO  # type: ignore[attr-defined]

        cancellation_requested = {"value": False}
        model = YOLO(checkpoint_source)
        model.add_callback(
            "on_fit_epoch_end",
            lambda trainer: _on_fit_epoch_end(
                settings,
                factory,
                job_id,
                run_id or "",
                trainer,
                cancellation_requested,
            ),
        )
        model.add_callback(
            "on_train_start",
            lambda trainer: _on_train_start(
                settings,
                factory,
                job_id,
                run_id or "",
                trainer,
            ),
        )
        model.add_callback(
            "on_train_end",
            lambda trainer: _on_train_end(
                settings,
                factory,
                job_id,
                run_id or "",
                trainer,
            ),
        )

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise RuntimeError("Classification run disappeared before launch")
            train_args = dict(run.training_config_json or {})
            for key in _METADATA_CONFIG_KEYS:
                train_args.pop(key, None)
            train_args.update(
                {
                    "data": str(dataset_root),
                    "device": resolve_training_device(run.device),
                    "project": str(
                        resolve_managed_project_path(settings, f"{base_relative}/runs")
                    ),
                    "name": "classify",
                    "exist_ok": True,
                    "save": True,
                    "verbose": False,
                    "amp": run.precision == "amp",
                }
            )
            if run.random_seed is not None:
                train_args["seed"] = run.random_seed
            _append_log(
                resolve_managed_project_path(settings, run.logs_path or ""),
                f"[{datetime.now(UTC).isoformat()}] launching snapshot-backed Ultralytics classification",
            )

        model.train(**train_args)

        with factory() as session:
            run = session.get(TrainingRun, run_id)
            job = session.get(Job, job_id)
            if run is None or job is None or model.trainer is None:
                raise RuntimeError("Classification run disappeared after execution")
            save_dir = Path(str(model.trainer.save_dir)).resolve()
            results_csv = save_dir / "results.csv"
            weights_dir = save_dir / "weights"
            best_ckpt = weights_dir / "best.pt"
            last_ckpt = weights_dir / "last.pt"
            history = _read_results_csv(results_csv)
            metrics = _last_metrics(history)
            run.metrics_history_json = history
            run.metrics_json = metrics
            run.artifact_manifest_json = {
                **dict(run.artifact_manifest_json or {}),
                "run_save_dir": _relative_to_data_dir(settings, save_dir),
                "results_csv": (
                    _relative_to_data_dir(settings, results_csv) if results_csv.is_file() else None
                ),
                "best_checkpoint_path": (
                    _relative_to_data_dir(settings, best_ckpt) if best_ckpt.is_file() else None
                ),
                "last_checkpoint_path": (
                    _relative_to_data_dir(settings, last_ckpt) if last_ckpt.is_file() else None
                ),
            }
            run.result_checkpoint_path = (
                _relative_to_data_dir(settings, best_ckpt)
                if best_ckpt.is_file()
                else _relative_to_data_dir(settings, last_ckpt)
                if last_ckpt.is_file()
                else None
            )
            if cancellation_requested["value"] or job.status == "cancel_requested":
                run.status = "cancelled"
                run.stage = "cancelled"
                job.status = "cancelled"
            elif run.result_checkpoint_path is None:
                raise RuntimeError("Classification training produced no checkpoint")
            else:
                run.status = "completed"
                run.stage = "completed"
                job.status = "succeeded"
                job.progress_current = max(job.progress_total, 1)
                job.result_json = {
                    "stage": "completed",
                    "metrics": metrics,
                    "result_checkpoint_path": run.result_checkpoint_path,
                    "classification_dataset_snapshot_id": dict(
                        run.artifact_manifest_json or {}
                    ).get("classification_dataset_snapshot_id"),
                }
                session.add(
                    ExperimentRecord(
                        project_id=run.project_id,
                        training_run_id=run.id,
                        dataset_version_id=None,
                        dataset_manifest_sha256=run.dataset_manifest_sha256,
                        split_manifest_sha256=run.split_manifest_sha256,
                        task=run.task,
                        provider_id=run.provider_id,
                        architecture=run.architecture,
                        summary_metrics_json=metrics,
                        comparison_warnings_json=list(run.warnings_json or []),
                        artifact_manifest_json=dict(run.artifact_manifest_json or {}),
                        package_versions_json=_package_versions_snapshot(),
                    )
                )
            run.completed_at = datetime.now(UTC)
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            run = session.get(TrainingRun, run_id) if run_id else None
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
            if run is not None:
                run.status = "failed"
                run.stage = "failed"
                run.error_message = str(exc)
                run.completed_at = datetime.now(UTC)
                if run.logs_path:
                    with suppress(Exception):
                        _append_log(
                            resolve_managed_project_path(settings, run.logs_path),
                            f"[{datetime.now(UTC).isoformat()}] failure: {exc}",
                        )
            session.commit()
        return False
