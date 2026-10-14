"""Training workspace services."""

from __future__ import annotations

import re
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    Job,
    ModelRegistration,
    Project,
    TrainingDraft,
    TrainingRun,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.dependencies import configure_provider_runtime, provider_preflight, provider_spec
from reefvision.ml.ultralytics_registry import (
    UltralyticsRegistrySnapshot,
    ultralytics_training_registry,
    validate_ultralytics_training_configuration,
)
from reefvision.ml.ultralytics_tuning import effective_search_space
from reefvision.repositories.dataset_versions import DatasetVersionRepository
from reefvision.repositories.jobs import JobRepository
from reefvision.repositories.models import ModelRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.repositories.training import TrainingRepository
from reefvision.schemas.training import (
    ExperimentCompareRequest,
    ExperimentCompareResponse,
    ExperimentRecordResponse,
    TrainingDatasetSummaryResponse,
    TrainingDraftPatchRequest,
    TrainingDraftResponse,
    TrainingDraftSummaryResponse,
    TrainingDraftWriteRequest,
    TrainingLeakageAuditResponse,
    TrainingPreflightResponse,
    TrainingProviderArchitectureResponse,
    TrainingProviderResponse,
    TrainingRunCreateRequest,
    TrainingRunResponse,
    TrainingTilingEstimateResponse,
    TrainingTilingPreviewTileResponse,
    TrainingTilingRequest,
)
from reefvision.services.model_catalog import ModelCatalogService
from reefvision.snapshot_cache import get_cached_snapshot
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

TRAINABLE_PROVIDER_ID = "ultralytics"
TRAINING_TASKS = ("detect",)
TRAINING_PRECISIONS = ("fp32", "amp")
TRAINING_PROVIDER_ARCHITECTURE_TTL_SECONDS = 600
DEFAULT_TILING_CONFIG: dict[str, Any] = {
    "mode": "none",
    "tile_width": 640,
    "tile_height": 640,
    "overlap_x": 0,
    "overlap_y": 0,
    "retain_edge_tiles": True,
}
DEFAULT_TRAINING_CONFIG: dict[str, Any] = {
    "epochs": 50,
    "patience": 20,
    "batch": 8,
    "imgsz": 640,
    "optimizer": "auto",
    "workers": 2,
    "cache": False,
    "amp": False,
    "val": True,
    "plots": True,
}
DEFAULT_TUNING_CONFIG: dict[str, Any] = {
    "mode": "disabled",
    "preset": "recommended",
    "max_trials": 20,
    "epochs_per_trial": 10,
    "patience": 10,
    "search_space": {},
}
DEFAULT_EVALUATION_CONFIG: dict[str, Any] = {
    "split": "validation",
    "conf": 0.25,
    "iou": 0.45,
    "max_det": 300,
}
DEFAULT_RESOURCE_LIMITS: dict[str, Any] = {
    "max_runtime_minutes": 180,
    "max_disk_usage_gb": 20,
    "max_workers": 2,
    "allowed_devices": ["auto"],
}


def _ultralytics_architecture_available(
    requested: str,
    available_architecture_ids: set[str],
) -> bool:
    """Match scaled YOLO catalog names to Ultralytics base architecture YAMLs."""

    requested_name = Path(requested).name.casefold()
    available = {
        Path(architecture_id).name.casefold() for architecture_id in available_architecture_ids
    }
    if requested_name in available:
        return True

    # The pinned loader also accepts P2/P6/ghost suffixes and the legacy P6
    # spelling (for example yolov8n6.yaml -> yolov8n-p6.yaml).
    requested_name = re.sub(r"^(yolov[58][nslmx])6\.yaml$", r"\1-p6.yaml", requested_name)
    match = re.fullmatch(r"(yolo(?:v)?\d+)[nslmx]((?:-[\w-]+)?\.yaml)", requested_name)
    if match is None:
        return False

    base_architecture = f"{match.group(1)}{match.group(2)}"
    return base_architecture in available


