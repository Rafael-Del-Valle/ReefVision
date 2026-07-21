"""Typed API models for provider discovery, lifecycle, and software acceptance."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ProviderAssetState = Literal[
    "ready",
    "unavailable",
    "degraded",
    "loading",
    "loaded",
    "failed",
    "unloaded",
]
ProviderDeviceMode = Literal["auto", "cpu", "cuda"]


class ProviderFileRecordResponse(BaseModel):
    relative_path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)


class ProviderModelAssetResponse(BaseModel):
    id: str
    provider_id: str
    provider_version: str
    model_id: str
    architecture: str
    task: str
    capabilities: dict[str, bool]
    checkpoint_path: str
    checkpoint_path_kind: Literal["managed", "trusted_external"]
    checkpoint_sha256: str | None = None
    checkpoint_size_bytes: int | None = Field(default=None, ge=0)
    checkpoint_format: str
    file_manifest: list[ProviderFileRecordResponse]
    source: str
    revision: str | None = None
    license_metadata: dict[str, Any]
    required_packages: list[str]
    optional_packages: list[str]
    supported_devices: list[str]
    preferred_device: ProviderDeviceMode
    estimated_vram_bytes: int | None = Field(default=None, ge=0)
    input_types: list[str]
    output_types: list[str]
    prompt_types: list[str]
    supports_training: bool
    supports_inference: bool
    supports_video: bool
    state: ProviderAssetState
    failure_reason: str | None = None
    verification: dict[str, Any]
    last_health_check: dict[str, Any]
    last_health_check_at: datetime | None = None
    last_successful_load_at: datetime | None = None
    last_successful_inference_at: datetime | None = None
    metadata: dict[str, Any]
    latest_acceptance_status: str | None = None
    created_at: datetime
    updated_at: datetime


class ProviderModelAssetListResponse(BaseModel):
    items: list[ProviderModelAssetResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    duplicate_checksum_groups: list[list[str]] = Field(default_factory=list)


class ProviderDiscoveryResponse(BaseModel):
    discovered_count: int = Field(ge=0)
    managed_count: int = Field(ge=0)
    external_count: int = Field(ge=0)
    verified_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    duplicate_checksum_groups: list[list[str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TrustedExternalModelRegisterRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=300)
    provider_id: Literal["segment_anything", "depth_anything_v2"]
    architecture: str = Field(min_length=1, max_length=200)
    task: Literal["assist_segmentation", "depth"]
    checkpoint_path: str = Field(min_length=1, max_length=1200)
    source: str = Field(default="trusted_external_registration", min_length=1, max_length=500)
    revision: str | None = Field(default=None, max_length=200)
    license_metadata: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool

    @field_validator("model_id", "architecture", "checkpoint_path", "source", mode="before")
    @classmethod
    def strip_required(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_pairing(self) -> TrustedExternalModelRegisterRequest:
        if self.provider_id == "segment_anything" and self.task != "assist_segmentation":
            raise ValueError("segment_anything registrations must use assist_segmentation")
        if self.provider_id == "depth_anything_v2" and self.task != "depth":
            raise ValueError("depth_anything_v2 registrations must use depth")
        return self


class ProviderDeviceRequest(BaseModel):
    device: ProviderDeviceMode = "auto"


class ProviderHealthRequest(ProviderDeviceRequest):
    kind: Literal["metadata", "load"] = "metadata"
    keep_loaded: bool = False


class ProviderLifecycleActionResponse(BaseModel):
    asset: ProviderModelAssetResponse
    action: str
    state: ProviderAssetState
    resolved_device: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ProviderInferenceRequest(ProviderDeviceRequest):
    request_id: str = Field(min_length=1, max_length=100)
    source_path: str | None = Field(default=None, min_length=1, max_length=1200)
    image_id: str | None = Field(default=None, min_length=36, max_length=36)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def exactly_one_source(self) -> ProviderInferenceRequest:
        if bool(self.source_path) == bool(self.image_id):
            raise ValueError("Choose exactly one managed source path or project image ID")
        return self


class ProviderInferenceResponse(BaseModel):
    request_id: str
    provider_id: str
    model_id: str
    task: str
    resolved_device: str
    outputs: list[dict[str, Any]]
    metadata: dict[str, Any]
    warnings: list[str]


class ProviderCancelResponse(BaseModel):
    request_id: str
    cancellation_requested: bool


class ProviderMetadataRepairRequest(BaseModel):
    confirmed: bool


class ProviderAcceptanceRecordResponse(BaseModel):
    id: str
    run_id: str
    provider_asset_id: str | None = None
    provider_id: str
    model_id: str
    checkpoint_sha256: str | None = None
    device: str
    runtime_versions: dict[str, str]
    load_result: str
    inference_result: str
    unload_result: str
    peak_memory_bytes: int | None = Field(default=None, ge=0)
    execution_time_ms: int = Field(ge=0)
    warnings: list[str]
    failure_reason: str | None = None
    test_input_identifier: str
    details: dict[str, Any]
    validation_kind: Literal["software_acceptance"]
    recorded_at: datetime


class ProviderAcceptanceRecordListResponse(BaseModel):
    items: list[ProviderAcceptanceRecordResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
