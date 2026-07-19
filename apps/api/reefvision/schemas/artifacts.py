"""Unified artifact provenance API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArtifactCreateRequest(BaseModel):
    artifact_type: str = Field(min_length=1, max_length=100)
    created_by: str = Field(default="local_user", min_length=1, max_length=120)
    source_kind: str | None = Field(default=None, max_length=80)
    source_id: str | None = Field(default=None, max_length=120)
    source_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_annotation_revision: int | None = Field(default=None, ge=0)
    dataset_version_id: str | None = None
    dataset_version_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    model_id: str | None = None
    model_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provider_id: str | None = Field(default=None, max_length=120)
    provider_version: str | None = Field(default=None, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)
    postprocessing: dict[str, Any] = Field(default_factory=dict)
    review_status: str = Field(default="unreviewed", max_length=40)
    parent_artifact_id: str | None = None
    supersedes_artifact_id: str | None = None
    managed_path: str | None = Field(default=None, max_length=800)
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_and_content(self) -> ArtifactCreateRequest:
        if (self.source_kind is None) != (self.source_id is None):
            raise ValueError("source_kind and source_id must be supplied together")
        if self.managed_path is None and not self.payload:
            raise ValueError("Artifact creation requires managed_path or payload")
        return self


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    artifact_type: str
    created_by: str
    reefvision_version: str
    source_kind: str | None
    source_id: str | None
    source_checksum: str | None
    source_annotation_revision: int | None
    dataset_version_id: str | None
    dataset_version_checksum: str | None
    model_id: str | None
    model_checksum: str | None
    provider_id: str | None
    provider_version: str | None
    parameters_json: dict[str, Any]
    postprocessing_json: dict[str, Any]
    review_status: str
    parent_artifact_id: str | None
    supersedes_artifact_id: str | None
    managed_path: str | None
    checksum: str
    size_bytes: int | None
    metadata_json: dict[str, Any]
    created_at: datetime


class ArtifactLineageResponse(BaseModel):
    artifact: ArtifactResponse
    ancestors: list[ArtifactResponse]
    descendants: list[ArtifactResponse]
    superseded_by: list[ArtifactResponse]


class ArtifactPreviewResponse(BaseModel):
    artifact_id: str
    preview_kind: Literal[
        "image",
        "video",
        "audio",
        "html",
        "json",
        "text",
        "table",
        "archive",
        "binary",
        "payload",
    ]
    media_type: str | None
    content_url: str | None
    filename: str | None
    text: str | None
    payload: dict[str, Any] | list[Any] | None
    columns: list[str]
    rows: list[list[Any]]
    archive_entries: list[str]
    truncated: bool
    checksum_verified: bool | None
