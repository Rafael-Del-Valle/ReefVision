"""Portable scientific classification assignment export contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


ClassificationDataExportFormat = Literal["csv", "json", "npz"]


def _default_formats() -> list[ClassificationDataExportFormat]:
    return ["csv", "json", "npz"]


class ClassificationDataExportRequest(BaseModel):
    formats: list[ClassificationDataExportFormat] = Field(
        default_factory=_default_formats,
        min_length=1,
        max_length=3,
    )
    assignment_status: str = Field(default="accepted", min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_formats(self) -> ClassificationDataExportRequest:
        if len(self.formats) != len(set(self.formats)):
            raise ValueError("Classification data export formats must be unique")
        return self


class ClassificationDataExportResponse(BaseModel):
    artifact_id: str
    project_id: str
    row_count: int = Field(ge=0)
    archive_path: str
    manifest_path: str
    archive_sha256: str
    archive_size_bytes: int = Field(ge=0)
    manifest_sha256: str
    formats: list[str]
    matched_measurement_count: int = Field(ge=0)
    unmatched_measurement_count: int = Field(ge=0)
    ambiguous_measurement_count: int = Field(ge=0)
    warnings: list[str]
