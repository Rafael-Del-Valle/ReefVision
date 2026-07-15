"""Background export-job processing."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    ExportRecord,
    ImageAsset,
    Job,
)
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


def process_export_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    output_path: str | None = None
    archive_path: str | None = None
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
            else:
                raise RuntimeError(f"Unsupported export format: {export.format}")

        with factory() as session:
            job = session.get(Job, job_id)
            export = session.get(ExportRecord, export_id)
            if job is None or export is None:
                raise RuntimeError("Export job references missing database rows")
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
