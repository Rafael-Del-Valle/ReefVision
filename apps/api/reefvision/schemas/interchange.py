"""Bidirectional dataset and annotation interchange schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

InterchangeFormat = Literal[
    "coco_detection",
    "coco_instance",
    "coco_panoptic",
    "cvat",
    "labelme",
    "roboflow_coco",
    "roboflow_yolo",
]
ClassConflictPolicy = Literal["error", "skip", "merge"]
ExistingAnnotationPolicy = Literal["append", "skip_image", "replace_imported", "error"]


class InterchangePreviewRequest(BaseModel):
    format: InterchangeFormat
    document: dict[str, Any]
    class_mapping: dict[str, str] = Field(default_factory=dict)
    create_missing_classes: bool = False
    class_conflict_policy: ClassConflictPolicy = "error"
    existing_annotation_policy: ExistingAnnotationPolicy = "append"
    source_name: str | None = Field(default=None, max_length=500)


class InterchangeCategoryMapping(BaseModel):
    source_key: str
    source_name: str
    target_class_id: str | None
    target_class_name: str | None
    resolution: Literal["matched", "explicit", "create", "skip", "conflict", "unmapped"]
    message: str | None = None


class InterchangeImageMatch(BaseModel):
    source_key: str
    source_filename: str
    target_image_id: str | None
    target_filename: str | None
    status: Literal["matched", "missing", "ambiguous", "dimension_mismatch"]
    annotation_count: int = Field(ge=0)
    message: str | None = None


class InterchangePreviewResponse(BaseModel):
    project_id: str
    format: InterchangeFormat
    preview_checksum: str
    valid: bool
    source_category_count: int
    matched_category_count: int
    created_category_count: int
    skipped_category_count: int
    source_image_count: int
    matched_image_count: int
    missing_image_count: int
    source_annotation_count: int
    importable_box_count: int
    importable_mask_count: int
    mappings: list[InterchangeCategoryMapping]
    images: list[InterchangeImageMatch]
    warnings: list[str]
    blockers: list[str]


class InterchangeApplyRequest(InterchangePreviewRequest):
    preview_checksum: str = Field(min_length=64, max_length=64)


class InterchangeApplyResponse(BaseModel):
    project_id: str
    format: InterchangeFormat
    preview_checksum: str
    created_class_ids: list[str]
    created_annotation_ids: list[str]
    created_mask_annotation_ids: list[str]
    skipped_annotation_count: int
    affected_image_ids: list[str]
    warnings: list[str]


class InterchangeExportRequest(BaseModel):
    format: InterchangeFormat
    image_ids: list[str] = Field(default_factory=list, max_length=100_000)
    include_images: bool = True
    include_boxes: bool = True
    include_masks: bool = True
    include_archived_classes: bool = False

    @model_validator(mode="after")
    def require_geometry(self) -> InterchangeExportRequest:
        if not self.include_boxes and not self.include_masks:
            raise ValueError("At least one geometry type must be exported")
        return self


class InterchangeExportResponse(BaseModel):
    project_id: str
    export_id: str
    format: InterchangeFormat
    archive_path: str
    manifest_path: str
    archive_sha256: str
    archive_size_bytes: int
    image_count: int
    box_annotation_count: int
    mask_annotation_count: int
    warnings: list[str]
