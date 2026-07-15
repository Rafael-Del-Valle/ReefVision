"""Dataset-version and export API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from reefvision.domain.enums import ANNOTATION_STATUSES, AnnotationStatus
from reefvision.schemas.jobs import JobResponse

DatasetSplit = Literal["train", "validation", "test", "unassigned"]
DatasetSplitMethod = Literal["none", "manual", "random", "group_random"]
DatasetExportFormat = Literal[
    "yolo_detection",
    "yolo_segmentation",
    "semantic_masks",
]
DatasetVersionStatus = Literal[
    "validating",
    "creating",
    "complete",
    "failed",
    "cancelled",
    "archived",
]


def default_eligible_statuses() -> list[AnnotationStatus]:
    return ["reviewed"]


class SplitRatios(BaseModel):
    train: float = Field(default=0.7, ge=0, le=1)
    validation: float = Field(default=0.2, ge=0, le=1)
    test: float = Field(default=0.1, ge=0, le=1)

    @model_validator(mode="after")
    def ensure_some_weight(self) -> SplitRatios:
        if self.train + self.validation + self.test <= 0:
            raise ValueError("At least one split ratio must be greater than zero")
        return self


class ManualSplitAssignment(BaseModel):
    image_id: str
    split: DatasetSplit


class DatasetVersionPreviewRequest(BaseModel):
    parent_version_id: str | None = None
    eligible_annotation_statuses: list[AnnotationStatus] = Field(
        default_factory=default_eligible_statuses
    )
    split_method: DatasetSplitMethod = "group_random"
    requested_ratios: SplitRatios | None = None
    split_seed: int | None = None
    reuse_parent_assignments: bool = False
    manual_assignments: list[ManualSplitAssignment] = Field(default_factory=list)

    @field_validator("eligible_annotation_statuses")
    @classmethod
    def normalize_statuses(
        cls,
        values: list[AnnotationStatus],
    ) -> list[AnnotationStatus]:
        if not values:
            raise ValueError("Choose at least one eligible annotation status")
        ordered = [status for status in ANNOTATION_STATUSES if status in values]
        if not ordered:
            raise ValueError("Choose at least one eligible annotation status")
        return ordered


class DatasetVersionCreateRequest(DatasetVersionPreviewRequest):
    name: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    creator: str | None = Field(default=None, max_length=100)

    @field_validator("name", "notes", "creator")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DatasetVersionPreviewClassCount(BaseModel):
    label_class_id: str
    class_index: int
    class_name: str
    count: int
    mask_count: int = 0


class DatasetVersionPreviewImage(BaseModel):
    image_id: str
    original_filename: str
    annotation_status: AnnotationStatus
    group_key: str | None
    annotation_count: int
    mask_annotation_count: int = 0
    proposed_split: DatasetSplit


class DatasetVersionSplitSummary(BaseModel):
    split: DatasetSplit
    image_count: int
    annotation_count: int
    mask_annotation_count: int = 0


class DatasetVersionPreviewResponse(BaseModel):
    requested_split_method: DatasetSplitMethod
    resolved_split_method: DatasetSplitMethod
    eligible_image_count: int
    eligible_annotation_count: int
    eligible_mask_annotation_count: int = 0
    missing_group_key_count: int
    warnings: list[str]
    split_summary: list[DatasetVersionSplitSummary]
    per_class_counts: list[DatasetVersionPreviewClassCount]
    images: list[DatasetVersionPreviewImage]


class DatasetVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    version_number: int
    name: str
    notes: str | None
    parent_version_id: str | None
    status: DatasetVersionStatus
    requested_split_method: DatasetSplitMethod
    resolved_split_method: DatasetSplitMethod
    eligible_annotation_statuses_json: list[str]
    requested_ratios_json: dict[str, float] | None
    achieved_ratios_json: dict[str, float] | None
    split_seed: int | None
    reuse_parent_assignments: bool
    missing_group_key_count: int
    warnings_json: list[str]
    class_map_json: list[dict[str, Any]]
    manifest_sha256: str
    image_count: int
    annotation_count: int
    mask_annotation_count: int = 0
    created_by: str
    reefvision_version: str
    schema_version: str
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class DatasetVersionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_version_id: str
    image_id: str
    image_sha256: str
    original_filename: str
    width_px: int
    height_px: int
    image_annotation_status: str
    split: DatasetSplit
    group_key: str | None
    annotation_snapshot_json: list[dict[str, Any]]
    mask_annotation_snapshot_json: list[dict[str, Any]] = Field(default_factory=list)
    per_class_counts_json: dict[str, int]
    per_mask_class_counts_json: dict[str, int] = Field(default_factory=dict)
    annotation_count: int
    mask_annotation_count: int = 0
    snapshot_sha256: str
    created_at: datetime


class DatasetVersionManifestResponse(BaseModel):
    dataset_version_id: str
    manifest_sha256: str
    manifest_json: dict[str, Any]


class DatasetVersionComparisonItem(BaseModel):
    image_id: str
    original_filename: str
    from_split: DatasetSplit | None
    to_split: DatasetSplit | None
    from_annotation_count: int
    to_annotation_count: int


class DatasetVersionComparisonResponse(BaseModel):
    base_version_id: str
    compare_version_id: str
    added_images: list[DatasetVersionComparisonItem]
    removed_images: list[DatasetVersionComparisonItem]
    changed_images: list[DatasetVersionComparisonItem]
    annotation_delta: int


class DatasetExportCreateRequest(BaseModel):
    format: DatasetExportFormat = "yolo_detection"


class ExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    dataset_version_id: str
    job_id: str | None
    format: str
    output_path: str
    manifest_path: str
    archive_path: str
    request_json: dict[str, Any]
    status: str
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class DatasetExportCreateResponse(BaseModel):
    export: ExportResponse
    job: JobResponse
