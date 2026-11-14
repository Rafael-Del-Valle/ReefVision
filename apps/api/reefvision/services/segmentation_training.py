"""Task-aware extensions for detection and instance-segmentation training."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from reefvision.db.models import DatasetVersion, DatasetVersionItem, TrainingDraft
from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import (
    configure_provider_runtime,
    provider_preflight,
    provider_spec,
)
from reefvision.ml.ultralytics_registry import (
    validate_ultralytics_training_configuration,
)
from reefvision.schemas.training import (
    TrainingDraftWriteRequest,
    TrainingPreflightResponse,
    TrainingProviderArchitectureResponse,
    TrainingProviderResponse,
    TrainingTilingEstimateResponse,
)
from reefvision.services.training import (
    TRAINABLE_PROVIDER_ID,
    TRAINING_PRECISIONS,
    TRAINING_PROVIDER_ARCHITECTURE_TTL_SECONDS,
    TrainingService,
    _ultralytics_architecture_available,
)
from reefvision.services.training_tasks import (
    DETECTION_TASK,
    INSTANCE_SEGMENTATION_TASK,
    SUPPORTED_ULTRALYTICS_TRAINING_TASKS,
    TaskDatasetPreflight,
    task_dataset_preflight,
)
from reefvision.snapshot_cache import get_cached_snapshot


class SegmentationTrainingService(TrainingService):
    """Extend the stable detection workspace with Ultralytics segmentation."""

    def list_providers(self) -> list[TrainingProviderResponse]:
        architectures = [
            *self._cached_ultralytics_detect_architectures(),
            *self._cached_ultralytics_segment_architectures(),
        ]
        return [
            TrainingProviderResponse(
                provider_id=TRAINABLE_PROVIDER_ID,
                display_name="Ultralytics YOLO",
                provider_version=provider_spec(TRAINABLE_PROVIDER_ID).provider_version,
                supported_tasks=list(SUPPORTED_ULTRALYTICS_TRAINING_TASKS),
                supported_precision_modes=list(TRAINING_PRECISIONS),
                supports_tiling=False,
                supports_tuning=False,
                supports_packaged_desktop=True,
                warning=(
                    "Detection and polygon instance-segmentation training are "
                    "available. Raster masks remain reserved for the "
                    "semantic-segmentation provider slice."
                ),
                architectures=sorted(
                    architectures,
                    key=lambda item: (item.task, item.display_name.casefold()),
                ),
            )
        ]

    def _ultralytics_segment_architectures(
        self,
    ) -> list[TrainingProviderArchitectureResponse]:
        configure_provider_runtime(self.settings)
        try:
            models_root = Path(str(files("ultralytics.cfg").joinpath("models")))
        except Exception:
            return []
        architectures: list[TrainingProviderArchitectureResponse] = []
        for path in models_root.rglob("*-seg.yaml"):
            normalized = path.name.casefold()
            if any(token in normalized for token in ("-cls", "-pose", "-obb", "world", "yoloe")):
                continue
            architectures.append(
                TrainingProviderArchitectureResponse(
                    architecture_id=path.name,
                    display_name=path.name.removesuffix(".yaml"),
                    task=INSTANCE_SEGMENTATION_TASK,
                    source=str(path.relative_to(models_root)),
                )
            )
        deduped = {item.architecture_id: item for item in architectures}
        return sorted(
            deduped.values(),
            key=lambda item: item.display_name.casefold(),
        )

    def _cached_ultralytics_segment_architectures(
        self,
    ) -> list[TrainingProviderArchitectureResponse]:
        return get_cached_snapshot(
            (f"training_provider_segment_architectures:{self.settings.resolved_data_dir}"),
            self._ultralytics_segment_architectures,
            ttl_seconds=TRAINING_PROVIDER_ARCHITECTURE_TTL_SECONDS,
        ).value

    def _architectures_for_task(
        self,
        task: str,
    ) -> list[TrainingProviderArchitectureResponse]:
        if task == DETECTION_TASK:
            return self._cached_ultralytics_detect_architectures()
        if task == INSTANCE_SEGMENTATION_TASK:
            return self._cached_ultralytics_segment_architectures()
        return []

    def _apply_task_dataset_details(
        self,
        response: TrainingPreflightResponse,
        task_check: TaskDatasetPreflight,
    ) -> TrainingPreflightResponse:
        response.blockers = self._dedupe_messages([*response.blockers, *task_check.blockers])
        response.warnings = self._dedupe_messages([*response.warnings, *task_check.warnings])
        response.dataset.mask_annotation_count = (
            task_check.polygon_count + task_check.raster_mask_count
        )
        response.dataset.polygon_count = task_check.polygon_count
        response.dataset.raster_mask_count = task_check.raster_mask_count
        response.dataset.polygon_counts_by_split = dict(task_check.polygon_counts_by_split)
        response.dataset.raster_counts_by_split = dict(task_check.raster_counts_by_split)
        response.status = (
            "blocked"
            if response.blockers
            else "ready_with_warnings"
            if response.warnings
            else "ready"
        )
        return response

    def preflight(
        self,
        project_id: str,
        payload: TrainingDraftWriteRequest,
    ) -> TrainingPreflightResponse:
        project = self._project(project_id)
        resolved_catalog_selection = None
        if payload.catalog_model_id:
            try:
                resolved_catalog_selection = self.catalog.resolve_training_selection(
                    project.id,
                    payload.catalog_model_id,
                )
            except ValidationError:
                return super().preflight(project_id, payload)

        task = (
            resolved_catalog_selection.task
            if resolved_catalog_selection is not None
            else payload.task or ""
        )
        if task != INSTANCE_SEGMENTATION_TASK:
            response = super().preflight(project_id, payload)
            if task == DETECTION_TASK and payload.dataset_version_id:
                dataset_version = self._version(payload.dataset_version_id)
                if dataset_version.status == "complete":
                    items = self.versions.items_for_version(dataset_version.id)
                    response = self._apply_task_dataset_details(
                        response,
                        task_dataset_preflight(DETECTION_TASK, items),
                    )
            return response

        warnings: list[str] = []
        blockers: list[str] = []
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

        provider_id = (
            resolved_catalog_selection.provider_id
            if resolved_catalog_selection is not None
            else payload.provider_id or TRAINABLE_PROVIDER_ID
        )
        if provider_id != TRAINABLE_PROVIDER_ID:
            blockers.append("Only the pinned Ultralytics provider supports this segmentation slice")

        architecture = (
            resolved_catalog_selection.architecture
            if resolved_catalog_selection is not None
            else payload.architecture or ""
        )
        available_architectures = {
            item.architecture_id for item in self._cached_ultralytics_segment_architectures()
        }
        if not architecture:
            blockers.append(
                "Choose a local Ultralytics segmentation architecture before launching training"
            )
        elif not _ultralytics_architecture_available(
            architecture,
            available_architectures,
        ):
            blockers.append(
                "The selected segmentation architecture is not available in the "
                "installed pinned Ultralytics package"
            )

        if payload.precision not in TRAINING_PRECISIONS:
            blockers.append("Supported precision modes are fp32 and amp")

        initial_checkpoint_source = (
            resolved_catalog_selection.initial_checkpoint_source
            if resolved_catalog_selection is not None
            else payload.initial_checkpoint_source
        )
        initial_checkpoint_model_id = (
            resolved_catalog_selection.initial_checkpoint_model_id
            if resolved_catalog_selection is not None
            else payload.initial_checkpoint_model_id
        )
        if initial_checkpoint_source == "registered_model":
            if not initial_checkpoint_model_id:
                blockers.append(
                    "Choose a registered segmentation checkpoint or switch to scratch training"
                )
            else:
                model = self._model(initial_checkpoint_model_id)
                if (
                    model.project_id != project.id
                    or model.purpose != "segmenter"
                    or model.task != INSTANCE_SEGMENTATION_TASK
                ):
                    blockers.append(
                        "The selected checkpoint must be an Ultralytics segmentation "
                        "model from the same project"
                    )
                if model.provider_name != TRAINABLE_PROVIDER_ID:
                    blockers.append(
                        "Only Ultralytics segmentation checkpoints can seed this training flow"
                    )
        elif initial_checkpoint_source not in {"scratch", "managed_catalog"}:
            blockers.append("Unsupported checkpoint source")

        training_config = self._merged_training_config(payload.training_config)
        training_config["amp"] = payload.precision == "amp"
        try:
            validation = validate_ultralytics_training_configuration(
                task=INSTANCE_SEGMENTATION_TASK,
                mode="train",
                parameters=training_config,
                search_space=[],
                expected_ultralytics_version=provider_spec(TRAINABLE_PROVIDER_ID).provider_version,
                settings=self.settings,
            )
            warnings.extend(validation.warnings)
        except ValidationError as exc:
            blockers.append(str(exc))

        tuning_config = self._merged_tuning_config(payload.tuning_config)
        if tuning_config.get("mode", "disabled") != "disabled":
            blockers.append(
                "Tuning configuration can be saved, but segmentation tuning "
                "execution is not implemented"
            )

        tiling_config = self._merged_tiling_config(payload.tiling_config)
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
        if tiling_config.get("mode") != "none":
            blockers.append(
                "The segmentation runner currently launches only the no-tiling baseline"
            )

        dataset_summary = self._dataset_summary(version, items=version_items)
        task_check = task_dataset_preflight(task, version_items or [])
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

        dependency = provider_preflight(
            provider_id,
            self.settings,
            check_level="full",
        )
        if not dependency.ready:
            blockers.extend(
                [
                    *dependency.issues,
                    *[
                        f"{item.distribution_name} should be {item.required_version}"
                        for item in dependency.package_statuses
                        if item.status != "ok"
                    ],
                ]
            )

        resource_snapshot = self._resource_snapshot(payload.device)
        disk_free_gb = resource_snapshot.get("disk_free_gb")
        max_disk_usage_gb = float(
            self._merged_resource_limits(payload.resource_limits)["max_disk_usage_gb"]
        )
        if isinstance(disk_free_gb, (int, float)) and disk_free_gb < max_disk_usage_gb:
            warnings.append(
                "Requested disk budget exceeds currently available free space in "
                "the ReefVision data directory"
            )

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
                "provider_name": dependency.provider_name,
                "ready": dependency.ready,
                "status": dependency.status,
                "issues": list(dependency.issues),
            },
        )

    def _draft_validation_snapshot(
        self,
        project_id: str,
        draft: TrainingDraft,
    ) -> TrainingPreflightResponse:
        if draft.task != INSTANCE_SEGMENTATION_TASK:
            return super()._draft_validation_snapshot(project_id, draft)
        return self.preflight(project_id, self._draft_like_payload(draft))
