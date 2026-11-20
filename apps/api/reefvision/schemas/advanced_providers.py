"""Advanced provider manifest and execution-preflight schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AdvancedProviderTask = Literal[
    "open_vocabulary_detect",
    "example_guided_detect",
    "assist_segmentation",
    "video_propagation",
    "relative_depth",
    "caption",
    "phrase_grounding",
    "visual_question",
    "semantic_segment",
]


class AdvancedProviderManifestResponse(BaseModel):
    provider_id: str
    display_name: str
    maturity: str
    execution_supported: bool
    execution_surface: Literal[
        "provider_lab",
        "existing_workflow",
        "blocked",
    ]
    supported_tasks: list[str]
    prompt_fields_by_task: dict[str, list[str]]
    output_contracts_by_task: dict[str, list[str]]
    required_model_extensions: list[str]
    required_packages: list[str]
    recommended_devices: list[str]
    known_limitations: list[str]
    integration_notes: list[str]
    source_kind: Literal["built_in", "local_manifest"] = "built_in"
    manifest_version: int | None = None
    declared_capabilities: list[str] = Field(default_factory=list)
    availability_status: str | None = None
    availability_reason: str | None = None
    source_filename: str | None = None
    source_sha256: str | None = None
    discovery_status: str = "built_in"
    discovery_errors: list[str] = Field(default_factory=list)


class AdvancedProviderPreflightRequest(BaseModel):
    task: AdvancedProviderTask
    device: str = Field(default="auto", min_length=1, max_length=30)
    model_id: str | None = Field(default=None, max_length=36)
    allow_model_download: bool = False
    prompt_fields: dict[str, object] = Field(default_factory=dict)


class AdvancedProviderPreflightResponse(BaseModel):
    provider_id: str
    task: str
    ready: bool
    execution_supported: bool
    execution_surface: Literal[
        "provider_lab",
        "existing_workflow",
        "blocked",
    ]
    availability_status: str
    blockers: list[str]
    warnings: list[str]
    required_prompt_fields: list[str]
    provided_prompt_fields: list[str]
    missing_prompt_fields: list[str]
    output_contract: list[str]
    selected_model_id: str | None
    selected_device: str
