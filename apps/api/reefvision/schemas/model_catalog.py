"""Validated model-catalog definitions and lightweight installation-state schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CatalogCategory = Literal[
    "pretrained_catalog",
    "my_trained_models",
    "imported_custom_models",
]
CatalogTask = Literal[
    "detect",
    "segment",
    "semantic_segment",
    "open_vocabulary_detect",
    "example_guided_detect",
    "assist_segmentation",
    "video_propagation",
    "track",
    "caption",
    "phrase_grounding",
    "relative_depth",
]
CatalogInstallationState = Literal[
    "Available",
    "Not Installed",
    "Provider Required",
    "Downloading",
    "Verifying",
    "Installing",
    "Ready",
    "Update Available",
    "Incompatible",
    "Blocked",
    "Corrupted",
    "Unavailable",
]
CatalogSelectionKind = Literal[
    "builtin_architecture",
    "managed_catalog_model",
    "registered_model",
    "planned_unavailable",
]
CatalogDeprecationStatus = Literal["active", "deprecated", "experimental"]
CatalogWorkflow = Literal["training", "prompt_assist", "smart_mask", "video", "model_hub"]
CatalogAvailability = Literal["available", "experimental", "unavailable"]


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class CatalogInputSize(BaseModel):
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


class CatalogExpectedFile(BaseModel):
    """One allow-listed asset required by an installable catalog entry."""

    filename: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(gt=0)

    @field_validator("filename", "source_url", "revision", "sha256", mode="before")
    @classmethod
    def strip_file_strings(cls, value: object) -> object:
        return _strip(value) if isinstance(value, str) or value is None else value

    @model_validator(mode="after")
    def validate_trusted_file(self) -> CatalogExpectedFile:
        if "/" in self.filename or "\\" in self.filename:
            raise ValueError("expected filenames must not contain path separators")
        approved_ultralytics = self.source_url.startswith(
            "https://github.com/ultralytics/assets/releases/download/"
        )
        approved_depth_anything = (
            self.source_url.startswith(
                "https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf/resolve/"
            )
            and len(self.revision) == 40
            and all(character in "0123456789abcdef" for character in self.revision.lower())
            and self.source_url.endswith(f"/{self.revision}/{self.filename}")
        )
        if not (approved_ultralytics or approved_depth_anything):
            raise ValueError("catalog downloads must use an approved HTTPS source")
        if self.source_url.rsplit("/", 1)[-1] != self.filename:
            raise ValueError("download URL filename must match the expected filename")
        if any(character not in "0123456789abcdefABCDEF" for character in self.sha256):
            raise ValueError("sha256 must contain only hexadecimal characters")
        return self


class ModelCatalogEntryResponse(BaseModel):
    # Definition fields. These are sufficient to render a card without importing a provider.
    catalog_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    display_summary: str = Field(min_length=1)
    category: CatalogCategory
    provider_id: str = Field(min_length=1)
    architecture: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    task: CatalogTask
    trainable: bool
    inference_supported: bool
    checkpoint_identifier: str | None = None
    download_source_type: str = Field(min_length=1)
    expected_files: list[CatalogExpectedFile] = Field(default_factory=list)
    expected_size: int | None = Field(default=None, ge=0)
    license_summary: str = Field(min_length=1)
    provider_pack_id: str | None = None
    recommended_ram: float | None = Field(default=None, ge=0)
    recommended_vram: float | None = Field(default=None, ge=0)
    supported_devices: list[str] = Field(default_factory=list)
    supported_runtimes: list[str] = Field(default_factory=list)
    desktop_support: str = Field(min_length=1)
    availability: CatalogAvailability

    # Compatibility/detail fields retained for existing ReefVision consumers.
    provider: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    architecture_family: str = Field(min_length=1)
    model_variant: str = Field(min_length=1)
    model_size: str | None = None
    inference: bool
    video_compatibility: bool
    prompt_assist_compatibility: bool
    tiling_compatibility: bool
    tuning_compatibility: bool
    checkpoint_source: str = Field(min_length=1)
    expected_checksum: str | None = Field(default=None, min_length=64, max_length=64)
    expected_file_size: int | None = Field(default=None, ge=0)
    model_weight_license: str = Field(min_length=1)
    package_license: str = Field(min_length=1)
    required_provider_pack: str | None = None
    required_package_versions: list[str] = Field(default_factory=list)
    supported_runtime: list[str] = Field(default_factory=list)
    supported_precision: list[str] = Field(default_factory=list)
    expected_input_size: CatalogInputSize | None = None
    minimum_recommended_ram_gb: float | None = Field(default=None, ge=0)
    minimum_recommended_vram_gb: float | None = Field(default=None, ge=0)
    desktop_package_status: str = Field(min_length=1)
    clean_machine_verification_status: str = Field(min_length=1)
    deprecation_status: CatalogDeprecationStatus = "active"
    replacement_model_id: str | None = None
    known_limitations: list[str] = Field(default_factory=list)

    # Local state fields. The service derives these and never uses them to filter definitions.
    installation_state: CatalogInstallationState
    installation_reason: str | None = None
    installation_job_id: str | None = None
    installed_asset_id: str | None = None
    installed_path: str | None = None
    installed_checksum: str | None = None
    advanced_only: bool = False
    requires_confirmation: bool = False
    selection_kind: CatalogSelectionKind
    architecture_reference: str | None = None
    resolved_model_id: str | None = None

    @field_validator(
        "display_name",
        "display_summary",
        "provider_id",
        "architecture",
        "variant",
        "checkpoint_identifier",
        "download_source_type",
        "license_summary",
        "provider_pack_id",
        "desktop_support",
        "provider",
        "provider_version",
        "architecture_family",
        "model_variant",
        "model_size",
        "checkpoint_source",
        "model_weight_license",
        "package_license",
        "required_provider_pack",
        "desktop_package_status",
        "clean_machine_verification_status",
        "replacement_model_id",
        "installation_reason",
        "installation_job_id",
        "installed_asset_id",
        "installed_path",
        "installed_checksum",
        "architecture_reference",
        "resolved_model_id",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value: object) -> object:
        return _strip(value) if isinstance(value, str) or value is None else value

    @model_validator(mode="after")
    def validate_selection_fields(self) -> ModelCatalogEntryResponse:
        if self.selection_kind == "builtin_architecture" and not self.architecture_reference:
            raise ValueError("builtin_architecture entries require architecture_reference")
        if self.selection_kind == "managed_catalog_model" and not self.expected_files:
            raise ValueError("managed_catalog_model entries require expected_files")
        if self.selection_kind == "registered_model" and not self.resolved_model_id:
            raise ValueError("registered_model entries require resolved_model_id")
        if self.selection_kind == "planned_unavailable" and self.availability != "unavailable":
            raise ValueError("planned_unavailable entries must be unavailable")
        if self.expected_files and self.expected_size != sum(
            item.size_bytes for item in self.expected_files
        ):
            raise ValueError("expected_size must equal the sum of expected file sizes")
        return self


class ModelCatalogResponse(BaseModel):
    schema_version: int = Field(ge=1)
    catalog_version: str = Field(min_length=1)
    application_version: str | None = None
    models: list[ModelCatalogEntryResponse]
    validation_warnings: list[str] = Field(default_factory=list)
    rejected_entries: int = Field(default=0, ge=0)
    source_path: str | None = None
    last_refresh_timestamp: datetime | None = None


class CatalogReadinessResponse(BaseModel):
    catalog_id: str
    installation_state: CatalogInstallationState
    installation_reason: str | None = None
    provider_id: str
    provider_version: str | None = None
    provider_ready: bool
    expected_files_valid: bool
    checked_at: datetime


class CatalogInstallRequest(BaseModel):
    confirmed: bool


class CatalogVerifyResponse(BaseModel):
    catalog_id: str
    installation_state: CatalogInstallationState
    verified: bool
    expected_checksum: str | None = None
    actual_checksum: str | None = None
    path: str | None = None
    reason: str | None = None


class TrackerCatalogEntryResponse(BaseModel):
    tracker_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    task: Literal["track"] = "track"
    installation_state: CatalogInstallationState
    installation_reason: str | None = None
    supported_runtime: list[str] = Field(default_factory=list)
    supported_devices: list[str] = Field(default_factory=list)
    desktop_package_status: str = Field(min_length=1)
    clean_machine_verification_status: str = Field(min_length=1)
    known_limitations: list[str] = Field(default_factory=list)
    required_package_versions: list[str] = Field(default_factory=list)

    @field_validator(
        "display_name",
        "provider",
        "provider_version",
        "installation_reason",
        "desktop_package_status",
        "clean_machine_verification_status",
        mode="before",
    )
    @classmethod
    def strip_tracker_strings(cls, value: object) -> object:
        return _strip(value) if isinstance(value, str) or value is None else value


class TrackerCatalogResponse(BaseModel):
    schema_version: int = Field(ge=1)
    catalog_version: str = Field(min_length=1)
    trackers: list[TrackerCatalogEntryResponse]
