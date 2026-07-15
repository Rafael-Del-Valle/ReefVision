"""Mask-aware dataset snapshots and segmentation export requests."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    ExportRecord,
    Job,
    MaskAnnotation,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ValidationError
from reefvision.schemas.dataset_versions import (
    DatasetExportCreateRequest,
    DatasetExportCreateResponse,
    DatasetVersionCreateRequest,
    DatasetVersionPreviewRequest,
    DatasetVersionPreviewResponse,
    DatasetVersionResponse,
    ExportResponse,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.services.dataset_versions import DatasetVersionService
from reefvision.storage.datasets import canonical_json_sha256, dataset_export_relative_paths
from reefvision.storage.projects import resolve_managed_project_path

MASK_AWARE_SCHEMA_VERSION = "0007"
SUPPORTED_EXPORT_FORMATS = {
    "yolo_detection",
    "yolo_segmentation",
    "semantic_masks",
}


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MaskAwareDatasetVersionService(DatasetVersionService):
    """Extend immutable dataset versions with verified polygon and raster masks."""

    def __init__(self, session: Session, settings: Settings) -> None:
        super().__init__(session, settings)

    def _masks_for_images(self, image_ids: list[str]) -> dict[str, list[MaskAnnotation]]:
        masks_by_image: dict[str, list[MaskAnnotation]] = defaultdict(list)
        if not image_ids:
            return masks_by_image
        statement = (
            select(MaskAnnotation)
            .options(selectinload(MaskAnnotation.label_class))
            .where(
                MaskAnnotation.image_id.in_(image_ids),
                MaskAnnotation.deleted_at.is_(None),
                MaskAnnotation.status == "verified",
            )
            .order_by(
                MaskAnnotation.image_id,
                MaskAnnotation.created_at,
                MaskAnnotation.id,
            )
        )
        for mask in self.session.scalars(statement):
            masks_by_image[mask.image_id].append(mask)
        return masks_by_image

    def _mask_snapshot(self, mask: MaskAnnotation) -> dict[str, Any]:
        label_class = mask.label_class
        if label_class is None:
            raise ValidationError("Dataset snapshots require every mask to resolve its class")
        content_sha256: str | None = None
        if mask.geometry_kind == "raster_mask":
            if not mask.mask_path:
                raise ValidationError("Raster mask snapshot is missing managed content")
            path = resolve_managed_project_path(self.settings, mask.mask_path)
            if not path.is_file():
                raise ValidationError("Raster mask snapshot content is missing")
            content_sha256 = _file_sha256(path)
        elif mask.geometry_kind != "polygon":
            raise ValidationError(f"Unsupported mask geometry: {mask.geometry_kind}")

        return {
            "id": mask.id,
            "label_class_id": label_class.id,
            "class_index": label_class.class_index,
            "class_name": label_class.name,
            "geometry_kind": mask.geometry_kind,
            "mask_path": mask.mask_path,
            "mask_content_sha256": content_sha256,
            "polygon_json": mask.polygon_json,
            "x_min": mask.x_min,
            "y_min": mask.y_min,
            "x_max": mask.x_max,
            "y_max": mask.y_max,
            "area_pixels": mask.area_pixels,
            "source_type": mask.source_type,
            "provenance_json": mask.provenance_json,
            "status": mask.status,
            "created_by": mask.created_by,
            "created_at": mask.created_at.isoformat(),
            "updated_at": mask.updated_at.isoformat(),
            "revision": mask.revision,
        }

    def preview_version(
        self,
        project_id: str,
        request: DatasetVersionPreviewRequest,
    ) -> DatasetVersionPreviewResponse:
        response = super().preview_version(project_id, request)
        image_ids = [item.image_id for item in response.images]
        masks_by_image = self._masks_for_images(image_ids)
        mask_counts_by_class: dict[str, int] = defaultdict(int)
        split_mask_counts: dict[str, int] = defaultdict(int)
        total_masks = 0

        for item in response.images:
            count = len(masks_by_image.get(item.image_id, []))
            item.mask_annotation_count = count
            split_mask_counts[item.proposed_split] += count
            total_masks += count
        for masks in masks_by_image.values():
            for mask in masks:
                if mask.label_class_id is not None:
                    mask_counts_by_class[mask.label_class_id] += 1
        for summary in response.split_summary:
            summary.mask_annotation_count = split_mask_counts[summary.split]
        for class_count in response.per_class_counts:
            class_count.mask_count = mask_counts_by_class[class_count.label_class_id]
        response.eligible_mask_annotation_count = total_masks
        return response

    def create_version(
        self,
        project_id: str,
        request: DatasetVersionCreateRequest,
    ) -> DatasetVersionResponse:
        project = self._project(project_id)
        self._parent_version(project.id, request.parent_version_id)
        candidates = self._eligible_images(
            project.id,
            list(request.eligible_annotation_statuses),
        )
        if not candidates:
            raise ValidationError("No images match the selected annotation statuses")

        split_plan = self._plan_splits(candidates, request)
        masks_by_image = self._masks_for_images([candidate.image.id for candidate in candidates])
        total_mask_count = sum(len(items) for items in masks_by_image.values())
        version = DatasetVersion(
            project_id=project.id,
            version_number=self.versions.next_version_number(project.id),
            name=request.name,
            notes=request.notes,
            parent_version_id=request.parent_version_id,
            status="creating",
            requested_split_method=request.split_method,
            resolved_split_method=split_plan.resolved_split_method,
            eligible_annotation_statuses_json=list(request.eligible_annotation_statuses),
            requested_ratios_json=split_plan.requested_ratios,
            achieved_ratios_json=split_plan.achieved_ratios,
            split_seed=request.split_seed,
            reuse_parent_assignments=request.reuse_parent_assignments,
            missing_group_key_count=split_plan.missing_group_key_count,
            warnings_json=list(split_plan.warnings),
            class_map_json=self._class_map(project),
            manifest_json={},
            manifest_sha256="",
            image_count=len(candidates),
            annotation_count=split_plan.eligible_annotation_count,
            mask_annotation_count=total_mask_count,
            created_by=request.creator or "local_user",
            reefvision_version=__version__,
            schema_version=MASK_AWARE_SCHEMA_VERSION,
        )
        self.versions.add_version(version)
        self.session.flush()

        manifest_items: list[dict[str, Any]] = []
        for candidate in sorted(candidates, key=lambda item: item.image.id):
            annotations = [
                self._annotation_snapshot(annotation) for annotation in candidate.annotations
            ]
            mask_snapshots = [
                self._mask_snapshot(mask) for mask in masks_by_image.get(candidate.image.id, [])
            ]
            mask_counts: dict[str, int] = defaultdict(int)
            for mask in mask_snapshots:
                mask_counts[str(mask["label_class_id"])] += 1
            item_payload: dict[str, Any] = {
                "image_id": candidate.image.id,
                "image_sha256": candidate.image.sha256,
                "original_filename": candidate.image.original_filename,
                "width_px": candidate.image.width_px,
                "height_px": candidate.image.height_px,
                "annotation_status": candidate.image.annotation_status,
                "split": split_plan.assignments[candidate.image.id],
                "group_key": candidate.image.group_key,
                "annotation_count": len(candidate.annotations),
                "mask_annotation_count": len(mask_snapshots),
                "per_class_counts": candidate.per_class_counts,
                "per_mask_class_counts": dict(mask_counts),
                "annotations": annotations,
                "mask_annotations": mask_snapshots,
            }
            snapshot_sha256 = canonical_json_sha256(item_payload)
            dataset_item = DatasetVersionItem(
                dataset_version_id=version.id,
                image_id=candidate.image.id,
                image_sha256=candidate.image.sha256,
                original_filename=candidate.image.original_filename,
                width_px=candidate.image.width_px,
                height_px=candidate.image.height_px,
                image_annotation_status=candidate.image.annotation_status,
                split=split_plan.assignments[candidate.image.id],
                group_key=candidate.image.group_key,
                annotation_snapshot_json=annotations,
                mask_annotation_snapshot_json=mask_snapshots,
                per_class_counts_json=candidate.per_class_counts,
                per_mask_class_counts_json=dict(mask_counts),
                annotation_count=len(candidate.annotations),
                mask_annotation_count=len(mask_snapshots),
                snapshot_sha256=snapshot_sha256,
            )
            self.versions.add_item(dataset_item)
            manifest_items.append({**item_payload, "snapshot_sha256": snapshot_sha256})

        manifest: dict[str, Any] = {
            "schema_version": MASK_AWARE_SCHEMA_VERSION,
            "reefvision_version": __version__,
            "project": {
                "id": project.id,
                "name": project.name,
                "slug": project.slug,
            },
            "dataset_version": {
                "id": version.id,
                "version_number": version.version_number,
                "name": version.name,
                "notes": version.notes,
                "parent_version_id": version.parent_version_id,
                "status": "complete",
                "created_by": version.created_by,
                "created_at": version.created_at.isoformat(),
            },
            "split_config": {
                "requested_split_method": version.requested_split_method,
                "resolved_split_method": version.resolved_split_method,
                "requested_ratios": version.requested_ratios_json,
                "achieved_ratios": version.achieved_ratios_json,
                "split_seed": version.split_seed,
                "reuse_parent_assignments": version.reuse_parent_assignments,
                "eligible_annotation_statuses": (version.eligible_annotation_statuses_json),
                "warnings": version.warnings_json,
                "missing_group_key_count": version.missing_group_key_count,
            },
            "summary": {
                "image_count": version.image_count,
                "annotation_count": version.annotation_count,
                "mask_annotation_count": version.mask_annotation_count,
            },
            "class_map": version.class_map_json,
            "items": manifest_items,
        }
        version.manifest_json = manifest
        version.manifest_sha256 = canonical_json_sha256(manifest)
        version.status = "complete"
        version.completed_at = utc_now()
        self.session.commit()
        self.session.refresh(version)
        return DatasetVersionResponse.model_validate(version)

    def create_export(
        self,
        version_id: str,
        request: DatasetExportCreateRequest,
    ) -> DatasetExportCreateResponse:
        version = self._version(version_id)
        if version.status != "complete":
            raise ValidationError("Only complete dataset versions may be exported")
        if request.format not in SUPPORTED_EXPORT_FORMATS:
            raise ValidationError("Unsupported dataset export format")
        if request.format != "yolo_detection" and version.mask_annotation_count <= 0:
            raise ValidationError("This dataset version does not contain mask annotations")

        export_id = str(uuid4())
        output_path, manifest_path, archive_path = dataset_export_relative_paths(
            project_storage_root=version.project.storage_root,
            version_number=version.version_number,
            export_id=export_id,
        )
        export = ExportRecord(
            id=export_id,
            project_id=version.project_id,
            dataset_version_id=version.id,
            format=request.format,
            output_path=output_path,
            manifest_path=manifest_path,
            archive_path=archive_path,
            request_json={
                "format": request.format,
                "dataset_version_id": version.id,
            },
            status="queued",
        )
        self.exports.add_export(export)
        job = Job(
            project_id=version.project_id,
            job_type="export",
            status="queued",
            progress_total=max(version.image_count, 1),
            request_json={"export_id": export.id, "format": request.format},
        )
        self.session.add(job)
        self.session.flush()
        export.job_id = job.id
        self.session.commit()
        self.session.refresh(export)
        self.session.refresh(job)
        return DatasetExportCreateResponse(
            export=ExportResponse.model_validate(export),
            job=JobResponse.model_validate(job),
        )