class TrainingService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.versions = DatasetVersionRepository(session)
        self.models = ModelRepository(session)
        self.jobs = JobRepository(session)
        self.training = TrainingRepository(session)
        self.catalog = ModelCatalogService(session, settings)

    def _project(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _version(self, version_id: str) -> DatasetVersion:
        version = self.versions.get_version(version_id)
        if version is None:
            raise NotFoundError("Dataset version not found")
        return version

    def _version_header(self, version_id: str) -> DatasetVersion:
        version = self.versions.get_version_header(version_id)
        if version is None:
            raise NotFoundError("Dataset version not found")
        return version

    def _draft(self, draft_id: str) -> TrainingDraft:
        draft = self.training.get_draft(draft_id)
        if draft is None:
            raise NotFoundError("Training draft not found")
        return draft

    def _run(self, run_id: str) -> TrainingRun:
        run = self.training.get_run(run_id)
        if run is None:
            raise NotFoundError("Training run not found")
        return run

    def _model(self, model_id: str) -> ModelRegistration:
        model = self.models.get(model_id)
        if model is None:
            raise NotFoundError("Model not found")
        return model

    def list_providers(self) -> list[TrainingProviderResponse]:
        warning = (
            "This Training foundation currently supports only Ultralytics object detection. "
            "Tuning is local and sequential; segmentation and non-Ultralytics tuning "
            "remain blocked."
        )
        return [
            TrainingProviderResponse(
                provider_id=TRAINABLE_PROVIDER_ID,
                display_name="Ultralytics YOLO",
                provider_version=provider_spec(TRAINABLE_PROVIDER_ID).provider_version,
                supported_tasks=list(TRAINING_TASKS),
                supported_precision_modes=list(TRAINING_PRECISIONS),
                supports_tiling=False,
                supports_tuning=True,
                supports_packaged_desktop=True,
                warning=warning,
                architectures=self._cached_ultralytics_detect_architectures(),
            )
        ]

    def get_provider_parameters(self, provider_id: str) -> UltralyticsRegistrySnapshot:
        if provider_id != TRAINABLE_PROVIDER_ID:
            raise NotFoundError("Training provider not found")
        return ultralytics_training_registry(self.settings)

    def list_drafts(self, project_id: str) -> list[TrainingDraftResponse]:
        self._project(project_id)
        return [self._draft_response(item) for item in self.training.list_drafts(project_id)]

    def list_draft_summaries(self, project_id: str) -> list[TrainingDraftSummaryResponse]:
        self._project(project_id)
        return [
            self._draft_summary_response(item)
            for item in self.training.list_draft_summaries(project_id)
        ]

    def get_draft(self, draft_id: str) -> TrainingDraftResponse:
        return self._draft_response(self._draft(draft_id))

    def create_draft(
        self, project_id: str, payload: TrainingDraftWriteRequest, *, commit: bool = True
    ) -> TrainingDraftResponse:
        project = self._project(project_id)
        draft = TrainingDraft(
            project_id=project_id,
            name=payload.name,
            run_name=payload.run_name or f"{project.slug}-train",
            notes=payload.notes,
            dataset_version_id=payload.dataset_version_id,
            task=payload.task,
            catalog_model_id=payload.catalog_model_id,
            provider_id=payload.provider_id,
            architecture=payload.architecture,
            initial_checkpoint_source=payload.initial_checkpoint_source,
            initial_checkpoint_model_id=payload.initial_checkpoint_model_id,
            resolved_model_asset_id=None,
            resolved_model_checksum=None,
            parameter_registry_version=None,
            selected_preset=None,
            installation_state=None,
            device=payload.device,
            precision=payload.precision,
            random_seed=payload.random_seed,
            tiling_config_json=self._merged_tiling_config(payload.tiling_config),
            training_config_json=self._merged_training_config(payload.training_config),
            tuning_config_json=self._merged_tuning_config(payload.tuning_config),
            evaluation_config_json=self._merged_evaluation_config(payload.evaluation_config),
            resource_limits_json=self._merged_resource_limits(payload.resource_limits),
            validation_state_json={},
        )
        self._apply_or_clear_catalog_selection(draft)
        self._refresh_dataset_snapshot_fields(draft)
        draft.validation_state_json = self._draft_validation_snapshot(project_id, draft).model_dump(
            mode="json"
        )
        self.training.add_draft(draft)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        self.session.refresh(draft)
        return self._draft_response(draft)

    def update_draft(
        self, draft_id: str, payload: TrainingDraftPatchRequest
    ) -> TrainingDraftResponse:
        draft = self._draft(draft_id)
        if payload.name is not None:
            draft.name = payload.name
        if payload.run_name is not None:
            draft.run_name = payload.run_name
        if payload.notes is not None:
            draft.notes = payload.notes
        if payload.dataset_version_id is not None:
            draft.dataset_version_id = payload.dataset_version_id or None
        if payload.task is not None:
            draft.task = payload.task
        if payload.catalog_model_id is not None:
            draft.catalog_model_id = payload.catalog_model_id or None
        if payload.provider_id is not None:
            draft.provider_id = payload.provider_id
        if payload.architecture is not None:
            draft.architecture = payload.architecture
        if payload.initial_checkpoint_source is not None:
            draft.initial_checkpoint_source = payload.initial_checkpoint_source
        if payload.initial_checkpoint_model_id is not None:
            draft.initial_checkpoint_model_id = payload.initial_checkpoint_model_id or None
        if payload.device is not None:
            draft.device = payload.device
        if payload.precision is not None:
            draft.precision = payload.precision
        if payload.random_seed is not None:
            draft.random_seed = payload.random_seed
        if payload.tiling_config is not None:
            draft.tiling_config_json = self._merged_tiling_config(payload.tiling_config)
        if payload.training_config is not None:
            draft.training_config_json = self._merged_training_config(payload.training_config)
        if payload.tuning_config is not None:
            draft.tuning_config_json = self._merged_tuning_config(payload.tuning_config)
        if payload.evaluation_config is not None:
            draft.evaluation_config_json = self._merged_evaluation_config(payload.evaluation_config)
        if payload.resource_limits is not None:
            draft.resource_limits_json = self._merged_resource_limits(payload.resource_limits)
        self._apply_or_clear_catalog_selection(draft)
        self._refresh_dataset_snapshot_fields(draft)
        draft.validation_state_json = self._draft_validation_snapshot(
            draft.project_id, draft
        ).model_dump(mode="json")
        self.session.commit()
        self.session.refresh(draft)
        return self._draft_response(draft)

    def delete_draft(self, draft_id: str) -> None:
        draft = self._draft(draft_id)
        self.training.delete_draft(draft)
        self.session.commit()

    def preflight(
        self, project_id: str, payload: TrainingDraftWriteRequest
    ) -> TrainingPreflightResponse:
        project = self._project(project_id)
        warnings: list[str] = []
        blockers: list[str] = []

        version = None
        version_items = None
        resolved_catalog_selection = None
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

        if payload.catalog_model_id:
            try:
                resolved_catalog_selection = self.catalog.resolve_training_selection(
                    project.id,
                    payload.catalog_model_id,
                )
            except ValidationError as exc:
                blockers.append(str(exc))

        task = (
            resolved_catalog_selection.task
            if resolved_catalog_selection is not None
            else payload.task or ""
        )
        if task not in TRAINING_TASKS:
            blockers.append("This Training foundation currently supports only object detection")

        provider_id = (
            resolved_catalog_selection.provider_id
            if resolved_catalog_selection is not None
            else payload.provider_id or TRAINABLE_PROVIDER_ID
        )
        if provider_id not in {TRAINABLE_PROVIDER_ID}:
            blockers.append(
                "Only the pinned Ultralytics provider is trainable in this foundation slice"
            )

        architecture = (
            resolved_catalog_selection.architecture
            if resolved_catalog_selection is not None
            else payload.architecture or ""
        )
        if not architecture:
            blockers.append("Choose a local Ultralytics architecture before launching training")
        elif not _ultralytics_architecture_available(
            architecture,
            {item.architecture_id for item in self._cached_ultralytics_detect_architectures()},
        ):
            blockers.append(
                "The selected architecture is not available in the installed pinned "
                "Ultralytics package"
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
                    "Choose a registered detector checkpoint or switch to scratch training"
                )
            else:
                model = self._model(initial_checkpoint_model_id)
                if model.project_id != project.id or model.purpose != "detector":
                    blockers.append(
                        "The selected checkpoint must be a detector model from the same project"
                    )
                if model.provider_name != TRAINABLE_PROVIDER_ID:
                    blockers.append(
                        "Only Ultralytics detector checkpoints can seed this training flow"
                    )
        elif initial_checkpoint_source not in {"scratch", "managed_catalog"}:
            blockers.append("Unsupported checkpoint source")

        training_config = self._merged_training_config(payload.training_config)
        training_config["amp"] = payload.precision == "amp"
        try:
            validation = validate_ultralytics_training_configuration(
                task="detect",
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
            try:
                max_trials = int(tuning_config.get("max_trials", 20))
                trial_epochs = int(tuning_config.get("epochs_per_trial", 10))
                patience = int(tuning_config.get("patience", 10))
                if not 1 <= max_trials <= 1000:
                    raise ValueError("Maximum trials must be between 1 and 1,000")
                if not 1 <= trial_epochs <= 1000:
                    raise ValueError("Epochs per trial must be between 1 and 1,000")
                if not 0 <= patience <= max_trials:
                    raise ValueError("Tuning patience must be between 0 and maximum trials")
                effective_search_space(tuning_config)
            except (TypeError, ValueError) as exc:
                blockers.append(str(exc))

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
                "Tiled training configuration is planned in this workspace, but the "
                "training runner currently launches only the no-tiling baseline"
            )

        dataset_summary = self._dataset_summary(version, items=version_items)
        leakage_audit = self._leakage_audit(version, items=version_items)
        warnings.extend(leakage_audit.warnings)
        blockers.extend(leakage_audit.blockers)

        dependency = provider_preflight(provider_id, self.settings, check_level="full")
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
                "Requested disk budget exceeds currently available free space in the "
                "ReefVision data directory"
            )

        status = "blocked" if blockers else "ready_with_warnings" if warnings else "ready"
        return TrainingPreflightResponse(
            status=status,
            warnings=self._dedupe_messages(warnings),
            blockers=self._dedupe_messages(blockers),
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

    def estimate_tiling(
        self, project_id: str, payload: TrainingTilingRequest
    ) -> TrainingTilingEstimateResponse:
        version = self._version(payload.dataset_version_id)
        if version.project_id != project_id:
            raise ValidationError("The dataset version must belong to the selected project")
        return self._tiling_estimate(
            version,
            self._merged_tiling_config(payload.tiling_config),
        )

    def create_run(
        self, project_id: str, payload: TrainingRunCreateRequest, *, commit: bool = True
    ) -> TrainingRunResponse:
        draft = self._draft(payload.draft_id)
        if draft.project_id != project_id:
            raise ValidationError("Training drafts must belong to the selected project")
        preflight = self.preflight(project_id, self._draft_like_payload(draft))
        if preflight.status == "blocked":
            raise ValidationError(
                preflight.blockers[0] if preflight.blockers else "Training preflight failed"
            )
        self._refresh_dataset_snapshot_fields(draft, include_split_manifest=True)

        run = TrainingRun(
            project_id=project_id,
            draft_id=draft.id,
            dataset_version_id=draft.dataset_version_id,
            dataset_manifest_sha256=draft.dataset_manifest_sha256 or "",
            split_manifest_sha256=draft.split_manifest_sha256 or "",
            task=draft.task or "detect",
            catalog_model_id=draft.catalog_model_id,
            provider_id=draft.provider_id or TRAINABLE_PROVIDER_ID,
            architecture=draft.architecture or "",
            initial_checkpoint_source=draft.initial_checkpoint_source,
            initial_checkpoint_model_id=draft.initial_checkpoint_model_id,
            resolved_model_asset_id=draft.resolved_model_asset_id,
            resolved_model_checksum=draft.resolved_model_checksum,
            parameter_registry_version=draft.parameter_registry_version,
            selected_preset=draft.selected_preset,
            installation_state=draft.installation_state,
            device=draft.device,
            precision=draft.precision,
            run_name=draft.run_name or draft.name,
            notes=draft.notes,
            random_seed=draft.random_seed,
            tiling_config_json=dict(draft.tiling_config_json),
            training_config_json=dict(draft.training_config_json),
            tuning_config_json=dict(draft.tuning_config_json),
            evaluation_config_json=dict(draft.evaluation_config_json),
            resource_limits_json=dict(draft.resource_limits_json),
            preflight_report_json=preflight.model_dump(mode="json"),
            draft_snapshot_json=self._draft_response(draft).model_dump(mode="json"),
            status="queued",
            stage="queued",
            progress_total_epochs=(
                int(dict(draft.tuning_config_json).get("max_trials", 20))
                if dict(draft.tuning_config_json).get("mode", "disabled") != "disabled"
                else int(
                    dict(draft.training_config_json).get(
                        "epochs", DEFAULT_TRAINING_CONFIG["epochs"]
                    )
                )
            ),
            warnings_json=list(preflight.warnings),
        )
        self.training.add_run(run)
        self.session.flush()
        job = Job(
            project_id=project_id,
            job_type="training",
            status="queued",
            progress_total=max(run.progress_total_epochs, 1),
            request_json={"training_run_id": run.id},
            result_json={"stage": "queued"},
        )
        self.jobs.add(job)
        self.session.flush()
        run.job_id = job.id
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        self.session.refresh(run)
        return self._run_response(run)

    def list_runs(self, project_id: str) -> list[TrainingRunResponse]:
        self._project(project_id)
        return [self._run_response(item) for item in self.training.list_runs(project_id)]

    def get_run(self, run_id: str) -> TrainingRunResponse:
        return self._run_response(self._run(run_id))

    def artifact_file(self, run_id: str, artifact_index: int) -> Path:
        run = self._run(run_id)
        artifacts = run.artifact_manifest_json.get("artifacts", [])
        if (
            not isinstance(artifacts, list)
            or artifact_index < 0
            or artifact_index >= len(artifacts)
        ):
            raise NotFoundError("Training artifact not found")
        artifact = artifacts[artifact_index]
        if not isinstance(artifact, dict) or not isinstance(artifact.get("relative_path"), str):
            raise NotFoundError("Training artifact metadata is unavailable")
        path = resolve_managed_project_path(self.settings, artifact["relative_path"])
        if not path.is_file():
            raise NotFoundError("Training artifact file is unavailable")
        return path

    def cancel_run(self, run_id: str) -> TrainingRunResponse:
        run = self._run(run_id)
        if run.job_id is None:
            raise ValidationError("This training run is not attached to a background job")
        job = self.jobs.get(run.job_id)
        if job is None:
            raise ValidationError("The background job for this training run no longer exists")
        if job.status == "queued":
            job.status = "cancelled"
            run.status = "cancelled"
            run.stage = "cancelled"
            run.completed_at = run.updated_at
        elif job.status == "running":
            job.status = "cancel_requested"
            run.status = "cancel_requested"
            run.stage = "cancel_requested"
        else:
            raise ValidationError("Only queued or running training jobs can be cancelled")
        self.session.commit()
        self.session.refresh(run)
        return self._run_response(run)

    def list_experiments(self, project_id: str) -> list[ExperimentRecordResponse]:
        self._project(project_id)
        return [
            ExperimentRecordResponse.model_validate(item)
            for item in self.training.list_experiments(project_id)
        ]

    def compare_experiments(self, payload: ExperimentCompareRequest) -> ExperimentCompareResponse:
        experiments = []
        for experiment_id in payload.experiment_ids:
            experiment = self.training.get_experiment(experiment_id)
            if experiment is None:
                raise NotFoundError("Experiment not found")
            experiments.append(experiment)
        warnings: list[str] = []
        dataset_hashes = {item.dataset_manifest_sha256 for item in experiments}
        split_hashes = {item.split_manifest_sha256 for item in experiments}
        tasks = {item.task for item in experiments}
        providers = {item.provider_id for item in experiments}
        if len(dataset_hashes) > 1:
            warnings.append("Compared experiments use different dataset manifests")
        if len(split_hashes) > 1:
            warnings.append("Compared experiments use different split manifests")
        if len(tasks) > 1:
            warnings.append("Compared experiments use different tasks")
        if len(providers) > 1:
            warnings.append("Compared experiments use different providers")
        return ExperimentCompareResponse(
            experiments=[ExperimentRecordResponse.model_validate(item) for item in experiments],
            warnings=warnings,
        )

    def _draft_response(self, draft: TrainingDraft) -> TrainingDraftResponse:
        return TrainingDraftResponse(
            id=draft.id,
            project_id=draft.project_id,
            name=draft.name,
            run_name=draft.run_name,
            notes=draft.notes,
            dataset_version_id=draft.dataset_version_id,
            dataset_manifest_sha256=draft.dataset_manifest_sha256,
            split_manifest_sha256=draft.split_manifest_sha256,
            task=draft.task,
            catalog_model_id=draft.catalog_model_id,
            provider_id=draft.provider_id,
            architecture=draft.architecture,
            initial_checkpoint_source=draft.initial_checkpoint_source,
            initial_checkpoint_model_id=draft.initial_checkpoint_model_id,
            resolved_model_asset_id=draft.resolved_model_asset_id,
            resolved_model_checksum=draft.resolved_model_checksum,
            parameter_registry_version=draft.parameter_registry_version,
            selected_preset=draft.selected_preset,
            installation_state=draft.installation_state,
            device=draft.device,
            precision=draft.precision,
            random_seed=draft.random_seed,
            tiling_config=dict(draft.tiling_config_json),
            training_config=dict(draft.training_config_json),
            tuning_config=dict(draft.tuning_config_json),
            evaluation_config=dict(draft.evaluation_config_json),
            resource_limits=dict(draft.resource_limits_json),
            validation_state=dict(draft.validation_state_json),
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )

    def _run_response(self, run: TrainingRun) -> TrainingRunResponse:
        return TrainingRunResponse(
            id=run.id,
            project_id=run.project_id,
            draft_id=run.draft_id,
            dataset_version_id=run.dataset_version_id,
            dataset_manifest_sha256=run.dataset_manifest_sha256,
            split_manifest_sha256=run.split_manifest_sha256,
            task=run.task,
            catalog_model_id=run.catalog_model_id,
            provider_id=run.provider_id,
            architecture=run.architecture,
            initial_checkpoint_source=run.initial_checkpoint_source,
            initial_checkpoint_model_id=run.initial_checkpoint_model_id,
            resolved_model_asset_id=run.resolved_model_asset_id,
            resolved_model_checksum=run.resolved_model_checksum,
            parameter_registry_version=run.parameter_registry_version,
            selected_preset=run.selected_preset,
            installation_state=run.installation_state,
            device=run.device,
            precision=run.precision,
            run_name=run.run_name,
            notes=run.notes,
            random_seed=run.random_seed,
            tiling_config=dict(run.tiling_config_json),
            training_config=dict(run.training_config_json),
            tuning_config=dict(run.tuning_config_json),
            evaluation_config=dict(run.evaluation_config_json),
            resource_limits=dict(run.resource_limits_json),
            preflight_report=dict(run.preflight_report_json),
            draft_snapshot=dict(run.draft_snapshot_json),
            status=run.status,
            stage=run.stage,
            progress_epoch=run.progress_epoch,
            progress_total_epochs=run.progress_total_epochs,
            metrics=dict(run.metrics_json),
            metrics_history=dict(run.metrics_history_json),
            warnings=list(run.warnings_json),
            artifact_manifest=dict(run.artifact_manifest_json),
            logs_path=run.logs_path,
            result_checkpoint_path=run.result_checkpoint_path,
            job_id=run.job_id,
            error_message=run.error_message,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            updated_at=run.updated_at,
        )

    def _draft_summary_response(self, draft: TrainingDraft) -> TrainingDraftSummaryResponse:
        validation_state = dict(draft.validation_state_json)
        warnings = validation_state.get("warnings", [])
        blockers = validation_state.get("blockers", [])
        return TrainingDraftSummaryResponse(
            id=draft.id,
            project_id=draft.project_id,
            name=draft.name,
            run_name=draft.run_name,
            dataset_version_id=draft.dataset_version_id,
            task=draft.task,
            catalog_model_id=draft.catalog_model_id,
            provider_id=draft.provider_id,
            architecture=draft.architecture,
            initial_checkpoint_source=draft.initial_checkpoint_source,
            validation_status=validation_state.get("status"),
            warning_count=len(warnings) if isinstance(warnings, list) else 0,
            blocker_count=len(blockers) if isinstance(blockers, list) else 0,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )

    def _refresh_dataset_snapshot_fields(
        self,
        draft: TrainingDraft,
        *,
        include_split_manifest: bool = False,
    ) -> None:
        if not draft.dataset_version_id:
            draft.dataset_manifest_sha256 = None
            draft.split_manifest_sha256 = None
            return
        version = self._version_header(draft.dataset_version_id)
        draft.dataset_manifest_sha256 = version.manifest_sha256
        if include_split_manifest:
            draft.split_manifest_sha256 = self._split_manifest_sha(
                self._version(draft.dataset_version_id)
            )
        elif not draft.split_manifest_sha256:
            draft.split_manifest_sha256 = None

    def _split_manifest_sha(
        self,
        version: DatasetVersion,
        items: list[DatasetVersionItem] | None = None,
    ) -> str:
        items = items if items is not None else self.versions.items_for_version(version.id)
        payload = [
            {
                "image_id": item.image_id,
                "split": item.split,
                "group_key": item.group_key,
                "snapshot_sha256": item.snapshot_sha256,
            }
            for item in items
        ]
        return canonical_json_sha256(payload)

    def _dataset_summary(
        self,
        version: DatasetVersion | None,
        *,
        items: list[DatasetVersionItem] | None = None,
    ) -> TrainingDatasetSummaryResponse:
        if version is None:
            return TrainingDatasetSummaryResponse(
                dataset_version_id=None,
                dataset_manifest_sha256=None,
                split_manifest_sha256=None,
                image_count=0,
                annotation_count=0,
                split_counts={},
                group_count=0,
                warnings=[],
            )
        resolved_items = items if items is not None else self.versions.items_for_version(version.id)
        split_counts: dict[str, int] = {}
        groups = {item.group_key for item in resolved_items if item.group_key}
        for item in resolved_items:
            split_counts[item.split] = split_counts.get(item.split, 0) + 1
        return TrainingDatasetSummaryResponse(
            dataset_version_id=version.id,
            dataset_manifest_sha256=version.manifest_sha256,
            split_manifest_sha256=self._split_manifest_sha(version, resolved_items),
            image_count=version.image_count,
            annotation_count=version.annotation_count,
            split_counts=split_counts,
            group_count=len(groups),
            warnings=list(version.warnings_json),
        )

    def _leakage_audit(
        self,
        version: DatasetVersion | None,
        *,
        items: list[DatasetVersionItem] | None = None,
    ) -> TrainingLeakageAuditResponse:
        if version is None:
            return TrainingLeakageAuditResponse(
                blocked=True,
                warnings=[],
                blockers=["A dataset version is required before leakage can be audited"],
                image_leak_count=0,
                group_leak_count=0,
            )
        resolved_items = items if items is not None else self.versions.items_for_version(version.id)
        image_splits: dict[str, set[str]] = {}
        group_splits: dict[str, set[str]] = {}
        for item in resolved_items:
            image_splits.setdefault(item.image_id, set()).add(item.split)
            if item.group_key:
                group_splits.setdefault(item.group_key, set()).add(item.split)
        image_leak_count = sum(1 for splits in image_splits.values() if len(splits) > 1)
        group_leak_count = sum(1 for splits in group_splits.values() if len(splits) > 1)
        blockers: list[str] = []
        if image_leak_count:
            blockers.append("One or more source images appear in multiple dataset splits")
        if group_leak_count:
            blockers.append("One or more source groups appear in multiple dataset splits")
        return TrainingLeakageAuditResponse(
            blocked=bool(blockers),
            warnings=[],
            blockers=blockers,
            image_leak_count=image_leak_count,
            group_leak_count=group_leak_count,
        )

    def _resource_snapshot(self, requested_device: str) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "requested_device": requested_device,
            "disk_free_gb": round(
                shutil.disk_usage(self.settings.resolved_data_dir).free / (1024**3), 2
            ),
        }
        try:
            import psutil

            snapshot["ram_total_gb"] = round(psutil.virtual_memory().total / (1024**3), 2)
            snapshot["ram_available_gb"] = round(psutil.virtual_memory().available / (1024**3), 2)
        except Exception:
            snapshot["ram_total_gb"] = None
            snapshot["ram_available_gb"] = None

        try:
            import torch

            snapshot["cuda_available"] = bool(torch.cuda.is_available())
            devices: list[dict[str, Any]] = []
            if torch.cuda.is_available():
                for index in range(torch.cuda.device_count()):
                    props = torch.cuda.get_device_properties(index)
                    devices.append(
                        {
                            "index": index,
                            "name": props.name,
                            "vram_total_gb": round(props.total_memory / (1024**3), 2),
                        }
                    )
                    if props.total_memory / (1024**3) <= 12.5:
                        snapshot.setdefault("warnings", []).append(
                            "The selected pinned stack is running on a 12 GB class GPU, "
                            "so larger batches or image sizes may exceed VRAM."
                        )
            snapshot["cuda_devices"] = devices
        except Exception:
            snapshot["cuda_available"] = False
            snapshot["cuda_devices"] = []
        return snapshot

    def _tiling_estimate(
        self,
        version: DatasetVersion,
        tiling_config: dict[str, Any],
        *,
        items: list[DatasetVersionItem] | None = None,
    ) -> TrainingTilingEstimateResponse:
        mode = str(tiling_config.get("mode", "none"))
        resolved_items = items if items is not None else self.versions.items_for_version(version.id)
        if mode == "none":
            preview = [
                TrainingTilingPreviewTileResponse(
                    image_id=item.image_id,
                    split=item.split,
                    x=0,
                    y=0,
                    width=item.width_px,
                    height=item.height_px,
                    retained_annotation_count=item.annotation_count,
                )
                for item in resolved_items[:5]
            ]
            avg_area = (
                sum(item.width_px * item.height_px for item in resolved_items) / len(resolved_items)
                if resolved_items
                else 0
            )
            return TrainingTilingEstimateResponse(
                blocked=False,
                warnings=[],
                tile_count=len(resolved_items),
                positive_tile_count=sum(1 for item in resolved_items if item.annotation_count > 0),
                background_tile_count=sum(
                    1 for item in resolved_items if item.annotation_count == 0
                ),
                estimated_storage_bytes=int(avg_area * len(resolved_items) * 3),
                preview_tiles=preview,
            )

        tile_width = int(tiling_config.get("tile_width", 640))
        tile_height = int(tiling_config.get("tile_height", 640))
        overlap_x = int(tiling_config.get("overlap_x", 0))
        overlap_y = int(tiling_config.get("overlap_y", 0))
        if tile_width <= 0 or tile_height <= 0:
            return TrainingTilingEstimateResponse(
                blocked=True,
                warnings=[],
                tile_count=0,
                positive_tile_count=0,
                background_tile_count=0,
                estimated_storage_bytes=0,
                preview_tiles=[],
            )
        if overlap_x >= tile_width or overlap_y >= tile_height:
            return TrainingTilingEstimateResponse(
                blocked=True,
                warnings=["Overlap must be smaller than tile dimensions"],
                tile_count=0,
                positive_tile_count=0,
                background_tile_count=0,
                estimated_storage_bytes=0,
                preview_tiles=[],
            )
        warnings = [
            "Tiling preview currently evaluates box-center retention only; polygon and "
            "mask clipping are not part of the current annotation model.",
        ]
        tile_count = 0
        positive_tile_count = 0
        background_tile_count = 0
        preview_tiles: list[TrainingTilingPreviewTileResponse] = []
        for item in resolved_items:
            stride_x = max(tile_width - overlap_x, 1)
            stride_y = max(tile_height - overlap_y, 1)
            x_positions = self._tile_positions(item.width_px, tile_width, stride_x)
            y_positions = self._tile_positions(item.height_px, tile_height, stride_y)
            for y in y_positions:
                for x in x_positions:
                    retained = 0
                    for annotation in item.annotation_snapshot_json:
                        center_x = (float(annotation["x_min"]) + float(annotation["x_max"])) / 2.0
                        center_y = (float(annotation["y_min"]) + float(annotation["y_max"])) / 2.0
                        if x <= center_x < x + tile_width and y <= center_y < y + tile_height:
                            retained += 1
                    tile_count += 1
                    if retained:
                        positive_tile_count += 1
                    else:
                        background_tile_count += 1
                    if len(preview_tiles) < 6:
                        preview_tiles.append(
                            TrainingTilingPreviewTileResponse(
                                image_id=item.image_id,
                                split=item.split,
                                x=x,
                                y=y,
                                width=min(tile_width, item.width_px - x),
                                height=min(tile_height, item.height_px - y),
                                retained_annotation_count=retained,
                            )
                        )
        return TrainingTilingEstimateResponse(
            blocked=False,
            warnings=warnings,
            tile_count=tile_count,
            positive_tile_count=positive_tile_count,
            background_tile_count=background_tile_count,
            estimated_storage_bytes=tile_count * tile_width * tile_height * 3,
            preview_tiles=preview_tiles,
        )

    def _tile_positions(self, full_size: int, tile_size: int, stride: int) -> list[int]:
        if full_size <= tile_size:
            return [0]
        positions = list(range(0, max(full_size - tile_size, 0) + 1, stride))
        last = full_size - tile_size
        if positions[-1] != last:
            positions.append(last)
        return positions

    def _merged_tiling_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {**DEFAULT_TILING_CONFIG, **(config or {})}

    def _merged_training_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {**DEFAULT_TRAINING_CONFIG, **(config or {})}

    def _merged_tuning_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {**DEFAULT_TUNING_CONFIG, **(config or {})}

    def _merged_evaluation_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {**DEFAULT_EVALUATION_CONFIG, **(config or {})}

    def _merged_resource_limits(self, config: dict[str, Any]) -> dict[str, Any]:
        return {**DEFAULT_RESOURCE_LIMITS, **(config or {})}

    def _draft_like_payload(self, draft: TrainingDraft) -> TrainingDraftWriteRequest:
        return TrainingDraftWriteRequest(
            name=draft.name,
            run_name=draft.run_name,
            notes=draft.notes,
            dataset_version_id=draft.dataset_version_id,
            task=draft.task,
            catalog_model_id=draft.catalog_model_id,
            provider_id=draft.provider_id,
            architecture=draft.architecture,
            initial_checkpoint_source=draft.initial_checkpoint_source,
            initial_checkpoint_model_id=draft.initial_checkpoint_model_id,
            device=draft.device,
            precision=draft.precision,
            random_seed=draft.random_seed,
            tiling_config=dict(draft.tiling_config_json),
            training_config=dict(draft.training_config_json),
            tuning_config=dict(draft.tuning_config_json),
            evaluation_config=dict(draft.evaluation_config_json),
            resource_limits=dict(draft.resource_limits_json),
        )

    def _apply_or_clear_catalog_selection(self, draft: TrainingDraft) -> None:
        if not draft.catalog_model_id:
            self._clear_catalog_selection(draft)
            return
        selection = self.catalog.resolve_training_selection(
            draft.project_id, draft.catalog_model_id
        )
        draft.task = selection.task
        draft.provider_id = selection.provider_id
        draft.architecture = selection.architecture
        draft.initial_checkpoint_source = selection.initial_checkpoint_source
        draft.initial_checkpoint_model_id = selection.initial_checkpoint_model_id
        draft.resolved_model_asset_id = selection.resolved_model_asset_id
        draft.resolved_model_checksum = selection.resolved_model_checksum
        draft.parameter_registry_version = selection.parameter_registry_version
        draft.selected_preset = selection.selected_preset
        draft.installation_state = selection.installation_state

    def _clear_catalog_selection(self, draft: TrainingDraft) -> None:
        draft.resolved_model_asset_id = None
        draft.resolved_model_checksum = None
        draft.parameter_registry_version = None
        draft.selected_preset = None
        draft.installation_state = None

    def _ultralytics_detect_architectures(self) -> list[TrainingProviderArchitectureResponse]:
        configure_provider_runtime(self.settings)
        try:
            models_root = Path(str(files("ultralytics.cfg").joinpath("models")))
        except Exception:
            return []
        architectures: list[TrainingProviderArchitectureResponse] = []
        for path in models_root.rglob("*.yaml"):
            name = path.name
            normalized = name.casefold()
            if any(
                token in normalized
                for token in ("-seg", "-cls", "-pose", "-obb", "world", "yoloe", "rtdetr")
            ):
                continue
            architectures.append(
                TrainingProviderArchitectureResponse(
                    architecture_id=name,
                    display_name=name.replace(".yaml", ""),
                    task="detect",
                    source=str(path.relative_to(models_root)),
                )
            )
        deduped = {item.architecture_id: item for item in architectures}
        return sorted(deduped.values(), key=lambda item: item.display_name.casefold())

    def _cached_ultralytics_detect_architectures(
        self,
    ) -> list[TrainingProviderArchitectureResponse]:
        return get_cached_snapshot(
            f"training_provider_architectures:{self.settings.resolved_data_dir}",
            self._ultralytics_detect_architectures,
            ttl_seconds=TRAINING_PROVIDER_ARCHITECTURE_TTL_SECONDS,
        ).value

    def _draft_validation_snapshot(
        self,
        project_id: str,
        draft: TrainingDraft,
    ) -> TrainingPreflightResponse:
        warnings: list[str] = []
        blockers: list[str] = []
        version = None
        if draft.dataset_version_id:
            version = self._version_header(draft.dataset_version_id)
            if version.project_id != project_id:
                raise ValidationError(
                    "Training drafts must reference a dataset version from the same project"
                )
            if version.status != "complete":
                blockers.append(
                    "Only complete immutable dataset versions may be selected for training"
                )
        else:
            blockers.append("Select an immutable dataset version before launching training")

        if draft.task and draft.task not in TRAINING_TASKS:
            blockers.append("This Training foundation currently supports only object detection")
        if draft.provider_id and draft.provider_id != TRAINABLE_PROVIDER_ID:
            blockers.append(
                "Only the pinned Ultralytics provider is trainable in this foundation slice"
            )
        if not draft.architecture:
            blockers.append("Choose a local Ultralytics architecture before launching training")
        elif not _ultralytics_architecture_available(
            draft.architecture,
            {item.architecture_id for item in self._cached_ultralytics_detect_architectures()},
        ):
            blockers.append(
                "The selected architecture is not available in the installed pinned "
                "Ultralytics package"
            )
        if draft.precision not in TRAINING_PRECISIONS:
            blockers.append("Supported precision modes are fp32 and amp")
        if (
            draft.initial_checkpoint_source == "registered_model"
            and not draft.initial_checkpoint_model_id
        ):
            blockers.append("Choose a registered detector checkpoint or switch to scratch training")
        elif draft.initial_checkpoint_source not in {
            "scratch",
            "registered_model",
            "managed_catalog",
        }:
            blockers.append("Unsupported checkpoint source")

        if draft.catalog_model_id and not draft.parameter_registry_version:
            warnings.append("Catalog selection details are still being resolved.")
        if (
            version is not None
            and version.status == "complete"
            and draft.split_manifest_sha256 is None
        ):
            warnings.append("Detailed dataset split validation will refresh before launch.")

        status = "blocked" if blockers else "ready_with_warnings" if warnings else "ready"
        return TrainingPreflightResponse(
            status=status,
            warnings=self._dedupe_messages(warnings),
            blockers=self._dedupe_messages(blockers),
            dataset=TrainingDatasetSummaryResponse(
                dataset_version_id=version.id if version is not None else None,
                dataset_manifest_sha256=version.manifest_sha256 if version is not None else None,
                split_manifest_sha256=draft.split_manifest_sha256,
                image_count=version.image_count if version is not None else 0,
                annotation_count=version.annotation_count if version is not None else 0,
                split_counts={},
                group_count=0,
                warnings=list(version.warnings_json) if version is not None else [],
            ),
            leakage_audit=TrainingLeakageAuditResponse(
                blocked=version is None,
                warnings=[],
                blockers=(
                    ["A dataset version is required before leakage can be audited"]
                    if version is None
                    else []
                ),
                image_leak_count=0,
                group_leak_count=0,
            ),
            resource_snapshot={"requested_device": draft.device, "status": "deferred"},
            provider_dependency_status={
                "provider_name": draft.provider_id or TRAINABLE_PROVIDER_ID,
                "status": "deferred",
                "ready": None,
            },
        )

    def _dedupe_messages(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered
