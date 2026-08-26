"""Typed scientific Results Package API contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ResultsPackageOptions(BaseModel):
    include_excel: bool = True
    include_machine_data: bool = True
    include_native_artifacts: bool = True
    include_logs: bool = True
    checkpoint_mode: Literal["none", "best", "best_and_last", "retained"] = "best"


class ResultsPackageFileEntry(BaseModel):
    relative_path: str
    category: str
    source_type: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    media_type: str | None = None


class ResultsPackageResponse(BaseModel):
    run_id: str
    package_type: Literal["training", "tuning"]
    package_name: str
    archive_name: str
    archive_size_bytes: int
    verification_status: Literal["verified"]
    warnings: list[str]
    download_url: str


class ResultsPackageVerificationResponse(BaseModel):
    valid: bool
    checked_files: int
    errors: list[str]
