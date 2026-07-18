"""Training workspace integration for nnU-Net semantic segmentation."""

from __future__ import annotations

from reefvision.db.models import DatasetVersion, DatasetVersionItem, TrainingDraft
from reefvision.domain.errors import ValidationError
from reefvision.ml.semantic_segmentation import (
    NNUNET_CONFIGURATION,
    NNUNET_PROVIDER_ID,
    SEMANTIC_SEGMENTATION_TASK,
    SUPPORTED_NNUNET_EPOCHS,
    nnunet_dependency_status,
)
from reefvision.schemas.training import (
    TrainingDraftWriteRequest,
    TrainingPreflightResponse,
    TrainingProviderArchitectureResponse,
    TrainingProviderResponse,
    TrainingTilingEstimateResponse,
)
from reefvision.services.segmentation_training import SegmentationTrainingService
from reefvision.services.training import TRAINING_PRECISIONS
from reefvision.services.training_tasks import task_dataset_preflight


class SemanticTrainingService(SegmentationTrainingService):
    """Add an optional nnU-Net v2 semantic task to the existing workspace."""

    def list_providers(self) -> list[TrainingProviderResponse]:
        dependency = nnunet_dependency_status()
        warning = None
        if not dependency["ready"]:
            warning = "nnU-Net is optional and currently unavailable: " + "; ".join(
                str(item) for item in dependency["issues"]
            )
        return [
            *super().list_providers(),
            TrainingProviderResponse(
                provider_id=NNUNET_PROVIDER_ID,
                display_name="nnU-Net v2",
                provider_version=str(dependency["provider_version"]),
                supported_tasks=[SEMANTIC_SEGMENTATION_TASK],
                supported_precision_modes=list(TRAINING_PRECISIONS),
                supports_tiling=False,
                supports_tuning=False,
                supports_packaged_desktop=False,
                warning=warning,
                architectures=[
                    TrainingProviderArchitectureResponse(
                        architecture_id=NNUNET_CONFIGURATION,
                        display_name="nnU-Net 2D",
                        task=SEMANTIC_SEGMENTATION_TASK,
                        source="nnunetv2",
                    )
                ],
            ),
        ]

    def preflight(
        self,
        project_id: str,
        payload: TrainingDraftWriteRequest,
    ) -> TrainingPreflightResponse:
        if payload.task != SEMANTIC_SEGMENTATION_TASK and payload.provider_id != NNUNET_PROVIDER_ID:
            return super().preflight(project_id, payload)

        project = self._project(project_id)
        blockers: list[str] = []
        warnings: list[str] = []
        version: DatasetVersion | None = None
        version_items: list[DatasetVersionItem] | None = None

        if payload.dataset_version_id:
            version = self._version(payload.dataset_version_id)
            if version.project_id != project.id:
                raise ValidationError(
                    "Training drafts must reference a dataset version from the same project"
                )
            if version.status != "complete":
                blockers.append(
                    "Only complete immutable dataset versions may be selected for training"
                )
            else:
                version_items = self.versions.items_for_version(version.id)
        else:
            blockers.append("Select an immutable dataset version before launching training")

        if payload.task != SEMANTIC_SEGMENTATION_TASK:
            blockers.append("nnU-Net supports only the semantic_segment training task")
        if (payload.provider_id or NNUNET_PROVIDER_ID) != NNUNET_PROVIDER_ID:
            blockers.append("Semantic segmentation currently uses the nnunet provider")
        if (payload.architecture or NNUNET_CONFIGURATION) != NNUNET_CONFIGURATION:
            blockers.append("The first nnU-Net slice supports only the 2d configuration")
        if payload.precision not in TRAINING_PRECISIONS:
            blockers.append("Supported precision modes are fp32 and amp")
        if payload.initial_checkpoint_source != "scratch":
            blockers.append("Initial nnU-Net training currently starts from scratch")

        training_config = self._merged_training_config(payload.training_config)
        epochs = int(training_config.get("epochs", 50))
        if epochs not in SUPPORTED_NNUNET_EPOCHS:
            blockers.append(
                "nnU-Net epochs must be one of: "
                + ", ".join(str(value) for value in SUPPORTED_NNUNET_EPOCHS)
            )
        tuning_config = self._merged_tuning_config(payload.tuning_config)
        if tuning_config.get("mode", "disabled") != "disabled":
            blockers.append("nnU-Net tuning execution is not implemented")
        tiling_config = self._merged_tiling_config(payload.tiling_config)
        if tiling_config.get("mode", "none") != "none":
            blockers.append(
                "nnU-Net performs its own patch planning; ReefVision tiling must remain disabled"
            )

        dataset_summary = self._dataset_summary(version, items=version_items)
        task_check = task_dataset_preflight(
            SEMANTIC_SEGMENTATION_TASK,
            version_items or [],
        )
        blockers.extend(task_check.blockers)
        warnings.extend(task_check.warnings)
        dataset_summary.mask_annotation_count = (
            task_check.polygon_count + task_check.raster_mask_count
        )
        dataset_summary.polygon_count = task_check.polygon_count
        dataset_summary.raster_mask_count = task_check.raster_mask_count
        dataset_summary.polygon_counts_by_split = dict(task_check.polygon_counts_by_split)
        dataset_summary.raster_counts_by_split = dict(task_check.raster_counts_by_split)

        leakage_audit = self._leakage_audit(version, items=version_items)
        warnings.extend(leakage_audit.warnings)
        blockers.extend(leakage_audit.blockers)

        dependency = nnunet_dependency_status()
        if not dependency["ready"]:
            blockers.extend(str(item) for item in dependency["issues"])

        resource_snapshot = self._resource_snapshot(payload.device)
        disk_free_gb = resource_snapshot.get("disk_free_gb")
        max_disk_usage_gb = float(
            self._merged_resource_limits(payload.resource_limits)["max_disk_usage_gb"]
        )
        if isinstance(disk_free_gb, (int, float)) and disk_free_gb < max_disk_usage_gb:
            warnings.append(
                "Requested disk budget exceeds currently available free space in the "
                "ReefVision data directory"
            )

        tiling_estimate = (
            self._tiling_estimate(version, tiling_config, items=version_items)
            if version is not None
            else TrainingTilingEstimateResponse(
                blocked=True,
                warnings=[],
                tile_count=0,
                positive_tile_count=0,
                background_tile_count=0,
                estimated_storage_bytes=0,
                preview_tiles=[],
            )
        )
        warnings.extend(tiling_estimate.warnings)

        blockers = self._dedupe_messages(blockers)
        warnings = self._dedupe_messages(warnings)
        status = "blocked" if blockers else "ready_with_warnings" if warnings else "ready"
        return TrainingPreflightResponse(
            status=status,
            warnings=warnings,
            blockers=blockers,
            dataset=dataset_summary,
            leakage_audit=leakage_audit,
            resource_snapshot=resource_snapshot,
            provider_dependency_status={
                "provider_name": NNUNET_PROVIDER_ID,
                "ready": bool(dependency["ready"]),
                "status": str(dependency["status"]),
                "issues": list(dependency["issues"]),
                "provider_version": str(dependency["provider_version"]),
            },
        )

    def _draft_validation_snapshot(
        self,
        project_id: str,
        draft: TrainingDraft,
    ) -> TrainingPreflightResponse:
        if draft.task != SEMANTIC_SEGMENTATION_TASK:
            return super()._draft_validation_snapshot(project_id, draft)
        return self.preflight(project_id, self._draft_like_payload(draft))
