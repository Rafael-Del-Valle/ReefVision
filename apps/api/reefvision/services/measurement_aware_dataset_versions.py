"""Dataset snapshots that preserve measurements and extended export formats."""

from __future__ import annotations

from typing import Any

from reefvision.db.models import ExportRecord, Job, MaskAnnotation
from reefvision.domain.errors import ValidationError
from reefvision.schemas.dataset_versions import (
    DatasetExportCreateRequest,
    DatasetExportCreateResponse,
    ExportResponse,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.services.mask_aware_dataset_versions import MaskAwareDatasetVersionService
from reefvision.storage.datasets import dataset_export_relative_paths

SUPPORTED_EXPORT_FORMATS = {
    "yolo_detection",
    "yolo_segmentation",
    "semantic_masks",
    "classification_multiclass",
    "classification_binary_state",
    "coco_instances",
}


class MeasurementAwareDatasetVersionService(MaskAwareDatasetVersionService):
    """Extend mask snapshots with measurements and complete export dispatch."""

    def _mask_snapshot(self, mask: MaskAnnotation) -> dict[str, Any]:
        snapshot = super()._mask_snapshot(mask)
        snapshot["measurement_json"] = dict(mask.measurement_json or {})
        return snapshot

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

        output_path, manifest_path, archive_path = dataset_export_relative_paths(
            project_storage_root=version.project.storage_root,
            version_number=version.version_number,
            export_id=version.id + "-" + str(len(version.exports) + 1),
        )
        request_json = request.model_dump(mode="json")
        request_json["dataset_version_id"] = version.id
        export = ExportRecord(
            project_id=version.project_id,
            dataset_version_id=version.id,
            format=request.format,
            output_path=output_path,
            manifest_path=manifest_path,
            archive_path=archive_path,
            request_json=request_json,
            status="queued",
        )
        self.exports.add_export(export)
        self.session.flush()
        output_path, manifest_path, archive_path = dataset_export_relative_paths(
            project_storage_root=version.project.storage_root,
            version_number=version.version_number,
            export_id=export.id,
        )
        export.output_path = output_path
        export.manifest_path = manifest_path
        export.archive_path = archive_path

        job = Job(
            project_id=version.project_id,
            job_type="export",
            status="queued",
            progress_total=max(version.image_count, 1),
            request_json={"export_id": export.id, **request_json},
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
