"""Image import, listing, and update schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from reefvision.domain.enums import AnnotationStatus

ImportItemStatus = Literal["successful", "duplicate", "unsupported", "failed"]


class ImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    original_filename: str
    managed_path: str
    thumbnail_path: str | None
    sha256: str
    width_px: int
    height_px: int
    file_size_bytes: int
    media_type: str
    import_source: str | None
    capture_timestamp: datetime | None
    group_key: str | None
    metadata_json: dict[str, Any]
    annotation_status: str
    annotation_revision: int
    annotation_count: int = 0
    created_at: datetime
    updated_at: datetime

    @field_validator("capture_timestamp")
    @classmethod
    def normalize_capture_timestamp_utc(cls, value: datetime | None) -> datetime | None:
        """Restore UTC on API reads after SQLite drops stored datetime offsets."""
        if value is None:
            return None
        if value.tzinfo is None:
            # Image ingestion normalizes EXIF acquisition times to UTC before
            # persistence; SQLite's DateTime adapter loses that timezone marker.
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ImageListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    original_filename: str
    thumbnail_path: str | None
    width_px: int
    height_px: int
    group_key: str | None
    annotation_status: str
    annotation_revision: int
    annotation_count: int = 0
    created_at: datetime
    updated_at: datetime


class ImagePageResponse(BaseModel):
    items: list[ImageListItemResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ImageUpdate(BaseModel):
    group_key: str | None = Field(default=None, max_length=300)
    annotation_status: AnnotationStatus | None = None

    @field_validator("group_key")
    @classmethod
    def normalize_group_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ImportItemResponse(BaseModel):
    filename: str
    relative_path: str | None = None
    status: ImportItemStatus
    detail: str | None = None
    image_id: str | None = None
    duplicate_image_id: str | None = None
    thumbnail_job_id: str | None = None


class ImageImportResponse(BaseModel):
    project_id: str
    successful: list[ImportItemResponse]
    duplicates: list[ImportItemResponse]
    unsupported: list[ImportItemResponse]
    failed: list[ImportItemResponse]

    @property
    def total(self) -> int:
        return sum(
            len(items)
            for items in (self.successful, self.duplicates, self.unsupported, self.failed)
        )
