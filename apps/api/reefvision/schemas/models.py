"""Model registration and inference API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class ModelRegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    purpose: str
    display_name: str
    source_filename: str
    managed_path: str
    sha256: str
    file_size_bytes: int
    framework: str
    task: str
    provider_name: str
    provider_version: str
    class_map_json: dict[str, Any]
    input_size_json: dict[str, Any] | None
    metadata_json: dict[str, Any]
    notes: str | None
    created_at: datetime
    updated_at: datetime


class InferenceJobCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=36)
    image_ids: list[str] = Field(min_length=1)
    confidence_threshold: FiniteFloat | None = Field(default=None, ge=0, le=1)
    iou_threshold: FiniteFloat | None = Field(default=None, ge=0, le=1)
    device: str = Field(default="auto", min_length=1, max_length=20)
    text_prompt: str | None = Field(default=None, max_length=1000)

    @field_validator("text_prompt", mode="before")
    @classmethod
    def strip_text_prompt(cls, value: object) -> object:
        return _strip(value) if isinstance(value, str) or value is None else value


class RegisterModelFromRunRequest(BaseModel):
    training_run_id: str = Field(min_length=1, max_length=36)
    display_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("display_name", "notes", mode="before")
    @classmethod
    def strip_strings(cls, value: object) -> object:
        return _strip(value) if isinstance(value, str) or value is None else value


class ProviderDependencyPackageResponse(BaseModel):
    distribution_name: str
    required_version: str
    installed_version: str | None
    status: str


class ProviderDependencyStatusResponse(BaseModel):
    provider_name: str
    display_name: str
    purpose: str
    provider_version: str
    status: str
    ready: bool
    tested_python: str
    current_python: str
    tested_platform: str
    current_platform: str
    tested_cuda: str | None
    current_cuda: str | None
    automatic_downloads_disabled: bool
    explicit_checkpoint_required: bool
    requirements_file: str
    packages: list[ProviderDependencyPackageResponse]
    issues: list[str]


class ProviderDependencyPreflightResponse(BaseModel):
    providers: list[ProviderDependencyStatusResponse]


class ModelProviderPackageResponse(BaseModel):
    distribution_name: str
    required_version: str | None
    installed_version: str | None
    status: str


class ModelProviderCapabilityMatrixResponse(BaseModel):
    image_detection: bool
    image_instance_segmentation: bool
    image_semantic_segmentation: bool
    text_prompt_detection: bool
    image_example_detection: bool
    click_prompting: bool
    box_prompting: bool
    brush_prompting: bool
    mask_prompting: bool
    video_propagation: bool
    multi_object_tracking: bool
    training: bool
    validation: bool
    tiled_training: bool
    tiled_inference: bool
    export: bool
    cpu_inference: bool
    cuda_inference: bool
    fp16: bool
    quantized_inference: bool
    packaged_desktop_operation: bool


class ModelProviderResponse(BaseModel):
    provider_id: str
    display_name: str
    provider_version: str
    package_version: str | None
    supported_model_families: list[str]
    supported_tasks: list[str]
    supported_input_types: list[str]
    supported_output_types: list[str]
    cpu_support: bool
    cuda_support: bool
    supported_precision_modes: list[str]
    video_support: bool
    training_support: bool
    tiling_support: bool
    supported_execution_runtimes: list[str]
    required_packages: list[ModelProviderPackageResponse]
    required_model_files: list[str]
    code_license: str
    weight_license: str
    memory_recommendations: list[str]
    known_limitations: list[str]
    desktop_packaging_state: str
    clean_machine_verification_state: str
    availability_status: str
    availability_reason: str | None
    default_registration_purpose: str | None
    registerable: bool
    capabilities: ModelProviderCapabilityMatrixResponse


class RuntimeProviderStatusResponse(BaseModel):
    runtime_id: str
    display_name: str
    package_name: str | None
    package_version: str | None
    available: bool
    status: str
    supports_cpu: bool
    supports_cuda: bool
    notes: list[str]


class UltralyticsTrainingRegistrySummaryResponse(BaseModel):
    parameter_count: int
    reefvision_supported_parameter_count: int
    tunable_parameter_count: int
    native_tune_parameter_count: int
    fixed_only_parameter_count: int


class UltralyticsTrainingRegistryParameterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    display_name: str
    category: str
    value_type: str
    default_value: Any
    minimum: float | int | None
    maximum: float | int | None
    choices: list[Any]
    supported_tasks: list[str]
    supported_modes: list[str]
    reefvision_supported: bool
    tunable: bool
    fixed_only: bool
    native_tune_default: bool
    help_text: str
    dependency_rules: list[str]
    supported_version: str
    native_tune_minimum: float | int | None
    native_tune_maximum: float | int | None
    native_tune_gain: float | None
    native_tune_scale: str | None


class UltralyticsTrainingRegistryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider_name: str
    provider_version: str
    ultralytics_version: str | None
    pinned_version_matches_installed: bool
    supported_tasks: list[str]
    supported_modes: list[str]
    method_signatures: dict[str, str]
    summary: UltralyticsTrainingRegistrySummaryResponse
    parameters: list[UltralyticsTrainingRegistryParameterResponse]


class UltralyticsSearchSpaceFieldRequest(BaseModel):
    name: str = Field(min_length=1)
    minimum: float | int | None = None
    maximum: float | int | None = None
    discrete_values: list[Any] = Field(default_factory=list)
    fixed_value: Any = None
    scale: str = Field(default="linear", min_length=1)
    integer: bool | None = None


class UltralyticsTrainingConfigurationValidationRequest(BaseModel):
    task: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    expected_ultralytics_version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    search_space: list[UltralyticsSearchSpaceFieldRequest] = Field(default_factory=list)


class UltralyticsValidatedSearchSpaceFieldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    minimum: float | int | None
    maximum: float | int | None
    discrete_values: list[Any]
    fixed_value: Any
    scale: str
    integer: bool


class UltralyticsTrainingConfigurationValidationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ultralytics_version: str | None
    requested_mode: str
    normalized_mode: str
    validated_parameters: dict[str, Any]
    validated_search_space: list[UltralyticsValidatedSearchSpaceFieldResponse]
    warnings: list[str]
