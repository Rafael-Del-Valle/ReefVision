"""Model-catalog loading, validation, local-state composition, and training resolution."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, Project
from reefvision.domain.errors import CatalogResourceError, NotFoundError, ValidationError
from reefvision.ml.optional_transformers_runtime import (
    OPTIONAL_MODEL_SPECS,
    optional_model_status,
)
from reefvision.repositories.models import ModelRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.model_catalog import (
    CatalogInstallationState,
    CatalogTask,
    CatalogWorkflow,
    ModelCatalogEntryResponse,
    ModelCatalogResponse,
    TrackerCatalogResponse,
)
from reefvision.storage.catalog_models import (
    catalog_asset_path,
    load_catalog_manifest,
    relative_catalog_asset_path,
)

MODEL_CATALOG_FILENAME = "model_catalog.json"
TRACKER_CATALOG_FILENAME = "tracker_catalog.json"
EXPECTED_MODEL_CATALOG_SCHEMA = 2
EXPECTED_MODEL_CATALOG_VERSION = "2.0.0"


@dataclass(frozen=True)
class ResolvedTrainingCatalogSelection:
    catalog_model_id: str
    task: str
    provider_id: str
    architecture: str | None
    initial_checkpoint_source: str
    initial_checkpoint_model_id: str | None
    resolved_model_asset_id: str | None
    resolved_model_checksum: str | None
    parameter_registry_version: str | None
    installation_state: str
    selected_preset: str


def clear_model_catalog_cache() -> None:
    _load_static_model_catalog.cache_clear()
    _load_static_tracker_catalog.cache_clear()


def _execution_mode() -> str:
    if vars(sys).get("_MEIPASS"):
        return "pyinstaller_sidecar"
    environment = os.environ.get("REEFVISION_ENV", "source").strip().casefold()
    return "tauri_desktop_development" if environment == "desktop" else environment or "source"


def _catalog_resource_candidates(filename: str) -> list[Path]:
    candidates: list[Path] = []
    configured_dir = os.environ.get("REEFVISION_CONFIG_DIR")
    if configured_dir and not configured_dir.isspace():
        candidates.append(Path(configured_dir).expanduser() / filename)

    bundle_root = vars(sys).get("_MEIPASS")
    if bundle_root:
        candidates.append(Path(str(bundle_root)).resolve() / "config" / filename)

    executable = getattr(sys, "executable", None)
    if executable:
        candidates.append(Path(executable).resolve().parent / "config" / filename)

    candidates.append(Path(__file__).resolve().parents[4] / "config" / filename)

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve(strict=False)).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_candidates.append(candidate)
    return unique_candidates


def _catalog_resource_error(filename: str, message: str) -> CatalogResourceError:
    candidates = _catalog_resource_candidates(filename)
    details: dict[str, object] = {
        "error": "catalog_resource_error",
        "reason": message,
        "expected_path": str(candidates[0]) if candidates else filename,
        "searched_paths": [str(candidate) for candidate in candidates],
        "execution_mode": _execution_mode(),
        "application_version": __version__,
        "catalog_version": EXPECTED_MODEL_CATALOG_VERSION,
        "recovery_action": (
            "Repair or reinstall ReefVision so config/model_catalog.json is restored, then retry."
        ),
    }
    return CatalogResourceError(message, details=details)


def _resolve_catalog_resource(filename: str) -> Path:
    for candidate in _catalog_resource_candidates(filename):
        if candidate.is_file():
            return candidate
    raise _catalog_resource_error(filename, f"Packaged catalog resource was not found: {filename}")


@lru_cache
def _load_static_model_catalog() -> ModelCatalogResponse:
    catalog_file = _resolve_catalog_resource(MODEL_CATALOG_FILENAME)
    try:
        payload = json.loads(catalog_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _catalog_resource_error(
            MODEL_CATALOG_FILENAME, f"Model catalog JSON could not be read: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise _catalog_resource_error(
            MODEL_CATALOG_FILENAME, "Model catalog root must be an object"
        )
    if payload.get("schema_version") != EXPECTED_MODEL_CATALOG_SCHEMA:
        raise _catalog_resource_error(
            MODEL_CATALOG_FILENAME,
            f"Unsupported catalog schema version: {payload.get('schema_version')!r}",
        )

    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        raise _catalog_resource_error(MODEL_CATALOG_FILENAME, "Model catalog models must be a list")

    warnings: list[str] = []
    models: list[ModelCatalogEntryResponse] = []
    seen: set[str] = set()
    for index, raw_entry in enumerate(raw_models):
        try:
            entry = ModelCatalogEntryResponse.model_validate(raw_entry)
            if entry.catalog_id in seen:
                raise ValueError(f"duplicate catalog_id {entry.catalog_id}")
            seen.add(entry.catalog_id)
            models.append(entry)
        except (PydanticValidationError, ValueError) as exc:
            warnings.append(f"Entry {index} was rejected: {exc}")
    if not models:
        raise _catalog_resource_error(
            MODEL_CATALOG_FILENAME,
            f"Catalog validation rejected all {len(raw_models)} entries",
        )
    return ModelCatalogResponse(
        schema_version=EXPECTED_MODEL_CATALOG_SCHEMA,
        catalog_version=str(payload.get("catalog_version") or EXPECTED_MODEL_CATALOG_VERSION),
        application_version=__version__,
        models=models,
        validation_warnings=warnings,
        rejected_entries=len(raw_models) - len(models),
        source_path=str(catalog_file),
        last_refresh_timestamp=datetime.now(UTC),
    )


@lru_cache
def _load_static_tracker_catalog() -> TrackerCatalogResponse:
    tracker_file = _resolve_catalog_resource(TRACKER_CATALOG_FILENAME)
    try:
        payload = json.loads(tracker_file.read_text(encoding="utf-8"))
        return TrackerCatalogResponse.model_validate(payload)
    except (OSError, json.JSONDecodeError, PydanticValidationError) as exc:
        raise _catalog_resource_error(
            TRACKER_CATALOG_FILENAME, f"Tracker catalog could not be loaded: {exc}"
        ) from exc


def validate_catalog_startup() -> list[str]:
    """Warm valid resources without preventing the API from reporting structured errors."""

    warnings: list[str] = []
    try:
        warnings.extend(_load_static_model_catalog().validation_warnings)
    except CatalogResourceError as exc:
        warnings.append(str(exc))
    try:
        _load_static_tracker_catalog()
    except CatalogResourceError as exc:
        warnings.append(str(exc))
    return warnings


def _task_allowed_for_workflow(task: CatalogTask, workflow: CatalogWorkflow | None) -> bool:
    if workflow is None or workflow == "model_hub":
        return True
    if workflow == "training":
        return task in {"detect", "segment", "semantic_segment"}
    if workflow == "prompt_assist":
        return task in {
            "assist_segmentation",
            "open_vocabulary_detect",
            "example_guided_detect",
            "phrase_grounding",
            "caption",
        }
    if workflow == "smart_mask":
        return task == "assist_segmentation"
    if workflow == "video":
        return task in {"track", "video_propagation", "metric_video_depth"}
    return True


def _installed_provider_version(provider_id: str) -> str | None:
    distribution = {
        "ultralytics": "ultralytics",
        "depth_anything_v2": "transformers",
    }.get(provider_id)
    if distribution is None:
        return None
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class ModelCatalogService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.models = ModelRepository(session)

    def _project(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _latest_install_jobs(self, project_id: str) -> dict[str, Job]:
        jobs = list(
            self.session.scalars(
                select(Job)
                .where(Job.project_id == project_id, Job.job_type == "model_install")
                .order_by(Job.created_at.desc(), Job.id.desc())
            )
        )
        latest: dict[str, Job] = {}
        for job in jobs:
            catalog_id = str(job.request_json.get("catalog_id") or "")
            if catalog_id and catalog_id not in latest:
                latest[catalog_id] = job
        return latest

    def _compose_static_state(
        self,
        entry: ModelCatalogEntryResponse,
        *,
        job: Job | None,
        manifest: dict[str, Any],
    ) -> ModelCatalogEntryResponse:
        updates: dict[str, Any] = {
            "installation_job_id": None,
            "installed_asset_id": None,
            "installed_path": None,
            "installed_checksum": None,
        }
        if entry.availability == "unavailable":
            updates.update(
                installation_state="Unavailable",
                installation_reason=entry.installation_reason
                or "This catalog definition is not available for installation.",
            )
            return entry.model_copy(update=updates)

        if job is not None and job.status in {"queued", "running", "cancel_requested"}:
            stage = str((job.result_json or {}).get("stage") or "downloading")
            state: CatalogInstallationState = (
                "Verifying"
                if stage == "verifying"
                else "Installing"
                if stage in {"finalizing", "provider_preflight"}
                else "Downloading"
            )
            updates.update(
                installation_state=state,
                installation_reason=(
                    "Cancellation requested; the worker is stopping safely."
                    if job.status == "cancel_requested"
                    else f"Installation job is {stage.replace('_', ' ')}."
                ),
                installation_job_id=job.id,
            )
            return entry.model_copy(update=updates)

        if entry.provider_id in OPTIONAL_MODEL_SPECS:
            runtime_status = optional_model_status(self.settings, entry.provider_id)
            spec = OPTIONAL_MODEL_SPECS[entry.provider_id]
            updates.update(
                installed_asset_id=(
                    f"optional_model:{entry.provider_id}" if runtime_status["cached"] else None
                ),
                installed_path=(str(runtime_status["path"]) if runtime_status["cached"] else None),
                installed_checksum=(spec.weight_sha256 if runtime_status["verified"] else None),
            )
            if runtime_status["ready"]:
                updates.update(
                    installation_state="Ready",
                    installation_reason=(
                        "Pinned optional model is cached, checksum-verified, "
                        f"and ready via {runtime_status.get('cache_source') or 'local cache'}."
                    ),
                )
            elif runtime_status["cached"] and not runtime_status["verified"]:
                updates.update(
                    installation_state="Corrupted",
                    installation_reason=runtime_status["reason"]
                    or "The optional model cache could not be verified.",
                )
            elif runtime_status["transformers_version"] is None:
                updates.update(
                    installation_state="Provider Required",
                    installation_reason=(
                        "Install the ReefVision advanced-provider runtime before using this model."
                    ),
                )
            elif job is not None and job.status == "failed":
                updates.update(
                    installation_state="Blocked",
                    installation_reason=job.error_message
                    or "The previous optional-model installation failed.",
                    installation_job_id=job.id,
                )
            else:
                updates.update(
                    installation_state="Not Installed",
                    installation_reason=(
                        "The pinned optional model is not installed yet. Use Download in Model Hub."
                    ),
                )
            return entry.model_copy(update=updates)

        record_value = manifest.get("assets", {}).get(entry.catalog_id)
        record = dict(record_value) if isinstance(record_value, dict) else None
        if manifest.get("corrupted"):
            updates.update(
                installation_state="Corrupted",
                installation_reason="The managed catalog manifest is corrupted.",
            )
            return entry.model_copy(update=updates)
        if record is not None and entry.expected_files:
            expected = entry.expected_files[0]
            path = catalog_asset_path(self.settings, entry.catalog_id, expected.filename)
            record_files = record.get("files")
            records_by_name = (
                {str(item.get("filename")): item for item in record_files if isinstance(item, dict)}
                if isinstance(record_files, list)
                else {str(record.get("filename")): record}
            )
            missing = next(
                (
                    item
                    for item in entry.expected_files
                    if not catalog_asset_path(
                        self.settings, entry.catalog_id, item.filename
                    ).is_file()
                ),
                None,
            )
            wrong_size = next(
                (
                    item
                    for item in entry.expected_files
                    if catalog_asset_path(self.settings, entry.catalog_id, item.filename).is_file()
                    and catalog_asset_path(self.settings, entry.catalog_id, item.filename)
                    .stat()
                    .st_size
                    != item.size_bytes
                ),
                None,
            )
            wrong_manifest = next(
                (
                    item
                    for item in entry.expected_files
                    if not isinstance(records_by_name.get(item.filename), dict)
                    or records_by_name[item.filename].get("sha256") != item.sha256
                    or records_by_name[item.filename].get("size_bytes") != item.size_bytes
                ),
                None,
            )
            wrong_checksum = next(
                (
                    item
                    for item in entry.expected_files
                    if catalog_asset_path(self.settings, entry.catalog_id, item.filename).is_file()
                    and catalog_asset_path(self.settings, entry.catalog_id, item.filename)
                    .stat()
                    .st_size
                    == item.size_bytes
                    and _file_sha256(
                        catalog_asset_path(self.settings, entry.catalog_id, item.filename)
                    )
                    != item.sha256
                ),
                None,
            )
            updates.update(
                installed_asset_id=f"catalog_model:{entry.catalog_id}",
                installed_path=relative_catalog_asset_path(
                    self.settings,
                    path if len(entry.expected_files) == 1 else path.parent,
                ),
                installed_checksum=str(record.get("sha256") or "") or None,
            )
            if missing is not None:
                updates.update(
                    installation_state="Corrupted",
                    installation_reason=(
                        f"The managed model file {missing.filename} is missing "
                        "from application data."
                    ),
                )
            elif wrong_size is not None:
                updates.update(
                    installation_state="Corrupted",
                    installation_reason=(
                        f"The managed model file {wrong_size.filename} size no "
                        "longer matches the catalog."
                    ),
                )
            elif wrong_manifest is not None:
                updates.update(
                    installation_state="Corrupted",
                    installation_reason=(
                        "The managed model file manifest is incomplete or invalid."
                    ),
                )
            elif wrong_checksum is not None:
                updates.update(
                    installation_state="Corrupted",
                    installation_reason=(
                        f"The managed model file {wrong_checksum.filename} checksum is invalid."
                    ),
                )
            else:
                updates.update(
                    installation_state="Ready",
                    installation_reason=(
                        "Managed checkpoint is installed and verified for offline use."
                    ),
                )
            return entry.model_copy(update=updates)

        if entry.expected_files:
            provider_version = _installed_provider_version(entry.provider_id)
            if entry.provider_pack_id and provider_version is None:
                updates.update(
                    installation_state="Provider Required",
                    installation_reason=(
                        f"Provider pack {entry.provider_pack_id} is required. "
                        "The catalog definition remains available."
                    ),
                )
            elif job is not None and job.status == "failed":
                updates.update(
                    installation_state="Blocked",
                    installation_reason=job.error_message or "The previous installation failed.",
                    installation_job_id=job.id,
                )
            else:
                updates.update(
                    installation_state="Not Installed",
                    installation_reason="The verified pretrained checkpoint is not installed yet.",
                )
            return entry.model_copy(update=updates)

        if entry.selection_kind == "builtin_architecture":
            updates.update(
                installation_state="Ready",
                installation_reason="Bundled architecture definition is available offline.",
                installed_asset_id=f"builtin_architecture:{entry.architecture_reference}",
            )
            return entry.model_copy(update=updates)

        updates.update(
            installation_state="Unavailable",
            installation_reason=entry.installation_reason or "No validated installer is available.",
        )
        return entry.model_copy(update=updates)

    def list_project_catalog(
        self,
        project_id: str,
        *,
        workflow: CatalogWorkflow | None = None,
        task: CatalogTask | None = None,
        include_unavailable: bool = True,
    ) -> ModelCatalogResponse:
        self._project(project_id)
        static_catalog = _load_static_model_catalog()
        jobs = self._latest_install_jobs(project_id)
        manifest = load_catalog_manifest(self.settings)
        models = [
            self._compose_static_state(
                entry,
                job=jobs.get(entry.catalog_id),
                manifest=manifest,
            )
            for entry in static_catalog.models
            if _task_allowed_for_workflow(entry.task, workflow)
            and (task is None or entry.task == task)
            and (include_unavailable or entry.availability != "unavailable")
        ]
        dynamic = [
            entry
            for entry in self._dynamic_entries(project_id)
            if _task_allowed_for_workflow(entry.task, workflow)
            and (task is None or entry.task == task)
            and (include_unavailable or entry.installation_state != "Unavailable")
        ]
        ordered = sorted(
            [*models, *dynamic],
            key=lambda item: (
                0
                if item.category == "pretrained_catalog"
                else 1
                if item.category == "my_trained_models"
                else 2,
                item.architecture_family.casefold(),
                item.display_name.casefold(),
                item.catalog_id,
            ),
        )
        return static_catalog.model_copy(
            update={"models": ordered, "last_refresh_timestamp": datetime.now(UTC)}
        )

    def get_static_catalog_item(self, catalog_id: str) -> ModelCatalogEntryResponse:
        for entry in _load_static_model_catalog().models:
            if entry.catalog_id == catalog_id:
                return entry
        raise NotFoundError("Catalog model not found")

    def get_project_catalog_item(
        self, project_id: str, catalog_id: str
    ) -> ModelCatalogEntryResponse:
        catalog = self.list_project_catalog(project_id)
        for entry in catalog.models:
            if entry.catalog_id == catalog_id:
                return entry
        raise NotFoundError("Catalog model not found")

    def tracker_catalog(self) -> TrackerCatalogResponse:
        return _load_static_tracker_catalog()

    def resolve_training_selection(
        self, project_id: str, catalog_id: str
    ) -> ResolvedTrainingCatalogSelection:
        entry = self.get_project_catalog_item(project_id, catalog_id)
        if entry.installation_state not in {"Ready", "Available"}:
            raise ValidationError(entry.installation_reason or "The selected model is not ready.")
        if entry.task not in {"detect", "segment", "semantic_segment"}:
            raise ValidationError("The selected catalog model is not a training model")
        if not entry.trainable:
            raise ValidationError("The selected catalog model is not marked trainable")
        if entry.selection_kind == "managed_catalog_model":
            if not entry.installed_asset_id or not entry.installed_checksum:
                raise ValidationError("The managed catalog checkpoint is not verified")
            return ResolvedTrainingCatalogSelection(
                catalog_model_id=entry.catalog_id,
                task=entry.task,
                provider_id=entry.provider_id,
                architecture=entry.architecture_reference,
                initial_checkpoint_source="managed_catalog",
                initial_checkpoint_model_id=None,
                resolved_model_asset_id=entry.installed_asset_id,
                resolved_model_checksum=entry.installed_checksum,
                parameter_registry_version=entry.provider_version,
                installation_state=entry.installation_state,
                selected_preset=entry.display_name,
            )
        if entry.selection_kind == "builtin_architecture":
            if not entry.architecture_reference:
                raise ValidationError("The selected model is missing its architecture reference")
            return ResolvedTrainingCatalogSelection(
                catalog_model_id=entry.catalog_id,
                task=entry.task,
                provider_id=entry.provider_id,
                architecture=entry.architecture_reference,
                initial_checkpoint_source="scratch",
                initial_checkpoint_model_id=None,
                resolved_model_asset_id=f"builtin_architecture:{entry.architecture_reference}",
                resolved_model_checksum=entry.expected_checksum,
                parameter_registry_version=entry.provider_version,
                installation_state=entry.installation_state,
                selected_preset=entry.display_name,
            )
        if entry.selection_kind == "registered_model":
            if not entry.resolved_model_id:
                raise ValidationError("The selected project model is missing its registration id")
            return ResolvedTrainingCatalogSelection(
                catalog_model_id=entry.catalog_id,
                task=entry.task,
                provider_id=entry.provider_id,
                architecture=entry.architecture_reference,
                initial_checkpoint_source="registered_model",
                initial_checkpoint_model_id=entry.resolved_model_id,
                resolved_model_asset_id=f"registered_model:{entry.resolved_model_id}",
                resolved_model_checksum=entry.expected_checksum,
                parameter_registry_version=entry.provider_version,
                installation_state=entry.installation_state,
                selected_preset=entry.display_name,
            )
        raise ValidationError("The selected catalog model is not available for training")

    def _dynamic_entries(self, project_id: str) -> list[ModelCatalogEntryResponse]:
        return [
            self._dynamic_entry_from_model(model)
            for model in self.models.list_for_project(project_id)
        ]

    def _dynamic_entry_from_model(self, model: ModelRegistration) -> ModelCatalogEntryResponse:
        metadata = dict(model.metadata_json)
        category = (
            "my_trained_models"
            if metadata.get("registered_from") == "training_run"
            else "imported_custom_models"
        )
        advanced_only = category == "imported_custom_models"
        task: CatalogTask = "assist_segmentation" if model.purpose == "assist" else "detect"
        architecture_reference = None
        source_architecture = metadata.get("source_architecture")
        if isinstance(source_architecture, str) and source_architecture.strip():
            architecture_reference = source_architecture.strip()
        architecture_family = architecture_reference or str(
            metadata.get("source_architecture_family") or model.framework or model.provider_name
        )
        model_size = metadata.get("source_model_size")
        input_size = (
            model.input_size_json.get("imgsz") if isinstance(model.input_size_json, dict) else None
        )
        supported_runtimes = [model.framework]
        license_summary = (
            "User-managed checkpoint; ReefVision does not infer redistribution rights."
        )
        return ModelCatalogEntryResponse(
            catalog_id=f"registered-model/{model.id}",
            display_name=model.display_name,
            display_summary=(
                "Previously trained ReefVision model that can be selected with one click."
                if category == "my_trained_models"
                else "Imported custom model kept in the project's managed storage."
            ),
            category=category,
            provider_id=model.provider_name,
            architecture=architecture_family,
            variant=str(model_size or model.task),
            task=task,
            trainable=model.purpose == "detector",
            inference_supported=True,
            checkpoint_identifier=model.source_filename,
            download_source_type="project_model_registration",
            expected_files=[],
            expected_size=model.file_size_bytes,
            license_summary=license_summary,
            provider_pack_id=None,
            recommended_ram=None,
            recommended_vram=None,
            supported_devices=["cpu", "cuda"],
            supported_runtimes=supported_runtimes,
            desktop_support="project_data",
            availability="available",
            provider=model.provider_name,
            provider_version=model.provider_version,
            architecture_family=architecture_family,
            model_variant=model.task,
            model_size=str(model_size).strip()
            if isinstance(model_size, str) and model_size.strip()
            else None,
            inference=True,
            video_compatibility=False,
            prompt_assist_compatibility=model.purpose == "assist",
            tiling_compatibility=False,
            tuning_compatibility=False,
            checkpoint_source="project_model_registration",
            expected_checksum=model.sha256,
            expected_file_size=model.file_size_bytes,
            model_weight_license=license_summary,
            package_license="Runtime package licensing depends on the selected provider stack.",
            required_provider_pack=None,
            required_package_versions=[],
            supported_runtime=supported_runtimes,
            supported_precision=["fp32"],
            expected_input_size=(
                {"width": input_size, "height": input_size} if isinstance(input_size, int) else None
            ),
            minimum_recommended_ram_gb=None,
            minimum_recommended_vram_gb=None,
            desktop_package_status="project_data",
            clean_machine_verification_status="project_scoped_registration",
            deprecation_status="active",
            replacement_model_id=None,
            known_limitations=(
                ["Imported custom checkpoints remain part of the advanced workflow."]
                if advanced_only
                else [
                    "Training compatibility depends on the original training architecture metadata."
                ]
            ),
            installation_state="Ready",
            installation_reason="Managed local model registration is available for offline use.",
            installed_asset_id=f"registered_model:{model.id}",
            installed_path=model.managed_path,
            installed_checksum=model.sha256,
            advanced_only=advanced_only,
            requires_confirmation=False,
            selection_kind="registered_model",
            architecture_reference=architecture_reference,
            resolved_model_id=model.id,
        )
