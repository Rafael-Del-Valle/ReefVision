"""Background export-job processing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ClassificationCrop,
    DatasetVersion,
    DatasetVersionItem,
    ExportRecord,
    ImageAsset,
    Job,
)
from reefvision.storage.classification_exports import write_classification_export
from reefvision.storage.coco_exports import write_coco_instances_export
from reefvision.storage.datasets import (
    remove_export_artifacts,
    write_yolo_detection_export,
)
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.segmentation_exports import (
    write_semantic_mask_export,
    write_yolo_segmentation_export,
)


def _fail_export(
    factory: sessionmaker[Session],
    export_id: str,
    *,
    message: str,
) -> None:
    with factory() as session:
        export = session.get(ExportRecord, export_id)
        if export is None:
            return
        export.status = "failed"
        export.error_message = message
        export.completed_at = datetime.now(UTC)
        session.commit()


def _classification_crop_rows(
    settings: Settings,
    *,
    manifest_path: str,
    expected_count: int,
) -> list[dict[str, Any]]:
    manifest_file = resolve_managed_project_path(settings, manifest_path)
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    raw_rows = payload.get("items")
    if not isinstance(raw_rows, list):
        raise RuntimeError("Classification export manifest is missing crop items")
    rows = [dict(item) for item in raw_rows if isinstance(item, dict)]
    if len(rows) != len(raw_rows) or len(rows) != expected_count:
        raise RuntimeError("Classification export crop manifest is incomplete")
    return rows


def _box_dict(value: object, *, integer: bool) -> dict[str, float] | dict[str, int]:
    if not isinstance(value, list) or len(value) != 4:
        raise RuntimeError("Classification crop manifest contains an invalid box")
    if integer:
        return {
            "x_min": int(value[0]),
            "y_min": int(value[1]),
            "x_max": int(value[2]),
            "y_max": int(value[3]),
        }
    return {
        "x_min": float(value[0]),
        "y_min": float(value[1]),
        "x_max": float(value[2]),
        "y_max": float(value[3]),
    }


def process_export_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    output_path: str | None = None
    archive_path: str | None = None
    classification_rows: list[dict[str, Any]] | None = None
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "export" or job.status != "queued":
            return False
        export_id = str(job.request_json["export_id"])
        export = session.get(ExportRecord, export_id)
        if export is None:
            job.status = "failed"
            job.error_message = "Export record is missing"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        export.status = "running"
        export.error_message = None
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        session.commit()

    try:
        with factory() as session:
            export = session.get(ExportRecord, export_id)
            if export is None:
                raise RuntimeError("Export record is missing")
            version = session.scalar(
                select(DatasetVersion).where(DatasetVersion.id == export.dataset_version_id)
            )
            if version is None:
                raise RuntimeError("Dataset version is missing")
            items = list(
                session.scalars(
                    select(DatasetVersionItem)
                    .where(DatasetVersionItem.dataset_version_id == version.id)
                    .order_by(
                        DatasetVersionItem.split,
                        DatasetVersionItem.original_filename,
                        DatasetVersionItem.image_id,
                    )
                )
            )
            images = list(
                session.scalars(
                    select(ImageAsset).where(ImageAsset.id.in_([item.image_id for item in items]))
                )
            )
            image_paths = {
                image.id: resolve_managed_project_path(
                    settings,
                    image.managed_path,
                )
                for image in images
            }
            for image_id, path in image_paths.items():
                if not path.is_file():
                    raise FileNotFoundError(
                        f"Managed source image is missing for export: {image_id}"
                    )
            output_path = export.output_path
            archive_path = export.archive_path
            if export.format == "yolo_detection":
                result = write_yolo_detection_export(
                    settings,
                    export_id=export.id,
                    version=version,
                    items=items,
                    image_paths=image_paths,
                    output_path=export.output_path,
                    manifest_path=export.manifest_path,
                    archive_path=export.archive_path,
                )
            elif export.format == "yolo_segmentation":
                result = write_yolo_segmentation_export(
                    settings,
                    export_id=export.id,
                    version=version,
                    items=items,
                    image_paths=image_paths,
                    output_path=export.output_path,
                    manifest_path=export.manifest_path,
                    archive_path=export.archive_path,
                )
            elif export.format == "semantic_masks":
                result = write_semantic_mask_export(
                    settings,
                    export_id=export.id,
                    version=version,
                    items=items,
                    image_paths=image_paths,
                    output_path=export.output_path,
                    manifest_path=export.manifest_path,
                    archive_path=export.archive_path,
                )
            elif export.format == "coco_instances":
                result = write_coco_instances_export(
                    settings,
                    export_id=export.id,
                    version=version,
                    items=items,
                    image_paths=image_paths,
                    output_path=export.output_path,
                    manifest_path=export.manifest_path,
                    archive_path=export.archive_path,
                )
            elif export.format in {
                "classification_multiclass",
                "classification_binary_state",
            }:
                mode = (
                    "binary_state"
                    if export.format == "classification_binary_state"
                    else "multiclass"
                )
                result = write_classification_export(
                    settings,
                    export_id=export.id,
                    version=version,
                    items=items,
                    image_paths=image_paths,
                    output_path=export.output_path,
                    manifest_path=export.manifest_path,
                    archive_path=export.archive_path,
                    mode=mode,
                    minimum_crop_size_px=int(export.request_json.get("minimum_crop_size_px", 10)),
                    padding_fraction=float(export.request_json.get("padding_fraction", 0.0)),
                )
                classification_rows = _classification_crop_rows(
                    settings,
                    manifest_path=export.manifest_path,
                    expected_count=int(result["item_count"]),
                )
            else:
                raise RuntimeError(f"Unsupported export format: {export.format}")

        with factory() as session:
            job = session.get(Job, job_id)
            export = session.get(ExportRecord, export_id)
            if job is None or export is None:
                raise RuntimeError("Export job references missing database rows")
            if classification_rows is not None:
                session.execute(
                    delete(ClassificationCrop).where(ClassificationCrop.export_id == export.id)
                )
                for item in classification_rows:
                    crop_path = str(item["crop_path"])
                    managed_path = f"{export.output_path.rstrip('/')}/{crop_path.lstrip('/')}"
                    session.add(
                        ClassificationCrop(
                            project_id=export.project_id,
                            export_id=export.id,
                            dataset_version_id=export.dataset_version_id,
                            image_id=str(item["image_id"]),
                            annotation_id=str(item["annotation_id"]),
                            label_class_id=str(item["source_label_class_id"]),
                            split=str(item["split"]),
                            managed_path=managed_path,
                            sha256=str(item["crop_sha256"]),
                            source_box_json=_box_dict(
                                item.get("source_bbox"),
                                integer=False,
                            ),
                            crop_box_json=_box_dict(
                                item.get("crop_bbox"),
                                integer=True,
                            ),
                            metadata_json={
                                "class_key": item.get("class_key"),
                                "class_label": item.get("class_label"),
                                "group_key": item.get("group_key"),
                                "image_sha256": item.get("image_sha256"),
                                "snapshot_sha256": item.get("snapshot_sha256"),
                            },
                        )
                    )
                result = {
                    **result,
                    "classification_crop_count": len(classification_rows),
                }
            export.status = "succeeded"
            export.completed_at = datetime.now(UTC)
            export.request_json = {**export.request_json, **result}
            job.status = "succeeded"
            job.progress_current = max(job.progress_total, 1)
            job.result_json = result
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        if output_path is not None:
            remove_export_artifacts(
                settings,
                output_path=output_path,
                archive_path=archive_path,
            )
        _fail_export(factory, export_id, message=str(exc))
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
                session.commit()
        return False
